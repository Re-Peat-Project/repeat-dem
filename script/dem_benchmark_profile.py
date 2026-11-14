"""Cross-section profiles of every benchmark candidate against the LiDAR, and of GEM-15 (DSM and DTM) against the LiDAR.

    python script/dem_benchmark_profile.py benchmark/mendahara.yaml [--theme light dark]

Transects (fixed by rule, not picked by eye): two straight lines through the centroid of the LiDAR cells inside the KHG,
west-east and south-north, each cut to the longest unbroken run of LiDAR cells inside the KHG along it. Every source is read
at the nearest cell to points every 25 m (the LiDAR spacing), as the benchmark scores do; heights as delivered or as
processed (01_candidates/*.vrt), no datum conversion (the LiDAR's datum is not recorded; processed candidates sit +0.6 to
+1.0 m above it). GEM-15 DSM is read from Google's public mosaics (gs://climate-and-sustainability/gem-15) and moved from
EGM96 to EGM2008 like the DTM (repeat_common.fetch_open_dem). Land cover: ESA WorldCover 2021 under each point.

Writes 01_dem/benchmark/09_profiles/: profile_<we|sn>_candidates_<theme>.png, profile_<we|sn>_gem15_<theme>.png,
profile_transects_<theme>.png (where the lines are) and profiles.csv (every sampled value).
"""
import argparse
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import rasterio
import yaml
from rasterio.features import geometry_mask

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dem_benchmark import out_dir  # noqa: E402

NAMES = {"deltadtm": "DeltaDTM v1.1", "klhk_modelled": "KLHK modelled DTM", "gedtm30": "GEDTM30 v1.1", "demnas": "DEMNAS",
         "fabdem": "FABDEM v1.2", "glo30": "Copernicus GLO-30 (DSM)", "gem15": "GEM-15 DTM"}
WC = {10: ("tree cover", "#1b7837"), 20: ("shrubland", "#a6d96a"), 30: ("grassland", "#d9ef8b"), 40: ("cropland", "#fdae61"),
      50: ("built-up", "#d73027"), 60: ("bare", "#bababa"), 80: ("water", "#4575b4"), 90: ("herbaceous wetland", "#74add1"),
      95: ("mangroves", "#35978f")}
THEMES = {"light": {"bg": "white", "fg": "#222222", "grid": "#dddddd", "lidar": "#111111", "raw": "#9e9e9e", "proc": "#d6604d",
                    "dsm": "#2166ac", "dtm": "#d6604d"},
          "dark": {"bg": "#16181c", "fg": "#e8e8e8", "grid": "#33363c", "lidar": "#f5f5f5", "raw": "#7a7a7a", "proc": "#f4a582",
                   "dsm": "#92c5de", "dtm": "#f4a582"}}


def sample(path, xs, ys, crs):
    """Nearest-cell values at points given in crs (NaN outside or at nodata)."""
    from pyproj import Transformer
    with rasterio.open(path) as r:
        if r.crs is None or r.crs.to_epsg() != crs.to_epsg():
            xx, yy = Transformer.from_crs(crs, r.crs or "EPSG:4326", always_xy=True).transform(xs, ys)
        else:
            xx, yy = xs, ys
        rows, cols = rasterio.transform.rowcol(r.transform, xx, yy)
        rows, cols = np.asarray(rows), np.asarray(cols)
        ok = (rows >= 0) & (rows < r.height) & (cols >= 0) & (cols < r.width)
        out = np.full(len(xs), np.nan)
        if ok.any():
            r0, r1, c0, c1 = rows[ok].min(), rows[ok].max() + 1, cols[ok].min(), cols[ok].max() + 1
            a = r.read(1, window=((r0, r1), (c0, c1)), masked=True).astype("float64").filled(np.nan)
            out[ok] = a[rows[ok] - r0, cols[ok] - c0]
        if r.nodata is not None and np.isfinite(r.nodata):
            out[out == r.nodata] = np.nan
        out[out < -1e30] = np.nan
    return out


