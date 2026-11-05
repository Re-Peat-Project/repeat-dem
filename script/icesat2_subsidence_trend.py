"""Height trend of ICESat-2 ground points relative to the LiDAR, 2019-2025, inside and outside drained land.
Config and reading rules: benchmark/icesat2_subsidence_trend.yaml (written before any result).

    python script/icesat2_subsidence_trend.py benchmark/icesat2_subsidence_trend.yaml

Per site: residual r = H - LiDAR at every usable step 04 ICESat-2 point; points binned in square cells; per group a robust
(Huber, IRLS) regression of r on time (years) with annual sine/cosine terms, all demeaned within cells (cell fixed
effects), on cells with enough dates and time span. 95% intervals by resampling cells. Output:
runs/checks/icesat2_subsidence_trend.csv and .md.
"""
import argparse
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WS = REPO.parent
for p in (REPO, HERE, WS / "repeat-common" / "src"):
    sys.path.insert(0, str(p))
from dem_benchmark import out_dir, sample  # noqa: E402
from repeat_common import khg  # noqa: E402


def huber_fit(X, y, c, iters=50):
    """Robust slope coefficients by iteratively reweighted least squares (Huber weights, MAD scale)."""
    w = np.ones(len(y))
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        sw = np.sqrt(w)
        b_new = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)[0]
        r = y - X @ b_new
        a = np.abs(r)
        w = np.where(a <= c, 1.0, c / np.maximum(a, 1e-12))
        if np.allclose(b_new, b, atol=1e-6):
            b = b_new
            break
        b = b_new
    return b


def demean(df, cols, key="cell"):
    return df[cols] - df.groupby(key)[cols].transform("mean")


