"""Canal mask and smoothing scale for DeltaDTM, scored against the LiDAR. Config and decision rules:
benchmark/canal_mask_sweep.yaml (written before any result).

    python script/canal_mask_sweep.py benchmark/canal_mask_sweep.yaml [--sites mendahara] [--report]

Per site (a benchmark config):
  1. surfaces: the step 04 DeltaDTM (dtm_corrected.tif: ICESat-2 class offsets applied, 30 m, not smoothed) with the
     step 04 land-cover mask, plus each canal/river mask variant (demnas_dtm.vector_mask, so a variant carries over to
     the pipeline config unchanged), then despike, smoothing (demnas_dtm.smooth, median then gaussian) at every scale,
     gap filling and the KHG mask; written to <benchmark>/06_canal_mask_sweep/<mask>_m<median>_g<gauss>.tif;
  2. scoring on the LiDAR grid inside the KHG: error of height differences over each baseline (all cells and land cells
     away from mapped canals and rivers), correlation of candidate and LiDAR height differences, and the median error by
     distance band from the nearest mapped canal. The LiDAR is never used in 1.
Results: <benchmark>/06_canal_mask_sweep/results.csv per site; runs/checks/canal_mask_sweep.csv and .md for both, with
the decisions of the config evaluated mechanically.
"""
import argparse
import copy
import os
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import yaml
from rasterio.features import geometry_mask, rasterize
from rasterio.windows import Window, from_bounds
from scipy import ndimage

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WS = REPO.parent
for p in (REPO, HERE, WS / "repeat-common" / "src"):
    sys.path.insert(0, str(p))
import demnas_dtm as dd  # noqa: E402
from dem_benchmark import out_dir, sample  # noqa: E402
from repeat_common import khg  # noqa: E402


def pair_diffs(a, b, k):
    """Height differences a(x+k)-a(x) and b(x+k)-b(x) along rows and columns, where all four values are finite."""
    da, db = [], []
    for sa, sb in (((slice(None), slice(k, None)), (slice(None), slice(None, -k))),
                   ((slice(k, None), slice(None)), (slice(None, -k), slice(None)))):
        x, y = a[sa] - a[sb], b[sa] - b[sb]
        ok = np.isfinite(x) & np.isfinite(y)
        da.append(x[ok])
        db.append(y[ok])
    return np.concatenate(da), np.concatenate(db)


def mask_layers(spec, kdir, cfg, out):
    """mask.vectors entries for demnas_dtm.vector_mask; class subsets are written once as small gpkg files in out."""
    items = []
    for it in spec:
        src = kdir / cfg[it["layer"]]
        path = src
        if it.get("classes"):
            cls = [str(c) for c in it["classes"]]
            path = out / f"_{it['layer']}_{'-'.join(cls)}.gpkg"
            if not path.exists():
                g = gpd.read_file(src)
                g[g["KODE_KANAL"].astype(str).isin(cls)].to_file(path, driver="GPKG")
        items.append({"path": str(path), "buffer_m": float(it["buffer_m"])})
    return items