def gem15_dsm(xs, ys, crs):
    """GEM-15 DSM (band 1 of the dsm mosaics) at the points, EGM96 -> EGM2008."""
    import pyproj
    from pyproj import Transformer
    from repeat_common.fetch_open_dem import gem15_mosaics
    lon, lat = Transformer.from_crs(crs, 4326, always_xy=True).transform(xs, ys)
    out = np.full(len(xs), np.nan)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_TIMEOUT="120", GDAL_HTTP_MAX_RETRY="4"):
        for url in gem15_mosaics((min(lon), min(lat), max(lon), max(lat))):
            url = url.replace("/dtm/zall/", "/dsm/zall/")
            todo = np.isnan(out)
            if not todo.any():
                break
            with rasterio.open("/vsicurl/" + url) as r:
                b = rasterio.warp.transform_bounds(r.crs, 4326, *r.bounds)
                inside = todo & (lon >= b[0]) & (lon <= b[2]) & (lat >= b[1]) & (lat <= b[3])
                if not inside.any():
                    continue
            v = sample("/vsicurl/" + url, xs[inside], ys[inside], crs)
            sub = out[inside]
            sub[np.isnan(sub)] = v[np.isnan(sub)]
            out[inside] = sub
    pyproj.network.set_network_enabled(True)
    shift = Transformer.from_crs("EPSG:4326+5773", "EPSG:4326+3855", always_xy=True).transform(lon, lat, np.zeros(len(lon)))[2]
    return out + shift


def transects(cfg, lidar_path, data):
    b, layer, field = cfg["boundary"]
    khg = gpd.read_file(data / b, layer=layer)
    with rasterio.open(lidar_path) as r:
        khg = khg[khg[field] == cfg["khg"]].to_crs(r.crs)
        z = r.read(1, masked=True).astype("float64").filled(np.nan)
        z[z < -1e30] = np.nan
        inside = ~geometry_mask(khg.geometry, out_shape=z.shape, transform=r.transform)
        ok = np.isfinite(z) & inside
        rr, cc = np.nonzero(ok)
        r0, c0 = int(round(rr.mean())), int(round(cc.mean()))
        lines = {}
        for name, line in (("we", ok[r0, :]), ("sn", ok[::-1, c0])):
            # longest unbroken run of valid LiDAR inside the KHG
            best, start = (0, 0), None
            for i, v in enumerate(np.append(line, False)):
                if v and start is None:
                    start = i
                elif not v and start is not None:
                    if i - start > best[1] - best[0]:
                        best = (start, i)
                    start = None
            idx = np.arange(*best)
            if name == "we":
                xs, ys = rasterio.transform.xy(r.transform, np.full(idx.size, r0), idx)
            else:
                xs, ys = rasterio.transform.xy(r.transform, z.shape[0] - 1 - idx, np.full(idx.size, c0))
            lines[name] = (np.asarray(xs), np.asarray(ys))
        return lines, r.crs, khg, z, r.transform


def strip(ax, lc, d, th):
    cols = [WC.get(int(v), ("", th["bg"]))[1] if np.isfinite(v) else th["bg"] for v in lc]
    ax.bar(d, np.ones_like(d), width=(d[1] - d[0]) if len(d) > 1 else 0.025, color=cols, align="edge", linewidth=0)
    ax.set_yticks([])
    ax.set_ylim(0, 1)
    ax.set_ylabel("land\ncover", rotation=0, ha="right", va="center", color=th["fg"], fontsize=8)


def style(fig, axes, th):
    fig.patch.set_facecolor(th["bg"])
    for ax in axes:
        ax.set_facecolor(th["bg"])
        ax.tick_params(colors=th["fg"], labelsize=8)
        for s in ax.spines.values():
            s.set_color(th["grid"])
        ax.grid(axis="y", color=th["grid"], linewidth=0.6)
        ax.set_axisbelow(True)


