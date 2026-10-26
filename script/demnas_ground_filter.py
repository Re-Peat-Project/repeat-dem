"""One-shot test of a DeltaDTM-style step for DEMNAS: ground filter, smoothing scales, ICESat-2/GEDI trend. Config and
decision rule: benchmark/demnas_ground_filter.yaml (written before any result).

    python script/demnas_ground_filter.py benchmark/demnas_ground_filter.yaml [--strip-rows 1500]

Per site (a benchmark config) and input surface (step 04 dtm_corrected.tif, ICESat-2 class offsets applied, not smoothed):
  1. per strip, on the input's own grid (nothing coarsened; strips overlap by the widest neighbourhood): land-cover mask
     as step 04, optional progressive morphological filter (non-ground cells removed), despike as step 04, then the
     repeat-dem smoothing (demnas_dtm.smooth, median then gaussian) at every scale in the config, gap filling, KHG mask.
     Written to <benchmark>/05_demnas_ground_filter/<input>_<filter>_m<median>_g<gauss>.tif (+ pmf_nonground.tif);
  2. trend: residuals (ground point - surface) at the calibration points (ICESat-2 calibration blocks of step 04, GEDI
     outside the ICESat-2 validation blocks), gaussian kernel average on a coarse correction grid, shrunk to 0 where
     points are sparse; written as <surface>_trend.tif. The corrected surface is surface + trend (bilinear);
  3. scoring against the LiDAR exactly as step 03 (1 km height-difference error, every cell pair) and at the held-out
     ICESat-2 validation points. The LiDAR is never used in 1 or 2.
Results: <benchmark>/05_demnas_ground_filter/results.csv per site, and runs/checks/demnas_ground_filter.csv for both.
"""
import argparse
import copy
import math
import os
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import yaml
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds
from scipy import ndimage

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WS = REPO.parent
for p in (REPO, HERE, WS / "repeat-common" / "src"):
    sys.path.insert(0, str(p))
import demnas_dtm as dd  # noqa: E402
import ground_truth as gt  # noqa: E402
from dem_benchmark import out_dir, sample, shift_diffs  # noqa: E402
from repeat_common import khg  # noqa: E402

BIG = np.float32(1e9)


def pmf_nonground(z, res, p):
    """Progressive morphological filter (square windows). True = non-ground. NaN cells are ignored."""
    valid = np.isfinite(z)
    surf = np.where(valid, z, BIG).astype("float32")
    flag = np.zeros(z.shape, bool)
    prev = 0
    for wm in p["windows_m"]:
        w = max(3, int(round(wm / res)) | 1)
        if w <= prev:
            continue
        ero = ndimage.minimum_filter1d(ndimage.minimum_filter1d(surf, w, axis=0), w, axis=1)
        ero[ero >= BIG] = -BIG                      # windows with no data: ignored by the dilation
        op = ndimage.maximum_filter1d(ndimage.maximum_filter1d(ero, w, axis=0), w, axis=1)
        dh = min(p["dh0_m"] + p["slope"] * (w - prev) * res, p["dh_max_m"])
        flag |= valid & ((surf - op) > dh)
        surf = np.where(valid, op, BIG)
        prev = w
    return flag


def block_keys(x, y, bs):
    return np.floor(x / bs).astype(np.int64) * 1_000_003 + np.floor(y / bs).astype(np.int64)