def surfaces(cfg, bench, kdir, out):
    """Step 1: every mask x smoothing surface for one site; returns {(mask, w, s): path} and masked share per mask."""
    src = bench / cfg["input"]
    run_cfg = yaml.safe_load(open(src.parent / "config.yaml", encoding="utf-8"))
    aoi = gpd.read_file(bench / "00_inputs" / "aoi_khg.gpkg")
    paths, share = {}, {}
    with rasterio.open(src) as d, rasterio.open(src.parent / "landcover.tif") as L:
        grid = dd.Grid(d.crs, d.transform, d.width, d.height)
        z0 = d.read(1).astype("float32")
        lc = L.read(1)
        prof = d.profile | {"compress": "deflate", "tiled": True, "blockxsize": 512, "blockysize": 512,
                            "dtype": "float32", "nodata": np.nan}
    inside = geometry_mask([aoi.to_crs(grid.crs).union_all()], z0.shape, grid.transform, invert=True)
    z0[np.isin(lc, [int(v) for v in run_cfg["mask"]["landcover_classes"]])] = np.nan
    for mname, spec in cfg["masks"].items():
        c = copy.deepcopy(run_cfg)
        c["mask"]["vectors"] = mask_layers(spec, kdir, cfg, out)
        want = {(mname, w, s): out / f"{mname}_m{w}_g{s}.tif" for w, s in cfg["smoothing"]}
        paths.update(want)
        vm = dd.vector_mask(c, grid)
        share[mname] = float(vm[inside & np.isfinite(z0)].mean()) if vm is not None else 0.0
        if all(p.exists() for p in want.values()):
            continue
        b = z0.copy()
        if vm is not None:
            b[vm] = np.nan
        if c["mask"]["despike"]:
            ref = dd.coarse_median(b, grid, float(c["mask"]["despike_window_m"]))
            b[np.isfinite(b) & (np.abs(b - ref) > float(c["mask"]["despike_threshold_m"]))] = np.nan
        for (_, w, s), p in want.items():
            c["smoothing"]["steps"] = [{"method": "median", "window_m": w}, {"method": "gaussian", "sigma_m": s}]
            sm = dd.fill_gaps(dd.smooth(b, grid, c), int(c["smoothing"]["fill_max_search_px"]))
            sm[~inside] = np.nan
            with rasterio.open(p, "w", **prof) as o:
                o.write(sm, 1)
        print(f"   surfaces {mname}: masked {100 * share[mname]:.1f}% of valid cells", flush=True)
    return paths, share


def lidar(bc, data, kdir, cfg):
    """LiDAR heights inside the KHG, cell centres, and distance to the nearest mapped canal and to any canal or river."""
    b = gpd.read_file(data / bc["boundary"][0], layer=bc["boundary"][1])
    with rasterio.open(data / bc["lidar"]["path"]) as L:
        geom = b[b[bc["boundary"][2]] == bc["khg"]].to_crs(L.crs).union_all()
        w = from_bounds(*geom.bounds, L.transform).round_offsets().round_lengths().intersection(Window(0, 0, L.width, L.height))
        z = L.read(1, window=w).astype("float32")
        z[~np.isfinite(z) | (z < -100) | (z > 1e4) | ((z == L.nodata) if L.nodata is not None else False)] = np.nan
        tf, res, crs = L.window_transform(w), abs(L.res[0]), L.crs
    z[~geometry_mask([geom], z.shape, tf, invert=True)] = np.nan
    can = gpd.read_file(kdir / cfg["canals"]).to_crs(crs)
    riv = gpd.read_file(kdir / cfg["rivers"]).to_crs(crs)
    def dist(geoms):
        r = rasterize([(g, 1) for g in geoms if g is not None and not g.is_empty], out_shape=z.shape, transform=tf,
                      fill=0, all_touched=True, dtype="uint8")
        return (ndimage.distance_transform_edt(r == 0) * res).astype("float32")
    d_can = dist(can.geometry)
    d_any = np.minimum(d_can, dist(riv.geometry))
    return z, tf, res, crs, d_can, d_any


def score(S, z, res, cfg, d_can, d_any, flat=False):
    e = S - z
    land = d_any > float(cfg["land_min_dist_m"])
    row = {}
    for bm in cfg["baselines_m"]:
        k = int(round(bm / res))
        da, dl = pair_diffs(S, z, k)
        row[f"rms_{bm}m"] = round(float(np.sqrt(np.mean((da - dl) ** 2))), 4)
        row[f"corr_{bm}m"] = 0.0 if flat else round(float(np.corrcoef(da, dl)[0, 1]), 4)
        Sl, zl = np.where(land, S, np.nan), np.where(land, z, np.nan)
        da, dl = pair_diffs(Sl, zl, k)
        row[f"land_rms_{bm}m"] = round(float(np.sqrt(np.mean((da - dl) ** 2))), 4)
        if not flat:
            row[f"land_corr_{bm}m"] = round(float(np.corrcoef(da, dl)[0, 1]), 4)
    ok = np.isfinite(e)
    med = float(np.median(e[ok]))
    row["median_minus_lidar_m"] = round(med, 3)
    row["nmad_m"] = round(float(1.4826 * np.median(np.abs(e[ok] - med))), 3)
    bands = cfg["distance_bands_m"] + [np.inf]
    for lo, hi in zip(bands[:-1], bands[1:]):
        sel = ok & (d_can >= lo) & (d_can < hi)
        row[f"canal_bias_{lo}_{'inf' if np.isinf(hi) else int(hi)}m"] = round(float(np.median(e[sel]) - med), 3) if sel.any() else None
    return row


