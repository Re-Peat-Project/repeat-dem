"""Benchmark candidate elevation surfaces against airborne lidar, per KHG, at every lidar cell.

    python script/lidar_benchmark.py [--config script/lidar_benchmark.yaml] [--out runs/lidar_benchmark.csv]

For each site in the config, every valid lidar cell inside the KHG boundary is compared with each surface
(nearest surface cell to the lidar cell centre; no resampling of either raster). The lidar is read in blocks,
so a 2 m DTM over a whole island fits in memory. Differences (surface - lidar) are accumulated in 1 cm bins,
so median and NMAD are exact to 1 cm. No vertical datum conversion: a constant offset shows in the median and
cancels in NMAD and in the median-removed shares.

Columns: n (lidar cells compared), median, NMAD (1.4826 x median absolute deviation from the median), mean, RMSE,
p05/p95, share of cells within 0.05 / 0.25 m of the median (how much of the surface follows the lidar shape),
and the lidar elevation range p05..p95 for scale.
Needs rasterio, geopandas, numpy, pandas, pyyaml, pyproj.
"""
import argparse
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import yaml
from pyproj import Transformer
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds

HERE = Path(__file__).resolve().parent
BLOCK = 4096  # lidar cells per side per read
EDGES = np.arange(-60, 60.0001, 0.01)  # 1 cm bins, surface - lidar (m)
ZEDGES = np.arange(-20, 200.0001, 0.01)


def valid(a, nodata):
    ok = np.isfinite(a) & (a > -100) & (a < 1e4)
    return ok & (a != nodata) if nodata is not None else ok


def hist_stats(h, edges):
    n = h.sum()
    if not n:
        return {}
    mid = (edges[:-1] + edges[1:]) / 2
    c = np.cumsum(h)
    q = lambda p: float(mid[np.searchsorted(c, p * n)])  # noqa: E731
    med = q(0.5)
    dev = np.abs(mid - med)
    o = np.argsort(dev)
    mad = float(dev[o][np.searchsorted(np.cumsum(h[o]), 0.5 * n)])
    near = lambda t: float(h[dev <= t].sum() / n)  # noqa: E731
    return {"n": int(n), "median": round(med, 3), "nmad": round(1.4826 * mad, 3), "p05": round(q(0.05), 2), "p95": round(q(0.95), 2),
            "within_0.05m_of_median_pct": round(100 * near(0.05), 1), "within_0.25m_of_median_pct": round(100 * near(0.25), 1)}


def run_site(data, site, boundary):
    b = gpd.read_file(data / boundary[0], layer=boundary[1])
    with rasterio.open(data / site["lidar"]) as L:
        geom = b[b[boundary[2]] == site["khg"]].to_crs(L.crs).union_all()
        win = from_bounds(*geom.bounds, L.transform).round_offsets().round_lengths().intersection(Window(0, 0, L.width, L.height))
        surf = {k: rasterio.open(data / p) for k, p in site["surfaces"].items()}
        tf = {k: Transformer.from_crs(L.crs, s.crs, always_xy=True) for k, s in surf.items()}
        hist = {k: np.zeros(len(EDGES) - 1, np.int64) for k in surf}
        sums = {k: [0.0, 0.0] for k in surf}
        zh = np.zeros(len(ZEDGES) - 1, np.int64)
        for r0 in range(int(win.row_off), int(win.row_off + win.height), BLOCK):
            for c0 in range(int(win.col_off), int(win.col_off + win.width), BLOCK):
                w = Window(c0, r0, min(BLOCK, win.col_off + win.width - c0), min(BLOCK, win.row_off + win.height - r0))
                m = geometry_mask([geom], (int(w.height), int(w.width)), L.window_transform(w), invert=True)
                if not m.any():
                    continue
                z = L.read(1, window=w).astype("float64")
                m &= valid(z, L.nodata)
                if not m.any():
                    continue
                rr, cc = np.nonzero(m)
                x, y = L.window_transform(w) * (cc + 0.5, rr + 0.5)
                zl = z[rr, cc]
                zh += np.histogram(zl, ZEDGES)[0]
                for k, s in surf.items():
                    sx, sy = tf[k].transform(x, y)
                    sw = from_bounds(sx.min(), sy.min(), sx.max(), sy.max(), s.transform).round_offsets().round_lengths()
                    sw = Window(sw.col_off - 1, sw.row_off - 1, sw.width + 3, sw.height + 3).intersection(Window(0, 0, s.width, s.height))
                    a = s.read(1, window=sw).astype("float64")
                    ok_a = valid(a, s.nodata)
                    t = s.window_transform(sw)
                    ci = np.floor((sx - t.c) / t.a).astype(np.int64)
                    ri = np.floor((sy - t.f) / t.e).astype(np.int64)
                    ins = (ci >= 0) & (ri >= 0) & (ci < a.shape[1]) & (ri < a.shape[0])
                    ins[ins] &= ok_a[ri[ins], ci[ins]]
                    d = a[ri[ins], ci[ins]] - zl[ins]
                    hist[k] += np.histogram(d, EDGES)[0]
                    sums[k][0] += d.sum()
                    sums[k][1] += (d * d).sum()
        zs = hist_stats(zh, ZEDGES)
        rows = []
        for k in surf:
            st = hist_stats(hist[k], EDGES)
            n = st.get("n", 0)
            rows.append({"khg": site["khg"], "lidar": site["lidar"], "lidar_res_m": round(abs(L.res[0]), 2), "surface": k,
                         "surface_path": site["surfaces"][k], "surface_res": round(abs(surf[k].res[0]), 6),
                         "lidar_cells_in_khg": zs.get("n"), "share_compared_pct": round(100 * n / zs["n"], 1) if n else 0, **st,
                         "mean": round(sums[k][0] / n, 3) if n else None, "rmse": round(np.sqrt(sums[k][1] / n), 3) if n else None,
                         "lidar_z_p05": zs.get("p05"), "lidar_z_p95": zs.get("p95")})
            print(rows[-1], flush=True)
        for s in surf.values():
            s.close()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "lidar_benchmark.yaml"))
    ap.add_argument("--out", default=str(HERE.parent / "runs" / "lidar_benchmark.csv"))
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    data = Path(os.environ.get("REPEAT_DATA") or HERE.parents[1] / "_data")
    rows = []
    for site in cfg["sites"]:
        print("##", site["khg"], flush=True)
        rows += run_site(data, site, cfg["boundary"])
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(a.out, index=False)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
