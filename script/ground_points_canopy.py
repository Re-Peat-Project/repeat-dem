"""Are our calibration ground points too high under forest? ICESat-2 and GEDI ground against the LiDAR, by canopy height.

    python script/ground_points_canopy.py benchmark/mendahara.yaml benchmark/sugihan_lumpur.yaml

Reads, per site, the ICESat-2 ATL08 segments with their quality columns (repeat_common.fetch_icesat2 --attributes:
<processing.ground_points stem>_attrs.gpkg) and the GEDI L2A points (gedi/gedi_l2a_<slug>.gpkg, already quality_flag 1,
degrade_flag 0, sensitivity >= 0.98). Heights are moved from the ellipsoid to EGM2008 (PROJ), then compared with the LiDAR at
the nearest LiDAR cell. The LiDAR's datum is not recorded, so one offset per site is removed: the median of (ICESat-2 as used
now - LiDAR) at points with canopy below 2 m. The canopy height is the Meta/WRI map averaged into each 25 m LiDAR cell.
The LiDAR only judges the points here; nothing is fitted to it.

Variants, fixed 2026-11-13 before any result (filters from the literature: Cobb et al. 2023, Science of Remote Sensing 7:100074;
doi:10.1016/j.rse.2021.112571; doi:10.1016/j.srs.2022.100067; see docs/icesat2-ground-points-canopy.md):
  is2_now        every finite segment, as the processing uses now (the 10-photon cut was never applied, see fetch_icesat2)
  is2_photons    at least 10 ground photons per 100 m segment (the cut the fetch meant to apply)
  is2_strong_night  is2_photons, strong beams (spots 1, 3, 5) and night (solar elevation < 0)
  is2_spatial    is2_strong_night, then a spatial filter for misclassified canopy: a point is dropped when it lies more than
                 1.0 m above the median of the other points within 500 m (at least 5 of them); two passes. Only high outliers
                 are dropped, because canopy mistaken for ground is always too high. Cobb et al. used a morphological and a
                 spatial filter; we have not read their exact parameters, so this is a filter of the same kind, not theirs.
  gedi_now       GEDI as fetched
  gedi_spatial   gedi_now with the same spatial filter
Judged per variant: median and NMAD of (point - LiDAR - offset) per canopy-height bin, and the slope of the bin medians
(m per m of canopy, bins 0-2, 2-5, 5-10, 10-15, 15-20, 20-25, 25-35 m with >= 30 points). A good calibration set has a slope near 0.

Writes 01_dem/benchmark/11_ground_points/: ground_points_bins.csv, ground_points_summary.csv, ground_points_<variant>.gpkg
(the filtered points, for a recalibration run), ground_points_canopy_<theme>.png.
"""
import argparse
import os
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import rasterio
import yaml
from pyproj import Transformer
from scipy.spatial import cKDTree

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dem_benchmark import out_dir  # noqa: E402
from dem_benchmark_canopy import canopy_on_grid  # noqa: E402

EDGES = [0, 2, 5, 10, 15, 20, 25, 35]
RADIUS_M, ABOVE_M, MIN_NB, PASSES = 500.0, 1.0, 5, 2
LABEL = {"is2_now": "ICESat-2, as used now", "is2_photons": "ICESat-2, ≥10 ground photons", "is2_strong_night": "ICESat-2, + strong beams at night",
         "is2_spatial": "ICESat-2, + spatial filter", "gedi_now": "GEDI, as fetched", "gedi_spatial": "GEDI, + spatial filter"}
COLOR = {"is2_now": "#9e9e9e", "is2_photons": "#74add1", "is2_strong_night": "#2166ac", "is2_spatial": "#d6604d", "gedi_now": "#b8e186",
         "gedi_spatial": "#1b7837"}
THEMES = {"light": {"bg": "white", "fg": "#222222", "grid": "#dddddd"}, "dark": {"bg": "#16181c", "fg": "#e8e8e8", "grid": "#33363c"}}


def spatial_filter(x, y, h):
    keep = np.ones(len(h), bool)
    for _ in range(PASSES):
        idx = np.flatnonzero(keep)
        tree = cKDTree(np.c_[x[idx], y[idx]])
        drop = np.zeros(len(idx), bool)
        for j, nb in enumerate(tree.query_ball_point(np.c_[x[idx], y[idx]], RADIUS_M)):
            nb = [k for k in nb if k != j]
            if len(nb) >= MIN_NB and h[idx[j]] > np.median(h[idx[nb]]) + ABOVE_M:
                drop[j] = True
        keep[idx[drop]] = False
    return keep