def decide(d):
    """Evaluate the two decisions of the config on the combined results; returns lines of text."""
    sites = list(d.site.unique())
    s = d[d["mask"] != "flat"]
    at = s[s.smoothing == "300/150"].set_index(["site", "mask"])
    L = ["## Decision 1: canal mask (at 300/150)", ""]
    passing = []
    for m in [m for m in s["mask"].unique() if m != "none"]:
        ok_err = all(at.loc[(st, m), "land_rms_1000m"] < at.loc[(st, "none"), "land_rms_1000m"] for st in sites)
        ok_bias = all(abs(at.loc[(st, m), "canal_bias_0_50m"]) < abs(at.loc[(st, "none"), "canal_bias_0_50m"]) for st in sites)
        L.append(f"- `{m}`: land 1 km error lower at both sites: {'yes' if ok_err else 'no'}; 0-50 m bias closer to 0 at both: "
                 f"{'yes' if ok_bias else 'no'}")
        if ok_err and ok_bias:
            passing.append((float(np.mean([at.loc[(st, m), "land_rms_1000m"] for st in sites])), m))
    best = min(passing)[1] if passing else "none"
    L += ["", f"**Result: {'adopt `' + best + '`' if passing else 'no mask passes; the template stays without a mask'}.**", ""]
    L += ["## Decision 2: smoothing scale (with the decision-1 mask)", ""]
    m = s[s["mask"] == best].set_index(["site", "smoothing"])
    change = []
    for sc in [x for x in s.smoothing.unique() if x != "300/150"]:
        ok_err = all(m.loc[(st, sc), "land_rms_1000m"] < m.loc[(st, "300/150"), "land_rms_1000m"] for st in sites)
        ok_cor = all(m.loc[(st, sc), "land_corr_2000m"] >= m.loc[(st, "300/150"), "land_corr_2000m"] for st in sites)
        L.append(f"- {sc}: land 1 km error lower at both sites: {'yes' if ok_err else 'no'}; 2 km correlation not lower at both: "
                 f"{'yes' if ok_cor else 'no'}")
        if ok_err and ok_cor:
            change.append(sc)
    L += ["", f"**Result: {'candidates to replace 300/150 (check on the delineation before adopting): ' + ', '.join(change) if change else '300/150 stays'}.**", ""]
    return L


