"""Re-score the DEM benchmark on stable land (outside licences, far from canals), where the LiDAR is not out of date.
Config and reading rules: benchmark/stable_land_rescore.yaml (written before any result).

    python script/stable_land_rescore.py benchmark/stable_land_rescore.yaml

Per site: reads the step 02/04 error maps (candidate minus LiDAR, on the LiDAR grid) and the LiDAR on the same grid;
builds zones from the licence layer and the distance to the nearest mapped canal; per candidate, state and zone computes
NMAD, median, error of height differences over each baseline (pairs with both cells in the zone), the LiDAR's own
signal and the correlation of candidate and LiDAR height differences. Output: runs/checks/stable_land_rescore.csv and .md.
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
from rasterio.windows import from_bounds
from scipy import ndimage

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WS = REPO.parent
for p in (REPO, HERE, WS / "repeat-common" / "src"):
    sys.path.insert(0, str(p))
from canal_mask_sweep import pair_diffs  # noqa: E402
from dem_benchmark import out_dir  # noqa: E402
from repeat_common import khg  # noqa: E402


def zones(cfg, kdir, shape, tf, crs, res):
    lic = gpd.read_file(kdir / cfg["licences"]).to_crs(crs)
    inside = rasterize([(g, 1) for g in lic.geometry if g is not None and not g.is_empty], out_shape=shape, transform=tf,
                       fill=0, dtype="uint8").astype(bool)
    can = gpd.read_file(kdir / cfg["canals"]).to_crs(crs)
    c = rasterize([(g, 1) for g in can.geometry if g is not None and not g.is_empty], out_shape=shape, transform=tf,
                  fill=0, all_touched=True, dtype="uint8")
    d = ndimage.distance_transform_edt(c == 0) * res
    z = {}
    for name, rule in cfg["zones"].items():
        m = np.ones(shape, bool)
        if rule.get("licence") == "outside":
            m &= ~inside
        if "min_canal_distance_m" in rule:
            m &= d > float(rule["min_canal_distance_m"])
        if "licence_or_near_canal_m" in rule:
            m &= inside | (d < float(rule["licence_or_near_canal_m"]))
        z[name] = m
    return z


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    data = Path(os.environ.get("REPEAT_DATA") or WS / "_data")
    rows = []
    for sc in cfg["sites"]:
        bc = yaml.safe_load(open(REPO / sc, encoding="utf-8"))
        site, bench, kdir = bc["site"], out_dir(bc), khg.folder(bc["khg"])
        em_dir = bench / cfg["error_maps"]
        with rasterio.open(em_dir / cfg["states"]["as_delivered"].format(c=cfg["candidates"][0])) as e0:
            tf, crs, shape, res = e0.transform, e0.crs, e0.shape, abs(e0.res[0])
            bounds = e0.bounds
        with rasterio.open(data / bc["lidar"]["path"]) as L:
            assert abs(L.res[0] - res) < 1e-6, "error maps are not on the LiDAR grid"
            w = from_bounds(*bounds, L.transform).round_offsets().round_lengths()
            lid = L.read(1, window=w, boundless=True, fill_value=np.nan).astype("float32")
            if L.nodata is not None:
                lid[lid == L.nodata] = np.nan
            lid[(lid < -100) | (lid > 1e4)] = np.nan
        assert lid.shape == shape, (lid.shape, shape)
        Z = zones(cfg, kdir, shape, tf, crs, res)
        valid = np.isfinite(lid)
        for zn, m in Z.items():
            share = 100 * float((m & valid).sum()) / max(int(valid.sum()), 1)
            lz = np.where(m, lid, np.nan)
            sig = {}
            for bm in cfg["baselines_m"]:
                k = int(round(bm / res))
                da, _ = pair_diffs(lz, lz, k)
                sig[bm] = float(np.sqrt(np.mean(da ** 2))) if da.size else np.nan
            for c in cfg["candidates"]:
                for state, pat in cfg["states"].items():
                    p = em_dir / pat.format(c=c)
                    if not p.exists():
                        continue
                    with rasterio.open(p) as E:
                        e = E.read(1).astype("float32")
                        if E.nodata is not None:
                            e[e == E.nodata] = np.nan
                    e = np.where(m & valid, e, np.nan)
                    cand = e + lz
                    ok = np.isfinite(e)
                    if ok.sum() < 1000:
                        continue
                    med = float(np.median(e[ok]))
                    r = {"site": site, "zone": zn, "zone_pct_of_lidar": round(share, 1), "candidate": c, "state": state,
                         "cells": int(ok.sum()), "median_m": round(med, 3),
                         "nmad_m": round(float(1.4826 * np.median(np.abs(e[ok] - med))), 3)}
                    for bm in cfg["baselines_m"]:
                        k = int(round(bm / res))
                        dc, dl = pair_diffs(cand, lz, k)
                        r[f"rms_{bm}m"] = round(float(np.sqrt(np.mean((dc - dl) ** 2))), 3)
                        r[f"corr_{bm}m"] = round(float(np.corrcoef(dc, dl)[0, 1]), 3)
                        r[f"lidar_signal_{bm}m"] = round(sig[bm], 3)
                    r["tier_a_pass"] = r["rms_1000m"] <= bc["criterion"]["tier_a_rms_m"]
                    r["tier_b_pass"] = r["rms_1000m"] <= bc["criterion"]["tier_b_fraction_of_signal"] * sig[1000]
                    rows.append(r)
                    print(f"{site} {zn} {c} {state}: 1 km {r['rms_1000m']} (signal {sig[1000]:.3f}), corr 2 km {r['corr_2000m']}", flush=True)
    d = pd.DataFrame(rows)
    dest = REPO / "runs" / "checks" / "stable_land_rescore.csv"
    d.to_csv(dest, index=False)
    L = ["# DEM benchmark re-scored on stable land", "",
         "Generated by `script/stable_land_rescore.py`; do not edit. Config and reading rules: `benchmark/stable_land_rescore.yaml`. "
         "Stable: outside licences and more than 1 km from a mapped canal. Drained: inside a licence or within 250 m of a canal. "
         "Errors in m (lower is better); correlation of candidate and LiDAR height differences (higher is better).", ""]
    for site in d.site.unique():
        x = d[d.site == site]
        L += [f"## {site}", ""]
        for zn in x.zone.unique():
            y = x[x.zone == zn]
            L += [f"### {zn}: {y.zone_pct_of_lidar.iloc[0]}% of LiDAR cells; LiDAR's own 1 km signal {y.lidar_signal_1000m.iloc[0]:.3f} m", "",
                  "| candidate | state | NMAD | median | 0.5 km | 1 km | 2 km | corr 1 km | corr 2 km | Tier A | Tier B |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
            for _, r in y.sort_values(["state", "rms_1000m"]).iterrows():
                L.append(f"| {r.candidate} | {r.state} | {r.nmad_m:.3f} | {r.median_m:+.3f} | {r.rms_500m:.3f} | {r.rms_1000m:.3f} | "
                         f"{r.rms_2000m:.3f} | {r.corr_1000m:.3f} | {r.corr_2000m:.3f} | {'pass' if r.tier_a_pass else 'fail'} | "
                         f"{'pass' if r.tier_b_pass else 'fail'} |")
            L.append("")
        p = x[x.state == "processed"].pivot_table(index="candidate", columns="zone", values="rms_1000m", aggfunc="first")
        if {"all", "stable"} <= set(p.columns):
            p["stable_minus_all"] = p["stable"] - p["all"]
            L += ["### Processed, 1 km error by zone", "", "| candidate | " + " | ".join(p.columns) + " |", "|---|" + "---|" * len(p.columns)]
            L += [f"| {c} | " + " | ".join(f"{v:+.3f}" if col == "stable_minus_all" else f"{v:.3f}" for col, v in r.items()) + " |"
                  for c, r in p.sort_values("all").iterrows()]
            L += ["", f"Ranking on all cells: {', '.join(p.sort_values('all').index)}. Ranking on stable land: "
                      f"{', '.join(p.sort_values('stable').index)}.", ""]
    dest.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote", dest.with_suffix(".md"))


if __name__ == "__main__":
    main()
