"""Forest-type height offsets for DeltaDTM (ForTy 2020 classes, TMF clearing since the DEM epoch), scored against the
LiDAR. Config, expectation and decision rule: benchmark/forest_offset.yaml (written before any result).

    python script/forest_offset.py benchmark/forest_offset.yaml

Per site: class shares on the step 04 DeltaDTM grid (ForTy argmax at 10 m averaged to 30 m; TMF "cleared since the DEM"
flag regridded nearest); per variant a robust fit of surface minus reference (ICESat-2 calibration points of the site,
or LiDAR cells of the other site) on those terms, the class terms subtracted, then the pipeline mask, despike and
300/150 smoothing; scored on the LiDAR grid by zone and at the held-out ICESat-2 validation points.
Output: <benchmark>/07_forest_offset/<variant>.tif, runs/checks/forest_offset.csv and .md.
"""
import argparse
import copy
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import yaml
from rasterio.features import geometry_mask
from rasterio.warp import Resampling, reproject

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WS = REPO.parent
for p in (REPO, HERE, WS / "repeat-common" / "src"):
    sys.path.insert(0, str(p))
import demnas_dtm as dd  # noqa: E402
from canal_mask_sweep import pair_diffs  # noqa: E402
from dem_benchmark import out_dir, sample  # noqa: E402
from icesat2_subsidence_trend import huber_fit  # noqa: E402
from repeat_common import khg  # noqa: E402
from stable_land_rescore import zones  # noqa: E402

FORTY_BANDS = ["primary", "nat_regen", "planted", "plantation", "tree_crop"]


def slug(name):
    return "_".join(w.capitalize() for w in khg.slug(name).split("_"))


def terms_on_grid(cfg, data, bc, grid_prof):
    """Share of each ForTy class (1-5; 'other' is the rest) and the TMF cleared flag on the DeltaDTM grid."""
    H, W, tf, crs = grid_prof["height"], grid_prof["width"], grid_prof["transform"], grid_prof["crs"]
    out = {}
    with rasterio.open(data / cfg["forty"].format(slug=slug(bc["khg"]))) as F:
        p = F.read().astype("float32")                      # 5 x h x w, 0-250, 255 nodata
        nod = (p == 255).any(axis=0)
        other = 250 - p.sum(axis=0)
        cls = np.argmax(np.concatenate([p, other[None]], axis=0), axis=0)      # 0..5, 5 = other
        for i, name in enumerate(FORTY_BANDS):
            onehot = np.where(nod, np.nan, (cls == i).astype("float32"))
            dst = np.full((H, W), np.nan, dtype="float32")
            reproject(onehot, dst, src_transform=F.transform, src_crs=F.crs, dst_transform=tf, dst_crs=crs,
                      resampling=Resampling.average, src_nodata=np.nan, dst_nodata=np.nan)
            out[name] = dst
    with rasterio.open(data / cfg["tmf"].format(slug=slug(bc["khg"]))) as T:
        names = T.tags()["bands"].split(",")
        e = T.read(names.index(cfg["dem_epoch_band"]) + 1)
        n = T.read(names.index(cfg["now_band"]) + 1)
        flag = (np.isin(e, [1, 2]) & np.isin(n, [3, 4])).astype("float32")
        flag[(e == 0) | (n == 0)] = np.nan
        dst = np.full((H, W), np.nan, dtype="float32")
        reproject(flag, dst, src_transform=T.transform, src_crs=T.crs, dst_transform=tf, dst_crs=crs,
                  resampling=Resampling.nearest, src_nodata=np.nan, dst_nodata=np.nan)
        out["cleared"] = dst
    return out


