"""Can raw DEMNAS see the mapped canals? Trough depth across canals per class, DEMNAS against the 2 m LiDAR on the same transects.
Config, metrics and decision: benchmark/canal_visibility.yaml (written before any result).

    python script/canal_visibility.py benchmark/canal_visibility.yaml

Transects as repeat-neraca/scripts/check_lidar_canal_levels.py (same segments, same positions), in the LiDAR's CRS; every surface is
sampled at the same transect points (nearest cell; points are reprojected for surfaces in another CRS). Output:
runs/checks/canal_visibility.csv and .md.
"""
import argparse
import glob
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import yaml
from pyproj import Transformer
from shapely.geometry import box

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO.parent / "repeat-common" / "src"))
from repeat_common import khg as K  # noqa: E402


def sample(path, crs, xs, ys):
    with rasterio.open(path) as s:
        if s.crs != crs:
            xs, ys = Transformer.from_crs(crs, s.crs, always_xy=True).transform(xs, ys)
        v = np.array([p[0] for p in s.sample(zip(xs, ys))], float)
        if s.nodata is not None:
            v[v == s.nodata] = np.nan
    v[(v < -100) | (v > 1e4)] = np.nan
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    data = Path(os.environ.get("REPEAT_DATA") or REPO.parent / "_data")
    kdir = K.folder(cfg["khg"])
    t = cfg["transect"]
    ref = data / cfg["surfaces"]["lidar_2m"]["path"]
    with rasterio.open(ref) as r:
        crs, bounds = r.crs, r.bounds
    offs = np.arange(-t["half_length_m"], t["half_length_m"] + t["step_m"] / 2, t["step_m"])
    win = lambda c: np.abs(offs - c) <= t["window_m"]
    chance = win(0).mean()
    can = gpd.read_file(kdir / cfg["canals"]).to_crs(crs)
    can = can[can.intersects(box(*bounds)) & (can.length >= t["min_segment_m"])]
    # transect points: one row per transect, one column per offset
    P, cls = [], []
    for c, grp in can.groupby(cfg["class_field"]):
        for g in grp.sample(min(t["per_class"], len(grp)), random_state=0).geometry:
            for f in (0.2, 0.4, 0.6, 0.8):
                p, q = g.interpolate(f, normalized=True), g.interpolate(f + 0.01, normalized=True)
                dx, dy = q.x - p.x, q.y - p.y
                n = np.hypot(dx, dy)
                if n == 0:
                    continue
                P.append([(p.x - o * dy / n, p.y + o * dx / n) for o in offs])
                cls.append(c)
    P = np.array(P)
    cls = np.array(cls)
    xs, ys = P[..., 0].ravel(), P[..., 1].ravel()
    lcf = sorted(glob.glob(str(data / cfg["landcover"])))
    lc_line = np.full(len(P), np.nan)
    with rasterio.open(lcf[0]) as s0:
        lcrs = s0.crs
    lx, ly = Transformer.from_crs(crs, lcrs, always_xy=True).transform(P[:, len(offs) // 2, 0], P[:, len(offs) // 2, 1])
    for f in lcf:
        with rasterio.open(f) as s:
            inb = (lx >= s.bounds.left) & (lx < s.bounds.right) & (ly > s.bounds.bottom) & (ly <= s.bounds.top)
            if inb.any():
                lc_line[inb] = [v[0] for v in s.sample(zip(lx[inb], ly[inb]))]
    cover = np.where(lc_line == 10, "tree cover", "open")
    rows = []
    for name, sc in cfg["surfaces"].items():
        root = data if sc["root"] == "data" else kdir
        Z = sample(root / sc["path"], crs, xs, ys).reshape(P.shape[:2])
        if sc.get("along_mean_m"):
            k = max(1, int(round(sc["along_mean_m"] / t["step_m"])))
            ker = np.ones(k) / k
            Z = np.array([np.convolve(z, ker, mode="same") for z in Z])
        ok = np.isfinite(Z).mean(axis=1) > 0.9
        land = np.nanmedian(Z, axis=1)
        wmin = lambda c: np.nanmin(np.where(win(c)[None, :], Z, np.nan), axis=1) - land
        line = -wmin(0)
        ctl = -np.minimum(wmin(t["control_m"]), wmin(-t["control_m"]))   # the deeper of the two controls: a strict test
        lowest = offs[np.nanargmin(np.where(np.isfinite(Z), Z, np.inf), axis=1)]
        for c in np.unique(cls):
            for cov in ("all", "open", "tree cover"):
                m = ok & (cls == c) & ((cover == cov) if cov != "all" else True)
                if m.sum() < 20:
                    continue
                dl, dc = line[m], ctl[m]
                auc = float((dl[:, None] > dc[None, :]).mean() + 0.5 * (dl[:, None] == dc[None, :]).mean())
                rows.append({"surface": name, "class": c, "cover": cov, "transects": int(m.sum()),
                             "depth_line_median_m": round(float(np.median(dl)), 2), "depth_control_median_m": round(float(np.median(dc)), 2),
                             "auc": round(auc, 3), "found": round(float(np.mean(np.abs(lowest[m]) <= t["window_m"])), 3),
                             "chance": round(float(chance), 3)})
        print(name, "done", flush=True)
    R = pd.DataFrame(rows)
    R["visible"] = (R.auc >= 0.75) & (R.found >= 3 * R.chance)
    dest = REPO / "runs" / "checks" / "canal_visibility.csv"
    R.to_csv(dest, index=False)
    L = ["# Canal visibility in raw DEMNAS against the LiDAR, Pulau Padang", "",
         f"Generated by `script/canal_visibility.py {a.config}`; do not edit. Transects across the mapped canals, ±{t['half_length_m']} m every "
         f"{t['step_m']} m; depth = lowest value within ±{t['window_m']} m of the line (or of the controls at ±{t['control_m']} m, the deeper of "
         "the two) minus the transect median, m below the land. auc = chance that the line is deeper than the control; found = share of "
         f"transects whose lowest point is at the line (chance {chance:.0%}). lidar_8m: the 2 m LiDAR averaged over 8 m along the transect.", "",
         "| surface | class | cover | transects | depth at line (m) | control (m) | auc | found | visible |", "|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {r.surface} | {r['class']} | {r.cover} | {r.transects} | {r.depth_line_median_m:.2f} | {r.depth_control_median_m:.2f} | "
          f"{r.auc:.2f} | {r.found:.0%} | {'yes' if r.visible else 'no'} |" for _, r in R.iterrows()]
    vis = R[(R.surface == "demnas_raw") & (R.cover == "all") & R.visible]["class"].tolist()
    L += ["", "## Decision", "", f"Classes visible in raw DEMNAS (auc >= 0.75 and found >= 3 x chance, all land covers): **{', '.join(vis) if vis else 'none'}**."]
    dest.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