def site(cfg_path):
    cfg = yaml.safe_load(open(cfg_path, encoding="utf-8"))
    data = Path(os.environ.get("REPEAT_DATA") or HERE.parents[1] / "_data")
    out = out_dir(cfg)
    gp = data / cfg["processing"]["ground_points"]
    is2 = gpd.read_file(gp.with_name(gp.stem + "_attrs.gpkg"))
    slug = gp.stem.split("_")[1] + "_" + gp.stem.split("_")[2]
    gedi = gpd.read_file(data / "gedi" / f"gedi_l2a_{slug}.gpkg")
    with rasterio.open(data / cfg["lidar"]["path"]) as r:
        crs, tf, shape = r.crs, r.transform, (r.height, r.width)
        z = r.read(1, masked=True).astype("float64").filled(np.nan)
    z[z < -1e30] = np.nan
    chm = canopy_on_grid(cfg, shape, tf, crs)
    import pyproj
    pyproj.network.set_network_enabled(True)      # the EGM2008 grid comes from the PROJ CDN when it is not installed
    to_h = Transformer.from_crs("EPSG:4979", "EPSG:4326+3855", always_xy=True)
    probe = to_h.transform(104.0, -1.5, 0.0)[2]
    if not np.isfinite(probe) or abs(probe) < 1:  # PROJ passes heights through unchanged when the geoid grid is missing
        sys.exit(f"EGM2008 geoid not applied (N at 104E 1.5S came out {probe}); install the PROJ grid us_nga_egm08_25.tif")
    to_xy = Transformer.from_crs("EPSG:4326", crs, always_xy=True)

    def prep(g):
        lon, lat = g.geometry.x.to_numpy(), g.geometry.y.to_numpy()
        H = to_h.transform(lon, lat, g["h_ell"].to_numpy("float64"))[2]
        x, y = to_xy.transform(lon, lat)
        rows, cols = rasterio.transform.rowcol(tf, x, y)
        rows, cols = np.asarray(rows), np.asarray(cols)
        ok = (rows >= 0) & (rows < shape[0]) & (cols >= 0) & (cols < shape[1])
        zl, ch = np.full(len(H), np.nan), np.full(len(H), np.nan)
        zl[ok], ch[ok] = z[rows[ok], cols[ok]], chm[rows[ok], cols[ok]]
        g = g.assign(H=H, x=x, y=y, lidar=zl, chm=ch)
        return g[np.isfinite(g.lidar) & np.isfinite(g.chm) & np.isfinite(g.H)].copy()

    is2, gedi = prep(is2), prep(gedi)
    V = {"is2_now": is2}
    V["is2_photons"] = is2[is2.gnd_ph_count >= 10]
    V["is2_strong_night"] = V["is2_photons"][V["is2_photons"].strong.astype(bool) & (V["is2_photons"].solar_elevation < 0)]
    s = V["is2_strong_night"]
    V["is2_spatial"] = s[spatial_filter(s.x.to_numpy(), s.y.to_numpy(), s.H.to_numpy())]
    V["gedi_now"] = gedi
    V["gedi_spatial"] = gedi[spatial_filter(gedi.x.to_numpy(), gedi.y.to_numpy(), gedi.H.to_numpy())]
    e0 = V["is2_now"]
    offset = float(np.median((e0.H - e0.lidar)[e0.chm < 2])) if (e0.chm < 2).sum() >= 30 else float(np.median(e0.H - e0.lidar))
    dest = out / "11_ground_points"
    dest.mkdir(exist_ok=True)
    bins, summ = [], []
    for v, g in V.items():
        e = (g.H - g.lidar - offset).to_numpy()
        c = g.chm.to_numpy()
        mids, meds = [], []
        for a, b in zip(EDGES[:-1], EDGES[1:]):
            m = (c >= a) & (c < b)
            if m.sum() >= 30:
                med = float(np.median(e[m]))
                bins.append({"site": cfg["site"], "variant": v, "canopy_m_from": a, "canopy_m_to": b, "points": int(m.sum()),
                             "median_m": round(med, 3), "nmad_m": round(float(1.4826 * np.median(np.abs(e[m] - med))), 3)})
                mids.append((a + b) / 2)
                meds.append(med)
        tall = c >= 15
        summ.append({"site": cfg["site"], "variant": v, "points": len(g), "share_of_source": round(len(g) / len(V["is2_now" if v.startswith("is2") else "gedi_now"]), 3),
                     "points_canopy_ge_15m": int(tall.sum()),
                     "median_canopy_lt_2m": round(float(np.median(e[c < 2])), 3) if (c < 2).sum() else None,
                     "median_canopy_ge_15m": round(float(np.median(e[tall])), 3) if tall.sum() else None,
                     "nmad_canopy_ge_15m": round(float(1.4826 * np.median(np.abs(e[tall] - np.median(e[tall])))), 3) if tall.sum() else None,
                     "slope_m_per_m": round(float(np.polyfit(mids, meds, 1)[0]), 3) if len(mids) >= 3 else None,
                     "datum_offset_removed_m": round(offset, 3)})
        keep = g.drop(columns=["x", "y", "lidar", "chm", "H"])
        keep.to_file(dest / f"ground_points_{v}.gpkg", driver="GPKG")
    pd.DataFrame(bins).to_csv(dest / "ground_points_bins.csv", index=False)
    pd.DataFrame(summ).to_csv(dest / "ground_points_summary.csv", index=False)
    return cfg, pd.DataFrame(bins), pd.DataFrame(summ), dest