def legend_wc(fig, present, th):
    from matplotlib.patches import Patch
    h = [Patch(color=WC[c][1], label=WC[c][0]) for c in sorted(present) if c in WC]
    fig.legend(handles=h, loc="lower center", ncol=min(len(h), 9), frameon=False, fontsize=8, labelcolor=th["fg"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--theme", nargs="+", default=["light", "dark"], choices=list(THEMES))
    a = ap.parse_args()
    import os
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    data = Path(os.environ.get("REPEAT_DATA") or HERE.parents[1] / "_data")
    out = out_dir(cfg)
    cand_dir = out / "01_candidates"
    dest = out / "09_profiles"
    dest.mkdir(exist_ok=True)
    lidar_path = data / cfg["lidar"]["path"]
    lines, crs, khg, z, tf = transects(cfg, lidar_path, data)
    rows = []
    prof = {}
    for name, (xs, ys) in lines.items():
        d = np.hypot(xs - xs[0], ys - ys[0]) / 1000
        p = {"d": d, "lidar": sample(lidar_path, xs, ys, crs), "lc": sample(cand_dir / "landcover_worldcover.vrt", xs, ys, crs)}
        for c in cfg["candidates"]:
            for tag in ("", "__processed"):
                f = cand_dir / f"{c}{tag}.vrt"
                if f.exists():
                    p[c + tag] = sample(f, xs, ys, crs)
        if "gem15" in cfg["candidates"]:
            p["gem15_dsm"] = gem15_dsm(xs, ys, crs)
        prof[name] = p
        df = pd.DataFrame({k: v for k, v in p.items()})
        df.insert(0, "y", ys)
        df.insert(0, "x", xs)
        df.insert(0, "transect", name)
        rows.append(df)
        print(f"transect {name}: {d[-1]:.1f} km, {len(d)} points", flush=True)
    pd.concat(rows).round(3).to_csv(dest / "profiles.csv", index=False)
    title_khg = cfg["khg"].replace("KHG ", "")
    label = {"we": "west → east", "sn": "south → north"}
    for th_name in a.theme:
        th = THEMES[th_name]
        for name, p in prof.items():
            d = p["d"]
            cands = [c for c in NAMES if c in cfg["candidates"] and c in p]
            allv = np.concatenate([p["lidar"]] + [p[c] for c in cands] + [p.get(c + "__processed", p["lidar"]) for c in cands])
            lo, hi = np.nanpercentile(allv, 0.5) - 0.5, np.nanpercentile(allv, 99.5) + 0.5
            # 1) every candidate against the LiDAR, one panel each, same height scale
            fig, axes = plt.subplots(len(cands) + 1, 1, figsize=(12, 1.7 * len(cands) + 1.6), sharex=True,
                                     gridspec_kw={"height_ratios": [4] * len(cands) + [0.6]})
            style(fig, axes, th)
            for ax, c in zip(axes, cands):
                ax.plot(d, p["lidar"], color=th["lidar"], lw=1.1, label="LiDAR (KLHK, 25 m)")
                ax.plot(d, p[c], color=th["raw"], lw=0.8, label="as delivered")
                if c + "__processed" in p:
                    ax.plot(d, p[c + "__processed"], color=th["proc"], lw=1.3, label="after repeat-dem processing")
                ax.set_ylim(lo, hi)
                ax.text(0.005, 0.92, NAMES[c], transform=ax.transAxes, va="top", color=th["fg"], fontsize=9, weight="bold")
                ax.set_ylabel("m", color=th["fg"], fontsize=8)
            axes[0].legend(loc="upper right", ncol=3, frameon=False, fontsize=8, labelcolor=th["fg"])
            strip(axes[-1], p["lc"], d, th)
            axes[-1].set_xlabel(f"distance along the transect ({label[name]}), km", color=th["fg"], fontsize=9)
            fig.suptitle(f"{title_khg}: every elevation source against the LiDAR, transect {label[name]}", color=th["fg"],
                         fontsize=11, x=0.01, ha="left")
            fig.text(0.01, 0.955, "Heights as delivered and after processing, nearest cell every 25 m, no datum conversion "
                     "(LiDAR datum not recorded). Same height scale in every panel.", color=th["fg"], fontsize=8, alpha=0.8)
            legend_wc(fig, set(np.unique(p["lc"][np.isfinite(p["lc"])]).astype(int)), th)
            fig.tight_layout(rect=(0, 0.03, 1, 0.95))
            fig.savefig(dest / f"profile_{name}_candidates_{th_name}.png", dpi=160, facecolor=th["bg"])
            plt.close(fig)
            # 2) GEM-15 DSM and DTM against the LiDAR
            if "gem15_dsm" in p:
                fig, axes = plt.subplots(2, 1, figsize=(12, 5.2), sharex=True, gridspec_kw={"height_ratios": [6, 0.6]})
                style(fig, axes, th)
                ax = axes[0]
                ax.fill_between(d, p["lidar"], p["gem15_dsm"], where=p["gem15_dsm"] > p["lidar"], color=th["dsm"], alpha=0.12, lw=0)
                ax.plot(d, p["gem15_dsm"], color=th["dsm"], lw=0.9, label="GEM-15 DSM (surface)")
                ax.plot(d, p["gem15"], color=th["dtm"], lw=1.1, label="GEM-15 DTM (bare earth, as delivered)")
                ax.plot(d, p["lidar"], color=th["lidar"], lw=1.3, label="LiDAR (KLHK, 25 m)")
                ax.set_ylabel("height (m)", color=th["fg"], fontsize=9)
                ax.legend(loc="upper right", ncol=3, frameon=False, fontsize=8, labelcolor=th["fg"])
                ok = np.isfinite(p["gem15"]) & np.isfinite(p["lidar"])
                tree = ok & (p["lc"] == 10)
                open_ = ok & np.isin(p["lc"], [20, 30, 40, 60, 90])
                msg = (f"DTM − LiDAR, median along this line: under tree cover {np.nanmedian((p['gem15'] - p['lidar'])[tree]):+.1f} m "
                       f"({tree.sum()} points), on open ground {np.nanmedian((p['gem15'] - p['lidar'])[open_]):+.1f} m ({open_.sum()} points)")
                ax.text(0.005, 0.04, msg, transform=ax.transAxes, color=th["fg"], fontsize=8)
                strip(axes[1], p["lc"], d, th)
                axes[1].set_xlabel(f"distance along the transect ({label[name]}), km", color=th["fg"], fontsize=9)
                fig.suptitle(f"{title_khg}: GEM-15 surface and terrain against the LiDAR, transect {label[name]}",
                             color=th["fg"], fontsize=11, x=0.01, ha="left")
                fig.text(0.01, 0.925, "GEM-15 v1 (Google, 15 m, 2022–2024 optical stereo), EGM96 moved to EGM2008; nearest cell "
                         "every 25 m; LiDAR datum not recorded.", color=th["fg"], fontsize=8, alpha=0.8)
                legend_wc(fig, set(np.unique(p["lc"][np.isfinite(p["lc"])]).astype(int)), th)
                fig.tight_layout(rect=(0, 0.05, 1, 0.92))
                fig.savefig(dest / f"profile_{name}_gem15_{th_name}.png", dpi=160, facecolor=th["bg"])
                plt.close(fig)
        # 3) where the transects are
        fig, ax = plt.subplots(figsize=(7, 6.5))
        style(fig, [ax], th)
        ext = (tf.c, tf.c + tf.a * z.shape[1], tf.f + tf.e * z.shape[0], tf.f)
        im = ax.imshow(z, extent=ext, cmap="terrain", vmin=np.nanpercentile(z, 1), vmax=np.nanpercentile(z, 99))
        khg.boundary.plot(ax=ax, color=th["fg"], lw=0.8)
        for name, (xs, ys) in lines.items():
            ax.plot(xs, ys, color="#d6604d", lw=2)
            ax.annotate(label[name], (xs[len(xs) // 2], ys[len(ys) // 2]), xytext=(4, 4), textcoords="offset points",
                        color=th["fg"], fontsize=8, bbox={"boxstyle": "round,pad=0.2", "fc": th["bg"], "ec": "none", "alpha": 0.8})
        b = khg.total_bounds
        ax.set_xlim(b[0] - 2000, b[2] + 2000)
        ax.set_ylim(b[1] - 2000, b[3] + 2000)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xlabel("")
        ax.set_ylabel("")
        cb = fig.colorbar(im, ax=ax, shrink=0.7)
        cb.set_label("LiDAR height (m)", color=th["fg"])
        cb.ax.tick_params(colors=th["fg"])
        ax.set_title(f"{title_khg}: transects over the LiDAR", color=th["fg"], fontsize=10, loc="left")
        fig.tight_layout()
        fig.savefig(dest / f"profile_transects_{th_name}.png", dpi=150, facecolor=th["bg"])
        plt.close(fig)
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
