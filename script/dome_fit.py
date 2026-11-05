"""Dome-shaped (constant-curvature) surfaces per sub-KHG unit: premise check on the LiDAR and a first test on DeltaDTM.
Config, reading and decisions: benchmark/dome_fit.yaml (written before any result).

    python script/dome_fit.py benchmark/dome_fit.yaml

Per site, on a 100 m grid over the KHG (LiDAR and DeltaDTM averaged onto it): per LiDAR sub-KHG unit, a robust (Huber)
quadratic z = a + b x + c y + d x^2 + e xy + f y^2 (constant Hessian) fitted on interior cells (away from canals) to the
LiDAR and to DeltaDTM; surfaces baseline / dome / dome_local / oracle_tilt / lidar_dome assembled per cell and scored
against the LiDAR by the error and correlation of height differences. The LiDAR never enters `dome` or `dome_local`.
Output: <benchmark>/08_dome_fit/<surface>.tif, runs/checks/dome_fit.csv, dome_fit_units.csv and dome_fit.md.
"""
import argparse
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import yaml
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from scipy import ndimage

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WS = REPO.parent
for p in (REPO, HERE, WS / "repeat-common" / "src"):
    sys.path.insert(0, str(p))
from canal_mask_sweep import pair_diffs  # noqa: E402
from dem_benchmark import out_dir  # noqa: E402
from icesat2_subsidence_trend import huber_fit  # noqa: E402
from repeat_common import khg  # noqa: E402

SURFACES = ["baseline", "dome", "dome_local", "oracle_tilt", "lidar_dome"]


def onto(path, grid, nod=None):
    H, W, tf, crs = grid
    dst = np.full((H, W), np.nan, dtype="float32")
    with rasterio.open(path) as s:
        src = s.read(1).astype("float32")
        if s.nodata is not None and not np.isnan(s.nodata):
            src[src == s.nodata] = np.nan
        src[(src < -100) | (src > 1e4)] = np.nan
        reproject(src, dst, src_transform=s.transform, src_crs=s.crs, dst_transform=tf, dst_crs=crs,
                  resampling=Resampling.average, src_nodata=np.nan, dst_nodata=np.nan)
    return dst