def plot(results, theme):
    th = THEMES[theme]
    fig, axes = plt.subplots(1, len(results), figsize=(6.2 * len(results), 4.6), sharey=True, squeeze=False)
    fig.patch.set_facecolor(th["bg"])
    for ax, (cfg, b, s, _) in zip(axes[0], results):
        ax.set_facecolor(th["bg"])
        ax.tick_params(colors=th["fg"], labelsize=8)
        for sp in ax.spines.values():
            sp.set_color(th["grid"])
        ax.grid(color=th["grid"], lw=0.5)
        ax.axhline(0, color=th["fg"], lw=0.6, alpha=0.5)
        for v in LABEL:
            d = b[b.variant == v]
            if len(d):
                n = int(s[s.variant == v].points.iloc[0])
                ax.plot((d.canopy_m_from + d.canopy_m_to) / 2, d.median_m, marker="o", ms=3, lw=1.6 if v == "is2_spatial" else 1.1,
                        color=COLOR[v], ls="--" if v.startswith("gedi") else "-", label=f"{LABEL[v]} ({n:,})")
        ax.set_title(cfg["khg"].replace("KHG ", ""), color=th["fg"], fontsize=10, loc="left")
        ax.set_xlabel("canopy height at the point (m)", color=th["fg"], fontsize=9)
    axes[0, 0].set_ylabel("ground point − LiDAR, median (m)", color=th["fg"], fontsize=9)
    h, lab = axes[0, -1].get_legend_handles_labels()
    fig.legend(h, [x.split(" (")[0] for x in lab], frameon=False, fontsize=8, labelcolor=th["fg"], loc="lower center", ncol=3)
    fig.suptitle("Are the calibration ground points too high under forest?", color=th["fg"], fontsize=11, x=0.01, ha="left")
    fig.text(0.01, 0.925, "Median of satellite ground minus LiDAR per canopy-height bin; one datum offset per site removed (open ground "
             "of ICESat-2 as used now). Flat = the points see the ground under the canopy.", color=th["fg"], fontsize=8, alpha=0.8)
    fig.tight_layout(rect=(0, 0.1, 1, 0.91))
    return fig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("configs", nargs="+")
    ap.add_argument("--theme", nargs="+", default=["light", "dark"])
    ap.add_argument("--plot-only", action="store_true", help="redraw the figure from the CSV files of an earlier run")
    a = ap.parse_args()
    if a.plot_only:
        res = []
        for c in a.configs:
            cfg = yaml.safe_load(open(c, encoding="utf-8"))
            d = out_dir(cfg) / "11_ground_points"
            res.append((cfg, pd.read_csv(d / "ground_points_bins.csv"), pd.read_csv(d / "ground_points_summary.csv"), d))
    else:
        res = [site(c) for c in a.configs]
    for cfg, b, s, _ in res:
        print(s.drop(columns=["site"]).to_string(index=False))
    for t in a.theme:
        fig = plot(res, t)
        for *_, dest in res:
            fig.savefig(dest / f"ground_points_canopy_{t}.png", dpi=160, facecolor=THEMES[t]["bg"])
        plt.close(fig)
    print("wrote", ", ".join(str(r[3]) for r in res))


if __name__ == "__main__":
    main()