def design(T, names, rows, cols):
    return np.column_stack([np.ones(len(rows))] + [T[n][rows, cols] for n in names])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    data = Path(os.environ.get("REPEAT_DATA") or WS / "_data")
    S = {}
    for sc in cfg["sites"]:                                  # load everything first: one variant fits on the other site
        bc = yaml.safe_load(open(REPO / sc, encoding="utf-8"))
        bench, kdir = out_dir(bc), khg.folder(bc["khg"])
        src = bench / cfg["input"]
        with rasterio.open(src) as d:
            prof = d.profile
            z = d.read(1).astype("float32")
        T = terms_on_grid(cfg, data, bc, prof)
        pts = gpd.read_file(bench / cfg["points"])
        pts = pts[pts.split.isin(["calibration", "validation"])].copy()
        r, c = rasterio.transform.rowcol(prof["transform"], pts.x.to_numpy(), pts.y.to_numpy())
        pts["row"], pts["col"] = np.asarray(r), np.asarray(c)
        pts = pts[(pts.row >= 0) & (pts.row < prof["height"]) & (pts.col >= 0) & (pts.col < prof["width"])]
        pts["res"] = z[pts.row, pts.col] - pts.H                  # surface minus ICESat-2
        # LiDAR residual on the DeltaDTM grid (cell centres), for the other site's fit
        rng = np.random.default_rng(42)
        rr, cc = np.nonzero(np.isfinite(z))
        xs, ys = rasterio.transform.xy(prof["transform"], rr, cc)
        lid = sample(str(data / bc["lidar"]["path"]), np.asarray(xs), np.asarray(ys), prof["crs"])
        ok = np.isfinite(lid)
        pick = rng.choice(np.flatnonzero(ok), min(cfg["lidar_fit_cells"], int(ok.sum())), replace=False)
        S[bc["site"]] = dict(bc=bc, bench=bench, kdir=kdir, src=src, prof=prof, z=z, T=T, pts=pts,
                             lid_rc=(rr[pick], cc[pick]), lid_res=(z[rr[pick], cc[pick]] - lid[pick]))
        print(f"{bc['site']}: {len(pts)} ICESat-2 points, ForTy/TMF terms on {prof['width']} x {prof['height']}", flush=True)

    rows, fits = [], []
    for site, s in S.items():
        other = next(k for k in S if k != site)
        bc, prof, z, T = s["bc"], s["prof"], s["z"], s["T"]
        out = s["bench"] / cfg["out"]
        out.mkdir(parents=True, exist_ok=True)
        run_cfg = yaml.safe_load(open(s["src"].parent / "config.yaml", encoding="utf-8"))
        run_cfg["smoothing"]["steps"] = [{"method": "median", "window_m": cfg["smoothing"][0]},
                                         {"method": "gaussian", "sigma_m": cfg["smoothing"][1]}]
        with rasterio.open(s["src"].parent / "landcover.tif") as L:
            lc = L.read(1)
        grid = dd.Grid(prof["crs"], prof["transform"], prof["width"], prof["height"])
        aoi = gpd.read_file(s["bench"] / "00_inputs" / "aoi_khg.gpkg").to_crs(prof["crs"]).union_all()
        inside = geometry_mask([aoi], z.shape, prof["transform"], invert=True)
        cal = s["pts"][s["pts"].split == "calibration"]
        val = s["pts"][s["pts"].split == "validation"]
        paths = {}
        for vname, v in cfg["variants"].items():
            names = (FORTY_BANDS if "forty" in v.get("terms", []) else []) + (["cleared"] if "cleared" in v.get("terms", []) else [])
            zc = z.copy()
            if names:
                if v["fit_on"] == "icesat2":
                    X, y = design(T, names, cal.row.to_numpy(), cal.col.to_numpy()), cal.res.to_numpy()
                else:
                    o = S[other]
                    X, y = design(o["T"], names, *o["lid_rc"]), o["lid_res"]
                ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
                b = huber_fit(X[ok], y[ok], cfg["huber_m"])
                fits.append({"site": site, "variant": vname, "fit_on": v["fit_on"] if v["fit_on"] == "icesat2" else f"lidar of {other}",
                             "n": int(ok.sum())} | {n: round(float(bb), 3) for n, bb in zip(names, b[1:])})
                corr = sum(b[i + 1] * np.nan_to_num(T[n], nan=0.0) for i, n in enumerate(names))
                zc = (z - corr).astype("float32")
                print(f"   {site} {vname}: " + ", ".join(f"{n} {bb:+.2f}" for n, bb in zip(names, b[1:])), flush=True)
            base = np.where(np.isin(lc, [int(x) for x in run_cfg["mask"]["landcover_classes"]]), np.nan, zc)
            ref = dd.coarse_median(base, grid, float(run_cfg["mask"]["despike_window_m"]))
            base[np.isfinite(base) & (np.abs(base - ref) > float(run_cfg["mask"]["despike_threshold_m"]))] = np.nan
            sm = dd.fill_gaps(dd.smooth(base, grid, run_cfg), int(run_cfg["smoothing"]["fill_max_search_px"]))
            sm[~inside] = np.nan
            paths[vname] = out / f"{vname}.tif"
            with rasterio.open(paths[vname], "w", **(prof | {"dtype": "float32", "nodata": np.nan, "compress": "deflate"})) as o_:
                o_.write(sm, 1)

        # scoring on the LiDAR grid inside the KHG
        b_ = gpd.read_file(data / bc["boundary"][0], layer=bc["boundary"][1])
        with rasterio.open(data / bc["lidar"]["path"]) as L:
            geom = b_[b_[bc["boundary"][2]] == bc["khg"]].to_crs(L.crs).union_all()
            w = rasterio.windows.from_bounds(*geom.bounds, L.transform).round_offsets().round_lengths() \
                .intersection(rasterio.windows.Window(0, 0, L.width, L.height))
            lz = L.read(1, window=w).astype("float32")
            lz[~np.isfinite(lz) | (lz < -100) | (lz > 1e4) | ((lz == L.nodata) if L.nodata is not None else False)] = np.nan
            ltf, lres, lcrs = L.window_transform(w), abs(L.res[0]), L.crs
        lz[~geometry_mask([geom], lz.shape, ltf, invert=True)] = np.nan
        Z = zones(cfg, s["kdir"], lz.shape, ltf, lcrs, lres)
        r2, c2 = np.nonzero(np.isfinite(lz))
        lx, ly = ltf * (c2 + 0.5, r2 + 0.5)
        for vname, p in paths.items():
            Sv = np.full(lz.shape, np.nan, dtype="float32")
            Sv[r2, c2] = sample(str(p), lx, ly, lcrs)
            ev = sample(str(p), val.x.to_numpy(), val.y.to_numpy(), prof["crs"]) - val.H.to_numpy()
            ev = ev[np.isfinite(ev)]
            row = {"site": site, "variant": vname, "icesat2_val_nmad_m": round(float(1.4826 * np.median(np.abs(ev - np.median(ev)))), 3),
                   "icesat2_val_n": int(ev.size)}
            for zn, m in Z.items():
                A, B = np.where(m, Sv, np.nan), np.where(m, lz, np.nan)
                for bm in cfg["baselines_m"]:
                    k = int(round(bm / lres))
                    da, dl = pair_diffs(A, B, k)
                    row[f"{zn}_rms_{bm}m"] = round(float(np.sqrt(np.mean((da - dl) ** 2))), 3)
                    row[f"{zn}_corr_{bm}m"] = round(float(np.corrcoef(da, dl)[0, 1]), 3)
            rows.append(row)
            print(f"   {site} {vname}: 1 km all {row['all_rms_1000m']} stable {row['stable_rms_1000m']} drained "
                  f"{row['drained_rms_1000m']}; ICESat-2 val NMAD {row['icesat2_val_nmad_m']}", flush=True)

    R, F = pd.DataFrame(rows), pd.DataFrame(fits)
    dest = REPO / "runs" / "checks" / "forest_offset.csv"
    R.to_csv(dest, index=False)
    F.to_csv(dest.with_name("forest_offset_fits.csv"), index=False)
    L = ["# Forest-type offsets for DeltaDTM", "", "Generated by `script/forest_offset.py`; do not edit. Config and decision rule: "
         "`benchmark/forest_offset.yaml`. 1 km height-difference error against the LiDAR (m, lower is better) by zone; "
         "2 km correlation (higher is better); NMAD at the held-out ICESat-2 points.", ""]
    for site in R.site.unique():
        x = R[R.site == site]
        L += [f"## {site}", "", "| variant | all 1 km | stable 1 km | drained 1 km | all corr 2 km | stable corr 2 km | ICESat-2 val NMAD |",
              "|---|---|---|---|---|---|---|"]
        L += [f"| {r.variant} | {r.all_rms_1000m:.3f} | {r.stable_rms_1000m:.3f} | {r.drained_rms_1000m:.3f} | {r.all_corr_2000m:.3f} | "
              f"{r.stable_corr_2000m:.3f} | {r.icesat2_val_nmad_m:.3f} |" for _, r in x.iterrows()]
        L.append("")
    L += ["## Fitted offsets (m, surface minus reference, relative to 'other land')", "",
          "| site | variant | fitted on | n | " + " | ".join(FORTY_BANDS + ["cleared"]) + " |", "|---|---|---|---|" + "---|" * 6]
    for _, f in F.iterrows():
        L.append(f"| {f.site} | {f.variant} | {f.fit_on} | {f.n} | " + " | ".join("" if pd.isna(f.get(n)) else f"{f[n]:+.2f}" for n in FORTY_BANDS + ["cleared"]) + " |")
    # decision
    L += ["", "## Decision", ""]
    sites = list(R.site.unique())
    passing = []
    for vname in [k for k, v in cfg["variants"].items() if v.get("fit_on") == "icesat2"]:
        ok = all(
            R[(R.site == s_) & (R.variant == vname)].iloc[0][f"{zn}_rms_1000m"] < R[(R.site == s_) & (R.variant == "none")].iloc[0][f"{zn}_rms_1000m"]
            for s_ in sites for zn in ("all", "stable")) and all(
            R[(R.site == s_) & (R.variant == vname)].iloc[0]["drained_rms_1000m"]
            <= R[(R.site == s_) & (R.variant == "none")].iloc[0]["drained_rms_1000m"] + 0.01 for s_ in sites)
        L.append(f"- `{vname}`: {'passes' if ok else 'fails'}")
        if ok:
            passing.append(vname)
    L += ["", f"**Result: {'adopt `' + passing[0] + '`' if passing else 'no ICESat-2-fitted variant passes; the pipeline is unchanged'}.**"]
    dest.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote", dest.with_suffix(".md"))


if __name__ == "__main__":
    main()