def report(csv_path, dest):
    d = pd.read_csv(csv_path)
    L = ["# Canal mask and smoothing sweep for DeltaDTM: results", "",
         f"Generated by `script/canal_mask_sweep.py --report` from `{csv_path.name}`; do not edit. Config and decision rules: "
         "`benchmark/canal_mask_sweep.yaml`.", "",
         "Land cells: LiDAR cells more than 100 m from any mapped canal or river. Errors in m, lower is better; correlations of "
         "candidate and LiDAR height differences, higher is better.", ""]
    order = [f"{w}/{g}" for w, g in [[150, 75], [300, 150], [450, 225], [600, 300], [1200, 600]]]
    for site in d.site.unique():
        x = d[(d.site == site) & (d["mask"] != "flat")]
        f = d[(d.site == site) & (d["mask"] == "flat")].iloc[0]
        for col, title in (("land_rms_1000m", f"land cells, 1 km height-difference error (flat surface: {f.land_rms_1000m:.3f})"),
                           ("rms_1000m", f"all cells, 1 km height-difference error (flat surface: {f.rms_1000m:.3f})"),
                           ("land_corr_2000m", "land cells, 2 km height-difference correlation (flat surface: 0)")):
            t = x.pivot_table(index="mask", columns="smoothing", values=col, aggfunc="first")
            t = t[[c for c in order if c in t.columns]]
            L += [f"## {site}: {title}", "", "| mask | masked % | " + " | ".join(t.columns) + " |", "|---|---|" + "---|" * len(t.columns)]
            sh = x.drop_duplicates("mask").set_index("mask").masked_pct
            L += [f"| {mk} | {sh[mk]:.1f} | " + " | ".join(f"{v:.3f}" for v in r.values) + " |" for mk, r in t.iterrows()]
            L.append("")
        bc = [c for c in d.columns if c.startswith("canal_bias_")]
        y = x[x.smoothing == "300/150"].set_index("mask")[bc]
        L += [f"## {site}: median error by distance from the nearest mapped canal, minus the overall median (m), at 300/150", "",
              "| mask | " + " | ".join(c.replace("canal_bias_", "").replace("_", "-") for c in bc) + " |", "|---|" + "---|" * len(bc)]
        L += [f"| {mk} | " + " | ".join("" if pd.isna(v) else f"{v:+.3f}" for v in r.values) + " |" for mk, r in y.iterrows()]
        L.append("")
    if d.site.nunique() >= 2:
        L += decide(d)
    Path(dest).write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote", dest)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--sites", nargs="*")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    dest = REPO / "runs" / "checks" / "canal_mask_sweep.csv"
    if a.report:
        return report(dest, dest.with_suffix(".md"))
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    data = Path(os.environ.get("REPEAT_DATA") or WS / "_data")
    allrows = []
    for sc in cfg["sites"]:
        bc = yaml.safe_load(open(REPO / sc, encoding="utf-8"))
        site = bc["site"]
        if a.sites and site not in a.sites:
            continue
        t0 = time.time()
        print(f"## {site}", flush=True)
        bench = out_dir(bc)
        kdir = khg.folder(bc["khg"])
        out = bench / cfg["out"]
        out.mkdir(parents=True, exist_ok=True)
        paths, share = surfaces(cfg, bench, kdir, out)
        z, tf, res, crs, d_can, d_any = lidar(bc, data, kdir, cfg)
        rr, cc = np.nonzero(np.isfinite(z))
        lx, ly = tf * (cc + 0.5, rr + 0.5)
        print(f"   LiDAR cells {rr.size}; land cells {int((np.isfinite(z) & (d_any > cfg['land_min_dist_m'])).sum())}", flush=True)
        flat = np.where(np.isfinite(z), np.float32(np.nanmedian(z)), np.nan).astype("float32")
        rows = [{"site": site, "mask": "flat", "smoothing": "", "masked_pct": 0.0} | score(flat, z, res, cfg, d_can, d_any, flat=True)]
        for (mname, w, s), p in paths.items():
            S = np.full(z.shape, np.nan, dtype="float32")
            S[rr, cc] = sample(str(p), lx, ly, crs)
            rows.append({"site": site, "mask": mname, "smoothing": f"{w}/{s}", "masked_pct": round(100 * share[mname], 2)}
                        | score(S, z, res, cfg, d_can, d_any))
            r = rows[-1]
            print(f"   {mname} {w}/{s}: land 1 km {r['land_rms_1000m']} (flat {rows[0]['land_rms_1000m']}), "
                  f"2 km corr {r['land_corr_2000m']}, 0-50 m bias {r['canal_bias_0_50m']}", flush=True)
        pd.DataFrame(rows).to_csv(out / "results.csv", index=False)
        allrows += rows
        print(f"   {site} done in {time.time() - t0:.0f} s", flush=True)
    new = pd.DataFrame(allrows)
    if dest.exists() and a.sites:
        old = pd.read_csv(dest)
        new = pd.concat([old[~old.site.isin(new.site.unique())], new])
    new.to_csv(dest, index=False)
    print("wrote", dest)
    report(dest, dest.with_suffix(".md"))


if __name__ == "__main__":
    main()
