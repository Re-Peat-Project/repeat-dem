"""Relative (pairwise) DEM error from the cached ground points of a run.

For usable points, takes the error of a surface (default err_dtm_smooth), removes the
site-wide median, and reports the RMS and NMAD of the error *difference* between pairs of
points in distance bins. This is the quantity the water-sharing model cares about: how wrong
is the height difference between two places h metres apart.

Caveats: the ground heights are ICESat-2/GEDI, which carry their own error; differences at
the shortest lag (< 150 m, mostly along one track) bound the point noise but do not remove it.

  python script/relative_error.py runs/exp_joint runs/mendahara_30m --col err_dtm_smooth
"""
import argparse

import geopandas as gpd
import numpy as np
from scipy.spatial import cKDTree

BINS = [(0, 150), (150, 300), (300, 600), (600, 1000), (1000, 2000), (2000, 4000), (4000, 8000)]


def pair_stats(run: str, col: str, max_points: int, seed: int):
    g = gpd.read_file(f"{run}/ground_points.gpkg")
    g = g[g["exclude_reason"].fillna("") == ""]
    e = g[col].to_numpy(float)
    xy = np.c_[g["x"].to_numpy(float), g["y"].to_numpy(float)]
    ok = np.isfinite(e)
    e, xy = e[ok], xy[ok]
    if len(e) > max_points:
        i = np.random.default_rng(seed).choice(len(e), max_points, replace=False)
        e, xy = e[i], xy[i]
    e = e - np.median(e)
    pairs = cKDTree(xy).query_pairs(BINS[-1][1], output_type="ndarray")
    dist = np.hypot(*(xy[pairs[:, 0]] - xy[pairs[:, 1]]).T)
    de = e[pairs[:, 0]] - e[pairs[:, 1]]
    rows = []
    for lo, hi in BINS:
        m = (dist >= lo) & (dist < hi)
        if m.sum() > 50:
            d = de[m]
            rows.append((lo, hi, int(m.sum()), float(np.sqrt(np.mean(d**2))),
                         float(1.4826 * np.median(np.abs(d - np.median(d))))))
    return len(e), float(e.std()), rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="run folders containing ground_points.gpkg")
    ap.add_argument("--col", default="err_dtm_smooth",
                    help="error column: err_dem_raw, err_dtm_calibrated or err_dtm_smooth")
    ap.add_argument("--max-points", type=int, default=9000, help="subsample size (pairs grow quadratically)")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    for run in a.runs:
        n, sd, rows = pair_stats(run, a.col, a.max_points, a.seed)
        print(f"\n{run}  {a.col}: n={n}, sd={sd:.2f} m")
        print("  lag (m)       pairs   rms diff (m)   nmad diff (m)")
        for lo, hi, k, rms, nmad in rows:
            print(f"  {lo:>5}-{hi:<5} {k:>9}   {rms:>8.2f}       {nmad:>8.2f}")