def surfaces(site, name, src, cfg, run_cfg, aoi, strip_rows, out):
    """Step 1 for one input: returns {variant: path}."""
    sm_list = cfg["smoothing"]
    variants = ["base", "pmf"] if name == "demnas" else ["base"]
    paths = {(v, w, s): out / f"{name}_{v}_m{w}_g{s}.tif" for v in variants for w, s in sm_list}
    if all(p.exists() for p in paths.values()):
        return {k: p for k, p in paths.items()}
    with rasterio.open(src) as d, rasterio.open(src.parent / "landcover.tif") as L:
        grid = dd.Grid(d.crs, d.transform, d.width, d.height)
        res = grid.res
        support = max([w * 1.5 + s * 4 for w, s in sm_list] + [run_cfg["mask"]["despike_window_m"] * 1.5]) * 2 \
            + run_cfg["smoothing"]["fill_max_search_px"] * res
        pad = int(math.ceil(max(2000.0, support, 2 * max(cfg["pmf"]["windows_m"])) / res))
        prof = d.profile | {"compress": "deflate", "tiled": True, "blockxsize": 512, "blockysize": 512, "BIGTIFF": "IF_SAFER",
                            "dtype": "float32", "nodata": np.nan}
        outs = {k: rasterio.open(p, "w", **prof) for k, p in paths.items()}
        ng_out = rasterio.open(out / f"{name}_pmf_nonground.tif", "w", **(prof | {"dtype": "uint8", "nodata": 255})) if "pmf" in variants else None
        geom = gpd.read_file(aoi).to_crs(d.crs).union_all()
        n_ng = n_valid = 0
        for c0 in range(0, d.height, strip_rows):
            c1 = min(d.height, c0 + strip_rows)
            p0, p1 = max(0, c0 - pad), min(d.height, c1 + pad)
            win = Window(0, p0, d.width, p1 - p0)
            sg = dd.Grid(d.crs, d.window_transform(win), d.width, p1 - p0)
            z = d.read(1, window=win).astype("float32")
            lc = L.read(1, window=win)
            z[np.isin(lc, [int(v) for v in run_cfg["mask"]["landcover_classes"]])] = np.nan
            inside = geometry_mask([geom], z.shape, sg.transform, invert=True)
            ins = {"base": z}
            if "pmf" in variants:
                ng = pmf_nonground(z, res, cfg["pmf"])
                zp = z.copy()
                zp[ng] = np.nan
                ins["pmf"] = zp
                r0, r1 = c0 - p0, c1 - p0
                ng_out.write(np.where(np.isfinite(z[r0:r1]), ng[r0:r1], 255).astype("uint8"), 1, window=Window(0, c0, d.width, c1 - c0))
                core = np.isfinite(z[r0:r1]) & inside[r0:r1]
                n_ng += int(ng[r0:r1][core].sum())
                n_valid += int(core.sum())
                del ng
            for v, base in ins.items():
                b = base.copy()
                if run_cfg["mask"]["despike"]:
                    ref = dd.coarse_median(b, sg, float(run_cfg["mask"]["despike_window_m"]))
                    b[np.isfinite(b) & (np.abs(b - ref) > float(run_cfg["mask"]["despike_threshold_m"]))] = np.nan
                    del ref
                for w, s in sm_list:
                    c = copy.deepcopy(run_cfg)
                    c["smoothing"]["steps"] = [{"method": "median", "window_m": w}, {"method": "gaussian", "sigma_m": s}]
                    sm = dd.fill_gaps(dd.smooth(b, sg, c), int(run_cfg["smoothing"]["fill_max_search_px"]))
                    sm[~inside] = np.nan
                    outs[(v, w, s)].write(sm[c0 - p0:c1 - p0], 1, window=Window(0, c0, d.width, c1 - c0))
                    del sm
            print(f"   {site} {name}: rows {c0}-{c1} of {d.height}", flush=True)
        for o in outs.values():
            o.close()
        if ng_out:
            ng_out.close()
            print(f"   {site} demnas: ground filter removed {100 * n_ng / max(n_valid, 1):.1f}% of the cells inside the KHG", flush=True)
    return paths


def trend(path, cal, tcfg):
    """Kernel-averaged residual field on a coarse grid; returns (field, transform) and writes <surface>_trend.tif."""
    with rasterio.open(path) as d:
        crs, t, W, H = d.crs, d.transform, d.width, d.height
    S = sample(path, cal.x.to_numpy(), cal.y.to_numpy(), crs)
    r = np.clip(cal.H.to_numpy() - S, -tcfg["clip_m"], tcfg["clip_m"])
    ok = np.isfinite(r)
    cell = float(tcfg["cell_m"])
    nx, ny = math.ceil(W * t.a / cell), math.ceil(H * -t.e / cell)
    ix = np.clip(((cal.x.to_numpy()[ok] - t.c) / cell).astype(int), 0, nx - 1)
    iy = np.clip(((t.f - cal.y.to_numpy()[ok]) / cell).astype(int), 0, ny - 1)
    s_sum, s_n = np.zeros((ny, nx)), np.zeros((ny, nx))
    np.add.at(s_sum, (iy, ix), r[ok])
    np.add.at(s_n, (iy, ix), 1.0)
    sig = tcfg["sigma_m"] / cell
    norm = 2 * math.pi * sig * sig                 # kernel weight 1 at distance 0
    g_sum = ndimage.gaussian_filter(s_sum, sig, mode="constant") * norm
    g_n = ndimage.gaussian_filter(s_n, sig, mode="constant") * norm
    field = (g_sum / (g_n + tcfg["prior_weight"])).astype("float32")
    ft = rasterio.Affine(cell, 0, t.c, 0, -cell, t.f)
    with rasterio.open(path.with_name(path.stem + "_trend.tif"), "w", driver="GTiff", width=nx, height=ny, count=1, dtype="float32",
                       crs=crs, transform=ft) as o:
        o.write(field, 1)
        o.update_tags(meaning="ground point minus surface, kernel average (m); add to the surface", n_points=str(int(ok.sum())))
    return field, ft