def fit_group(d, cfg, rng):
    cols = ["t", "s", "c"] if cfg["seasonal"] else ["t"]
    D = demean(d, ["r"] + cols)
    X, y = D[cols].to_numpy(), D["r"].to_numpy()
    slope = huber_fit(X, y, cfg["huber_m"])[0]
    cells = d.cell.unique()
    idx = {c: np.flatnonzero(d.cell.to_numpy() == c) for c in cells}
    boots = []
    for _ in range(cfg["bootstrap"]["reps"]):
        pick = rng.choice(cells, len(cells), replace=True)
        rows = np.concatenate([idx[c] for c in pick])
        sub = d.iloc[rows].copy()
        sub["cell"] = np.repeat(np.arange(len(pick)), [len(idx[c]) for c in pick])   # duplicates are separate cells
        Db = demean(sub, ["r"] + cols)
        boots.append(huber_fit(Db[cols].to_numpy(), Db["r"].to_numpy(), cfg["huber_m"])[0])
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return slope, lo, hi, np.array(boots)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    data = Path(os.environ.get("REPEAT_DATA") or WS / "_data")
    rows, diffs = [], []
    for sc in cfg["sites"]:
        bc = yaml.safe_load(open(REPO / sc, encoding="utf-8"))
        site, bench, kdir = bc["site"], out_dir(bc), khg.folder(bc["khg"])
        rng = np.random.default_rng(cfg["bootstrap"]["seed"])
        p = gpd.read_file(bench / cfg["points"])
        p = p[p.split.isin(["calibration", "validation"])].copy()
        p["lidar"] = sample(str(data / bc["lidar"]["path"]), p.x.to_numpy(), p.y.to_numpy(), p.crs)
        p = p[np.isfinite(p.lidar) & np.isfinite(p.H)].copy()
        p["r"] = p.H - p.lidar
        tt = pd.to_datetime(p.time, utc=True)
        p["day"] = tt.dt.floor("D")
        p["t"] = (tt - pd.Timestamp("2022-01-01", tz="UTC")).dt.total_seconds() / (365.25 * 86400)
        p["s"], p["c"] = np.sin(2 * np.pi * p.t), np.cos(2 * np.pi * p.t)
        cm = float(cfg["cell_m"])
        p["cell"] = (np.floor(p.x / cm).astype(np.int64) * 1_000_003 + np.floor(p.y / cm).astype(np.int64))
        can = gpd.read_file(kdir / cfg["canals"]).to_crs(p.crs)
        p["d_canal"] = gpd.sjoin_nearest(p[["geometry"]], can[["geometry"]], distance_col="d").groupby(level=0).d.min()
        L = gpd.read_file(kdir / cfg["licences"]).to_crs(p.crs)
        hit = gpd.sjoin(p[["geometry"]], L[["geometry"]], predicate="within").index
        p["licence"] = np.where(p.index.isin(hit), "inside", "outside")
        p["canopy"] = p.chm.fillna(0.0)

        g = p.groupby("cell").agg(nd=("day", "nunique"), t0=("t", "min"), t1=("t", "max"))
        keep = g[(g.nd >= cfg["min_dates_per_cell"]) & ((g.t1 - g.t0) >= cfg["min_span_years"])].index
        q = p[p.cell.isin(keep)].copy()
        print(f"{site}: {len(p)} points, {len(q)} in {len(keep)} cells with >= {cfg['min_dates_per_cell']} dates over "
              f">= {cfg['min_span_years']} yr", flush=True)

        sel = {"all": {"all": np.ones(len(q), bool)}}
        sel["licence"] = {v: (q.licence == v).to_numpy() for v in cfg["groups"]["licence"]}
        sel["distance_to_canal_m"] = {f"{lo}-{hi}": ((q.d_canal >= lo) & (q.d_canal < float(hi))).to_numpy()
                                      for lo, hi in cfg["groups"]["distance_to_canal_m"]}
        sel["canopy_m"] = {f"{lo}-{hi}": ((q.canopy >= lo) & (q.canopy < float(hi))).to_numpy() for lo, hi in cfg["groups"]["canopy_m"]}
        boots = {}
        for gname, vals in sel.items():
            for v, m in vals.items():
                d = q[m]
                d = d[d.cell.map(d.cell.value_counts()) >= 2]
                if d.cell.nunique() < 10:
                    continue
                slope, lo, hi, bt = fit_group(d, cfg, rng)
                boots[(gname, v)] = bt
                rows.append({"site": site, "group": gname, "value": v, "points": len(d), "cells": d.cell.nunique(),
                             "offset_median_m": round(float(np.median(d.r)), 3),
                             "trend_cm_per_yr": round(100 * slope, 2), "ci_lo": round(100 * lo, 2), "ci_hi": round(100 * hi, 2)})
                print(f"   {gname}={v}: {rows[-1]['trend_cm_per_yr']} cm/yr [{rows[-1]['ci_lo']}, {rows[-1]['ci_hi']}], "
                      f"{len(d)} points in {d.cell.nunique()} cells", flush=True)
        # inside minus outside: separate bootstraps, so the interval treats the two groups as independent samples
        for gname, a_, b_ in (("licence", "inside", "outside"), ("distance_to_canal_m", "0-250", "1000-inf")):
            if (gname, a_) in boots and (gname, b_) in boots:
                dd_ = boots[(gname, a_)] - boots[(gname, b_)]
                ra = next(r for r in rows if r["site"] == site and r["group"] == gname and r["value"] == a_)
                rb = next(r for r in rows if r["site"] == site and r["group"] == gname and r["value"] == b_)
                dtrend = (ra["trend_cm_per_yr"] - rb["trend_cm_per_yr"])
                doff = ra["offset_median_m"] - rb["offset_median_m"]
                lo, hi = np.percentile(100 * dd_, [2.5, 97.5])
                yrs = (doff / (dtrend / 100)) if hi < 0 else None          # both negative when drained land sank more
                ylo_hi = (np.percentile(doff / dd_[dd_ < 0], [2.5, 97.5]) if hi < 0 else (None, None))   # dd_ in m/yr
                diffs.append({"site": site, "contrast": f"{gname}: {a_} minus {b_}", "trend_diff_cm_per_yr": round(dtrend, 2),
                              "ci_lo": round(lo, 2), "ci_hi": round(hi, 2), "offset_diff_m": round(doff, 3),
                              "years_since_lidar": None if yrs is None else round(yrs, 1),
                              "years_ci": None if yrs is None else f"{ylo_hi[0]:.1f}-{ylo_hi[1]:.1f}"})
                print(f"   {diffs[-1]}", flush=True)
    rep = cfg.get("report", "icesat2_subsidence_trend")          # output name; the first run keeps the default
    dest = REPO / "runs" / "checks" / f"{rep}.csv"
    R, Dd = pd.DataFrame(rows), pd.DataFrame(diffs)
    R.to_csv(dest, index=False)
    Dd.to_csv(dest.with_name("icesat2_subsidence_contrasts.csv" if rep == "icesat2_subsidence_trend" else f"{rep}_contrasts.csv"), index=False)
    L = ["# ICESat-2 height trend relative to the LiDAR, 2019-2025", "",
         "Generated by `script/icesat2_subsidence_trend.py`; do not edit. Config and reading rules: "
         f"`{a.config}`. Trend within 500 m cells, robust fit with annual terms, 95% interval "
         "from resampling cells. Offset: median of ICESat-2 minus LiDAR in the group.", ""]
    for site in R.site.unique():
        L += [f"## {site}", "", "| group | value | points | cells | offset (m) | trend (cm/yr) | 95% interval |", "|---|---|---|---|---|---|---|"]
        L += [f"| {r.group} | {r.value} | {r.points} | {r.cells} | {r.offset_median_m:+.3f} | {r.trend_cm_per_yr:+.2f} | "
              f"{r.ci_lo:+.2f} to {r.ci_hi:+.2f} |" for _, r in R[R.site == site].iterrows()]
        L.append("")
    L += ["## Contrasts", "", "| site | contrast | trend difference (cm/yr) | 95% interval | offset difference (m) | years since LiDAR (if the trend difference is below 0) |",
          "|---|---|---|---|---|---|"]
    L += [f"| {r.site} | {r.contrast} | {r.trend_diff_cm_per_yr:+.2f} | {r.ci_lo:+.2f} to {r.ci_hi:+.2f} | {r.offset_diff_m:+.3f} | "
          f"{'' if pd.isna(r.years_since_lidar) else f'{r.years_since_lidar} ({r.years_ci})'} |" for _, r in Dd.iterrows()]
    dest.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote", dest.with_suffix(".md"))


if __name__ == "__main__":
    main()