def quad_design(x, y):
    return np.column_stack([np.ones_like(x), x, y, x * x, x * y, y * y])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    data = Path(os.environ.get("REPEAT_DATA") or WS / "_data")
    rows, urows = [], []
    for sc in cfg["sites"]:
        bc = yaml.safe_load(open(REPO / sc, encoding="utf-8"))
        site, bench, kdir = bc["site"], out_dir(bc), khg.folder(bc["khg"])
        out = bench / cfg["out"]
        out.mkdir(parents=True, exist_ok=True)
        with rasterio.open(data / bc["lidar"]["path"]) as L:
            crs = L.crs
        b = gpd.read_file(data / bc["boundary"][0], layer=bc["boundary"][1])
        geom = b[b[bc["boundary"][2]] == bc["khg"]].to_crs(crs).union_all()
        g = float(cfg["grid_m"])
        x0, y0, x1, y1 = geom.bounds
        x0, y1 = np.floor(x0 / g) * g, np.ceil(y1 / g) * g
        W, H = int(np.ceil((x1 - x0) / g)), int(np.ceil((y1 - y0) / g))
        tf = from_origin(x0, y1, g, g)
        grid = (H, W, tf, crs)
        lid = onto(data / bc["lidar"]["path"], grid)
        dat = onto(bench / cfg["deltadtm_data"], grid)
        base = onto(bench / cfg["deltadtm_baseline"], grid)
        units = gpd.read_file(kdir / cfg["units"]).to_crs(crs)
        uid = rasterize([(gg, i + 1) for i, gg in enumerate(units.geometry)], out_shape=(H, W), transform=tf, fill=0, dtype="int32")
        can = gpd.read_file(kdir / cfg["canals"]).to_crs(crs)
        cr = rasterize([(gg, 1) for gg in can.geometry if gg is not None and not gg.is_empty], out_shape=(H, W), transform=tf,
                       fill=0, all_touched=True, dtype="uint8")
        dcan = ndimage.distance_transform_edt(cr == 0) * g
        cols, rws = np.meshgrid(np.arange(W), np.arange(H))
        X = (x0 + (cols + 0.5) * g) / 1000.0
        Y = (y1 - (rws + 0.5) * g) / 1000.0
        S = {s: base.copy() for s in SURFACES}
        S["baseline"] = base
        for i in range(1, len(units) + 1):
            m = uid == i
            interior = m & np.isfinite(lid) & np.isfinite(dat)          # all cells of the unit with data (amendment, run 2)
            if interior.sum() < cfg["min_cells"]:
                urows.append({"site": site, "unit": units.iloc[i - 1].get("unit_id", i), "cells": int(interior.sum()), "fitted": False})
                continue
            xc, yc = X[interior].mean(), Y[interior].mean()
            sw = np.sqrt(np.where(dcan[interior] > cfg["interior_min_canal_m"], 1.0, cfg["near_canal_weight"]))
            Di = quad_design(X[interior] - xc, Y[interior] - yc)
            Dm = quad_design(X[m] - xc, Y[m] - yc)
            wfit = lambda D, y: huber_fit(D * sw[:, None], y.astype(float) * sw, cfg["huber_m"])
            bl = wfit(Di, lid[interior])
            bd = wfit(Di, dat[interior])
            bp = wfit(Di[:, :3], lid[interior])        # LiDAR plane only
            r_quad = lid[interior] - Di @ bl
            r_plane = lid[interior] - Di[:, :3] @ bp
            v0 = np.var(lid[interior])
            # oracle: DeltaDTM curvature, plane (offset and tilt) fitted to LiDAR minus that curvature
            curv_d = Di[:, 3:] @ bd[3:]
            bo = wfit(Di[:, :3], lid[interior] - curv_d)
            dome = Dm @ bd
            S["dome"][m] = dome
            S["oracle_tilt"][m] = Dm[:, :3] @ bo + Dm[:, 3:] @ bd[3:]
            S["lidar_dome"][m] = Dm @ bl
            r = np.full((H, W), np.nan, dtype="float32")
            r[m] = dat[m] - dome
            urows.append({"site": site, "unit": units.iloc[i - 1].get("unit_id", i), "cells": int(interior.sum()), "fitted": True,
                          "lidar_relief_m": round(float(np.nanpercentile(lid[interior], 95) - np.nanpercentile(lid[interior], 5)), 2),
                          "r2_quad": round(float(1 - np.var(r_quad) / v0), 3), "r2_plane": round(float(1 - np.var(r_plane) / v0), 3),
                          "lidar_resid_rms_m": round(float(np.sqrt(np.mean((r_quad - r_quad.mean()) ** 2))), 3),
                          "laplacian_lidar_m_per_km2": round(float(2 * bl[3] + 2 * bl[5]), 3),
                          "laplacian_deltadtm_m_per_km2": round(float(2 * bd[3] + 2 * bd[5]), 3)})
            S.setdefault("_resid", np.full((H, W), np.nan, dtype="float32"))
            S["_resid"][m] = r[m]
            S.setdefault("_coef", []).append((i, xc, yc, bd))
        # dome_local: dome + residual smoothed by a 300 m gaussian (nan-aware)
        res = S.pop("_resid", np.full((H, W), np.nan, dtype="float32"))
        coefs = S.pop("_coef", [])
        if cfg.get("write_30m"):
            # dome_local on the DeltaDTM grid (30 m) for the delineation test: unit quadratics from the 100 m fit, plus the 30 m
            # residual (data minus quadratic) smoothed by the same 300 m gaussian; baseline outside fitted units
            with rasterio.open(bench / cfg["deltadtm_data"]) as d30, rasterio.open(bench / cfg["deltadtm_baseline"]) as b30:
                z30, p30 = d30.read(1).astype("float32"), b30.profile
                bz30 = b30.read(1).astype("float32")
                t30 = d30.transform
            H3, W3 = z30.shape
            u30 = rasterize([(gg, k + 1) for k, gg in enumerate(units.to_crs(p30["crs"]).geometry)], out_shape=(H3, W3),
                            transform=t30, fill=0, dtype="int32")
            c3, r3 = np.meshgrid(np.arange(W3), np.arange(H3))
            X3, Y3 = (t30.c + (c3 + 0.5) * t30.a) / 1000.0, (t30.f + (r3 + 0.5) * t30.e) / 1000.0
            Q = np.full((H3, W3), np.nan, dtype="float32")
            for i, xc, yc, bd in coefs:
                mm = u30 == i
                Q[mm] = quad_design(X3[mm] - xc, Y3[mm] - yc) @ bd
            rr = np.where(np.isfinite(Q) & np.isfinite(z30), z30 - Q, np.nan)
            okr = np.isfinite(rr)
            s3 = 300.0 / abs(t30.a)
            sm3 = ndimage.gaussian_filter(np.where(okr, rr, 0.0), s3) / np.maximum(ndimage.gaussian_filter(okr.astype(float), s3), 1e-3)
            out30 = np.where(np.isfinite(Q), Q + sm3, bz30).astype("float32")
            out30[~np.isfinite(bz30)] = np.nan
            with rasterio.open(out / "dome_local_30m.tif", "w", **(p30 | {"dtype": "float32", "nodata": np.nan, "compress": "deflate"})) as o:
                o.write(out30, 1)
        ok = np.isfinite(res)
        sig = 300.0 / g
        num = ndimage.gaussian_filter(np.where(ok, res, 0.0), sig)
        den = ndimage.gaussian_filter(ok.astype(float), sig)
        sm = np.where(den > 1e-3, num / np.maximum(den, 1e-3), np.nan)
        fitted = np.isin(uid, [k + 1 for k in range(len(units))]) & ok
        S["dome_local"] = np.where(fitted, S["dome"] + sm, base)
        inside = (uid > 0) & np.isfinite(lid)
        prof = {"driver": "GTiff", "width": W, "height": H, "count": 1, "dtype": "float32", "crs": crs, "transform": tf,
                "nodata": np.nan, "compress": "deflate"}
        flat = np.where(inside, np.float32(np.nanmedian(lid[inside])), np.nan)
        for name, surf in list(S.items()) + [("flat", flat)]:
            Z = np.where(inside, surf, np.nan).astype("float32")
            if name != "flat":
                with rasterio.open(out / f"{name}.tif", "w", **prof) as o:
                    o.write(Z, 1)
            row = {"site": site, "surface": name}
            Lz = np.where(inside, lid, np.nan)
            for bm in cfg["baselines_m"]:
                k = int(round(bm / g))
                da, dl = pair_diffs(Z, Lz, k)
                row[f"rms_{bm}m"] = round(float(np.sqrt(np.mean((da - dl) ** 2))), 3)
                row[f"corr_{bm}m"] = 0.0 if name == "flat" else round(float(np.corrcoef(da, dl)[0, 1]), 3)
            rows.append(row)
            print(f"{site} {name}: " + ", ".join(f"{bm / 1000:g} km {row[f'rms_{bm}m']} (r {row[f'corr_{bm}m']})" for bm in cfg["baselines_m"]), flush=True)

    R, U = pd.DataFrame(rows), pd.DataFrame(urows)
    dest = REPO / "runs" / "checks" / f"{cfg.get('report', 'dome_fit')}.csv"
    R.to_csv(dest, index=False)
    U.to_csv(dest.with_name(dest.stem + "_units.csv"), index=False)
    L = ["# Dome-shaped surfaces per sub-KHG unit", "", f"Generated by `script/dome_fit.py {a.config}`; do not edit. Config, reading and decisions: "
         f"`{a.config}`. 100 m grid; error of height differences against the LiDAR (m, lower is better) and their correlation.", ""]
    for site in R.site.unique():
        x = R[R.site == site]
        u = U[(U.site == site) & (U.fitted)]
        L += [f"## {site}", "", f"Units fitted: {len(u)} of {int((U.site == site).sum())}. LiDAR premise: median R2 quadratic "
              f"{u.r2_quad.median():.2f} (plane {u.r2_plane.median():.2f}); median residual {u.lidar_resid_rms_m.median():.2f} m against a "
              f"median 5-95% relief of {u.lidar_relief_m.median():.2f} m; Laplacian negative (dome) in {int((u.laplacian_lidar_m_per_km2 < 0).sum())} "
              f"of {len(u)} units (LiDAR) and {int((u.laplacian_deltadtm_m_per_km2 < 0).sum())} (DeltaDTM); Spearman of the two Laplacians "
              f"{u.laplacian_lidar_m_per_km2.corr(u.laplacian_deltadtm_m_per_km2, method='spearman'):.2f}.", "",
              "| surface | 1 km | 2 km | 4 km | corr 1 km | corr 2 km | corr 4 km |", "|---|---|---|---|---|---|---|"]
        L += [f"| {r.surface} | {r.rms_1000m:.3f} | {r.rms_2000m:.3f} | {r.rms_4000m:.3f} | {r.corr_1000m:.3f} | {r.corr_2000m:.3f} | "
              f"{r.corr_4000m:.3f} |" for _, r in x.iterrows()]
        L.append("")
    sites = list(R.site.unique())
    g_ = lambda s, n, c: R[(R.site == s) & (R.surface == n)].iloc[0][c]
    prem = all(U[(U.site == s) & U.fitted].r2_quad.median() >= 0.5 and
               (U[(U.site == s) & U.fitted].laplacian_lidar_m_per_km2 < 0).mean() > 0.5 for s in sites)
    helps = [n for n in ("dome", "dome_local") if all(g_(s, n, "rms_2000m") < g_(s, "baseline", "rms_2000m") and
                                                     g_(s, n, "corr_2000m") >= g_(s, "baseline", "corr_2000m") for s in sites)]
    edge = all(g_(s, "oracle_tilt", "rms_2000m") <= 0.7 * g_(s, "baseline", "rms_2000m") for s in sites)
    L += ["## Decisions", "", f"1. Premise (median R2 >= 0.5 and dome-shaped in most units, both sites): **{'holds' if prem else 'does not hold'}**.",
          f"2. Data-only dome helps at both sites: **{', '.join(helps) if helps else 'no'}**.",
          f"3. Perfect edges would cut the 2 km error by at least 30% at both sites: **{'yes' if edge else 'no'}**."]
    dest.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote", dest.with_suffix(".md"))


if __name__ == "__main__":
    main()