def at(field, ft, x, y):
    col = (x - ft.c) / ft.a - 0.5
    row = (y - ft.f) / ft.e - 0.5
    return ndimage.map_coordinates(field, [row, col], order=1, mode="nearest")


def report(csv_path, dest):
    """Tables of the 1 km height-difference error (m) per site, variant and smoothing, and the ground points vs the LiDAR."""
    d = pd.read_csv(csv_path)
    s = d[d.smoothing.notna() & (d.smoothing.astype(str) != "")]
    flat = d[d.surface == "flat"].set_index("site").rms_1km_m
    L = ["# DEMNAS ground filter test: results", "", f"Generated by `script/demnas_ground_filter.py --report` from `{csv_path.name}`; do not edit.",
         "1 km height-difference error against the LiDAR (m); lower is better, and a flat surface scores the LiDAR's own 1 km signal.", ""]
    for site in d.site.unique():
        x = s[s.site == site]
        t = x.pivot_table(index=["surface", "trend"], columns="smoothing", values="rms_1km_m", aggfunc="first")
        t = t[[c for c in [f"{w}/{g}" for w, g in [[150, 75], [300, 150], [600, 300], [1200, 600]]] if c in t.columns]]
        L += [f"## {site} (flat surface: {flat[site]} m)", "", "| surface | trend | " + " | ".join(t.columns) + " |",
              "|---|---|" + "---|" * len(t.columns)]
        L += [f"| {sf} | {'yes' if tr else 'no'} | " + " | ".join(f"{v:.3f}" for v in r.values) + " |" for (sf, tr), r in t.iterrows()]
        L.append("")
    L += ["## Ground points against the LiDAR", "", "| site | points | n | median, point minus LiDAR (m) | NMAD (m) |", "|---|---|---|---|---|"]
    for _, r in d[d.surface.astype(str).str.endswith("_points")].iterrows():
        L.append(f"| {r.site} | {r.surface.replace('_points', '')} | {int(r.n_points)} | {r.median_minus_lidar_m} | {r.nmad_vs_lidar_m} |")
    Path(dest).write_text(chr(10).join(L) + chr(10), encoding="utf-8")
    print("wrote", dest)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--strip-rows", type=int, default=1500)
    ap.add_argument("--sites", nargs="*", help="only these sites (benchmark site names)")
    ap.add_argument("--inputs", nargs="*", help="only these inputs (keys of inputs in the config)")
    ap.add_argument("--report", action="store_true", help="only write runs/checks/demnas_ground_filter.md from the csv")
    a = ap.parse_args()
    if a.report:
        return report(REPO / "runs" / "checks" / "demnas_ground_filter.csv", REPO / "runs" / "checks" / "demnas_ground_filter.md")
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    data = Path(os.environ.get("REPEAT_DATA") or WS / "_data")
    allrows = []
    for sc in cfg["sites"]:
        bc = yaml.safe_load(open(REPO / sc, encoding="utf-8"))
        bench = out_dir(bc)
        out = bench / cfg["out"]
        out.mkdir(parents=True, exist_ok=True)
        site = bc["site"]
        if a.sites and site not in a.sites:
            continue
        print(f"## {site}", flush=True)
        t0 = time.time()
        run_cfg = yaml.safe_load(open(bench / "04_processed" / "demnas" / "config.yaml", encoding="utf-8"))
        aoi = bench / "00_inputs" / "aoi_khg.gpkg"

        # ground points: ICESat-2 as split in step 04; GEDI by the same validation blocks
        ip = gpd.read_file(bench / "04_processed" / "demnas" / "ground_points.gpkg")
        ip = ip[ip["split"].isin(["calibration", "validation"])]
        bs = float(run_cfg["ground"]["split"]["block_size_m"])
        val_blocks = set(block_keys(ip.x[ip.split == "validation"].to_numpy(), ip.y[ip.split == "validation"].to_numpy(), bs).tolist())
        gd = gpd.read_file(data / cfg["gedi"].format(slug="_".join(w.capitalize() for w in khg.slug(bc["khg"]).split("_"))))
        gd = gt.to_dem_datum(gd, run_cfg["ground"], None).to_crs(ip.crs)
        gd["x"], gd["y"] = gd.geometry.x, gd.geometry.y
        with rasterio.open(bench / "04_processed" / "demnas" / "landcover.tif") as L:
            glc = np.array([v[0] for v in L.sample(zip(gd.x, gd.y))])
        gd = gd[~np.isin(glc, [int(v) for v in run_cfg["mask"]["landcover_classes"]])]
        gd["split"] = np.where(np.isin(block_keys(gd.x.to_numpy(), gd.y.to_numpy(), bs), list(val_blocks)), "validation", "calibration")
        cal = pd.concat([ip[ip.split == "calibration"][["x", "y", "H"]], gd[gd.split == "calibration"][["x", "y", "H"]]])
        val_i = ip[ip.split == "validation"]
        print(f"   calibration points: {int((ip.split == 'calibration').sum())} ICESat-2 + {int((gd.split == 'calibration').sum())} GEDI; "
              f"validation {len(val_i)} ICESat-2", flush=True)

        # LiDAR inside the KHG (as step 03)
        b = gpd.read_file(data / bc["boundary"][0], layer=bc["boundary"][1])
        with rasterio.open(data / bc["lidar"]["path"]) as L:
            geom = b[b[bc["boundary"][2]] == bc["khg"]].to_crs(L.crs).union_all()
            w = from_bounds(*geom.bounds, L.transform).round_offsets().round_lengths().intersection(Window(0, 0, L.width, L.height))
            z = L.read(1, window=w).astype("float64")
            z[~np.isfinite(z) | (z < -100) | (z > 1e4) | ((z == L.nodata) if L.nodata is not None else False)] = np.nan
            tf, lres, lcrs = L.window_transform(w), abs(L.res[0]), L.crs
            z[~geometry_mask([geom], z.shape, tf, invert=True)] = np.nan
        rr, cc = np.nonzero(np.isfinite(z))
        lx, ly = tf * (cc + 0.5, rr + 0.5)
        k1 = int(round(1000 / lres))
        signal = float(np.sqrt(np.mean(shift_diffs(z, k1) ** 2)))
        rows = [{"site": site, "surface": "flat", "smoothing": "", "trend": False, "rms_1km_m": round(signal, 3)}]
        # diagnostics: the ground points themselves against the LiDAR (not used anywhere else)
        for nm, pts in (("icesat2_points", ip), ("gedi_points", gd)):
            e = sample(str(data / bc["lidar"]["path"]), pts.x.to_numpy(), pts.y.to_numpy(), pts.crs)
            e = pts.H.to_numpy() - e
            e = e[np.isfinite(e)]
            rows.append({"site": site, "surface": nm, "n_points": int(e.size), "median_minus_lidar_m": round(float(np.median(e)), 3),
                         "nmad_vs_lidar_m": round(float(1.4826 * np.median(np.abs(e - np.median(e)))), 3)})

        for name, rel in cfg["inputs"].items():
            if a.inputs and name not in a.inputs:
                continue
            paths = surfaces(site, name, bench / rel, cfg, run_cfg, aoi, a.strip_rows, out)
            for (v, wm, sg_), p in paths.items():
                S = np.full(z.shape, np.nan)
                S[rr, cc] = sample(p, lx, ly, lcrs)
                field, ft = trend(p, cal, cfg["trend"])
                Sv = sample(p, val_i.x.to_numpy(), val_i.y.to_numpy(), val_i.crs)
                for tr in (False, True):
                    Z = S.copy()
                    sv = Sv.copy()
                    if tr:
                        Z[rr, cc] += at(field, ft, lx, ly)
                        sv = sv + at(field, ft, val_i.x.to_numpy(), val_i.y.to_numpy())
                    e = Z - z
                    d = shift_diffs(e, k1)
                    ev = sv - val_i.H.to_numpy()
                    ev = ev[np.isfinite(ev)]
                    ee = e[np.isfinite(e)]
                    rows.append({"site": site, "surface": f"{name}_{v}", "smoothing": f"{wm}/{sg_}", "trend": tr,
                                 "rms_1km_m": round(float(np.sqrt(np.mean(d * d))), 3),
                                 "nmad_vs_lidar_m": round(float(1.4826 * np.median(np.abs(ee - np.median(ee)))), 3),
                                 "median_minus_lidar_m": round(float(np.median(ee)), 3),
                                 "icesat2_val_rmse_m": round(float(np.sqrt(np.mean(ev * ev))), 3), "n_val": int(ev.size)})
                    print(f"   {name}_{v} {wm}/{sg_} trend={tr}: 1 km {rows[-1]['rms_1km_m']} m (flat {signal:.3f}), "
                          f"ICESat-2 val RMSE {rows[-1]['icesat2_val_rmse_m']} m", flush=True)
        df = pd.DataFrame(rows)
        df.to_csv(out / "results.csv", index=False)
        allrows += rows
        print(f"   {site} done in {time.time() - t0:.0f} s", flush=True)
    dest = REPO / "runs" / "checks" / "demnas_ground_filter.csv"
    new = pd.DataFrame(allrows)
    if dest.exists() and (a.sites or a.inputs):  # partial run: keep the other rows
        old = pd.read_csv(dest)
        new = pd.concat([old[~old.site.isin(new.site.unique())], new])
    new.to_csv(dest, index=False)
    print("wrote", dest)
    report(dest, dest.with_suffix(".md"))


if __name__ == "__main__":
    main()
