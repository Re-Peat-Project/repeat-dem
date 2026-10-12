"""Compare a run's surfaces with an airborne-lidar DTM, held out of calibration.

1. Aggregates the lidar pixels straight into the run grid (no resampling grid offset).
2. Absolute error of dem_utm / dtm_corrected / dtm_smooth by land cover and canopy height.
3. Relative error: detrended error, error of the height difference over 0.5/1/2 km
   baselines, and the semivariogram of (surface - lidar) with an exponential fit.
4. Three-way table at the ICESat-2/GEDI points: DEM-lidar, DEM-ground, ground-lidar.

The lidar vertical datum is NOT assumed. A constant offset cancels in every relative
statistic; absolute figures are reported both raw and with the median removed.

  python script/lidar_compare.py runs/bengkalis_30m_gt "path/DTM_2mFloat.tif" \
      --out runs/padang_lidar --lidar-year 2016 --datum "unknown"
"""
import argparse
import json
import os

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.windows import Window
from scipy.optimize import curve_fit
from scipy.spatial import cKDTree

SURFACES = ["dem_utm", "dtm_corrected", "dtm_smooth"]
BASELINES = [500, 1000, 2000]
LAGS = [0, 60, 120, 240, 480, 800, 1200, 2000, 3000, 4500, 7000, 10000]


def nmad(d):
    return float(1.4826 * np.median(np.abs(d - np.median(d))))


def stats(d):
    d = d[np.isfinite(d)]
    if d.size < 30:
        return None
    return dict(n=int(d.size), median=float(np.median(d)), nmad=nmad(d), sd=float(d.std()),
                rmse=float(np.sqrt(np.mean(d**2))))


def aggregate(lidar, grid, strip=500, min_cov=0.0):
    """Mean, std and coverage of the lidar pixels inside each run-grid cell, over the lidar footprint."""
    with rasterio.open(lidar) as s, rasterio.open(grid) as g:
        gt, lt = g.transform, s.transform
        res = gt.a
        c0 = max(0, int(np.floor((lt.c - gt.c) / res)))
        r0 = max(0, int(np.floor((gt.f - lt.f) / res)))
        c1 = min(g.width, int(np.ceil((lt.c + s.width * lt.a - gt.c) / res)))
        r1 = min(g.height, int(np.ceil((gt.f - (lt.f + s.height * lt.e)) / res)))
        gw, gh = c1 - c0, r1 - r0
        n = np.zeros(gw * gh); sm = np.zeros(gw * gh); s2 = np.zeros(gw * gh)
        npix_cell = (res / abs(lt.a)) * (res / abs(lt.e))
        xs = lt.c + (np.arange(s.width) + 0.5) * lt.a
        ci = np.floor((xs - gt.c) / res).astype(int) - c0
        for r in range(0, s.height, strip):
            h = min(strip, s.height - r)
            a = s.read(1, window=Window(0, r, s.width, h)).astype(np.float64)
            ys = lt.f + (np.arange(r, r + h) + 0.5) * lt.e
            ri = np.floor((gt.f - ys) / res).astype(int) - r0
            ok = (a != s.nodata) & np.isfinite(a)
            ok &= ((ri >= 0) & (ri < gh))[:, None] & ((ci >= 0) & (ci < gw))[None, :]
            idx = (ri[:, None] * gw + ci[None, :])[ok]
            v = a[ok]
            n += np.bincount(idx, minlength=gw * gh)
            sm += np.bincount(idx, weights=v, minlength=gw * gh)
            s2 += np.bincount(idx, weights=v * v, minlength=gw * gh)
    with np.errstate(all="ignore"):
        mean = sm / n
        sd = np.sqrt(np.maximum(s2 / n - mean**2, 0))
    cov = n / npix_cell
    mean[cov < min_cov] = np.nan
    sh = (gh, gw)
    return mean.reshape(sh), sd.reshape(sh), cov.reshape(sh), (r0, r1, c0, c1)


def read_window(path, win, fill=np.nan):
    r0, r1, c0, c1 = win
    with rasterio.open(path) as s:
        a = s.read(1, window=Window(c0, r0, c1 - c0, r1 - r0), masked=True)
    return np.ma.filled(a.astype(float), fill)


def highpass(d, cells):
    """d minus its moving average over a (2*cells+1) window, ignoring NaN (box via cumulative sums)."""
    v = np.isfinite(d)
    z = np.where(v, d, 0.0)

    def box(a):
        k = 2 * cells + 1
        c = np.pad(a, ((1, 0), (0, 0))).cumsum(0)
        a = c[k:] - c[:-k]
        a = np.pad(a, ((cells, cells), (0, 0)))
        c = np.pad(a, ((0, 0), (1, 0))).cumsum(1)
        return np.pad(c[:, k:] - c[:, :-k], ((0, 0), (cells, cells)))

    s, n = box(z), box(v.astype(float))
    with np.errstate(all="ignore"):
        m = s / n
    m[n < 0.3 * (2 * cells + 1) ** 2] = np.nan
    return d - m


def poly_detrend(d, xy, order=2):
    v = np.isfinite(d)
    x, y = xy[:, 0] / 1e4, xy[:, 1] / 1e4
    cols = [x**i * y**j for i in range(order + 1) for j in range(order + 1 - i)]
    A = np.stack(cols, 1)
    coef = np.linalg.lstsq(A[v], d[v], rcond=None)[0]
    return d - A @ coef


def pair_diffs(e, xy, max_lag, seed, max_pts):
    ok = np.isfinite(e)
    e, xy = e[ok], xy[ok]
    if len(e) > max_pts:
        i = np.random.default_rng(seed).choice(len(e), max_pts, replace=False)
        e, xy = e[i], xy[i]
    p = cKDTree(xy).query_pairs(max_lag, output_type="ndarray")
    dist = np.hypot(*(xy[p[:, 0]] - xy[p[:, 1]]).T)
    return dist, e[p[:, 0]] - e[p[:, 1]]


def expo(h, nug, sill, rng):
    return nug + sill * (1 - np.exp(-h / rng))


def semivariogram(dist, de):
    rows = []
    for lo, hi in zip(LAGS[:-1], LAGS[1:]):
        m = (dist >= lo) & (dist < hi)
        if m.sum() > 200:
            rows.append((float(dist[m].mean()), float(0.5 * np.mean(de[m] ** 2)), int(m.sum())))
    out = dict(bins=[dict(lag_m=a, gamma_m2=b, pairs=c) for a, b, c in rows])
    if len(rows) >= 5:
        h, g = np.array([r[0] for r in rows]), np.array([r[1] for r in rows])
        try:
            (nug, sill, rng), _ = curve_fit(expo, h, g, p0=[g[0], g.max() - g[0], 1000.0],
                                            bounds=([0, 0, 30], [np.inf, np.inf, 50000]))
            out["fit"] = dict(model="exponential (practical range = 3 x range_param)", nugget_m2=float(nug),
                              partial_sill_m2=float(sill), range_param_m=float(rng),
                              practical_range_m=float(3 * rng), total_sill_m2=float(nug + sill))
        except Exception as ex:  # noqa: BLE001
            out["fit_error"] = str(ex)
    return out


def relative(e, xy, seed, max_pts, lidar_h=None):
    dist, de = pair_diffs(e, xy, LAGS[-1], seed, max_pts)
    out = dict(baselines={}, semivariogram=semivariogram(dist, de))
    for b in BASELINES:
        m = (dist >= 0.85 * b) & (dist <= 1.15 * b)
        if m.sum() > 200:
            d = de[m]
            out["baselines"][str(b)] = dict(pairs=int(m.sum()), rms_dh_m=float(np.sqrt(np.mean(d**2))),
                                            nmad_dh_m=nmad(d), slope_err_rms_m_per_km=float(np.sqrt(np.mean(d**2)) / b * 1000))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run")
    ap.add_argument("lidar")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lidar-year", type=int)
    ap.add_argument("--datum", default="unknown")
    ap.add_argument("--min-coverage", type=float, default=0.8)
    ap.add_argument("--max-lidar-sd", type=float, default=1.5, help="drop cells whose lidar std within the cell exceeds this (canals, edges)")
    ap.add_argument("--water-class", type=int, default=80)
    ap.add_argument("--max-points", type=int, default=12000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    grid = f"{a.run}/dem_utm.tif"

    L, Lsd, cov, win = aggregate(a.lidar, grid, min_cov=a.min_coverage)
    Lsd_ok = Lsd <= a.max_lidar_sd
    S = {k: read_window(f"{a.run}/{k}.tif", win) for k in SURFACES}
    lc = read_window(f"{a.run}/landcover.tif", win)
    chm = read_window(f"{a.run}/canopy_height.tif", win)
    exc = read_window(f"{a.run}/excluded_mask.tif", win, fill=1) > 0
    with rasterio.open(grid) as g:
        t = g.transform
        r0, r1, c0, c1 = win
        cc, rr = np.meshgrid(np.arange(c0, c1) + 0.5, np.arange(r0, r1) + 0.5)
        X, Y = t * (cc, rr)
    res = t.a

    valid = np.isfinite(L) & Lsd_ok & ~exc & (lc != a.water_class)
    for k in S:
        valid &= np.isfinite(S[k])
    report = dict(lidar=a.lidar, lidar_year=a.lidar_year, lidar_vertical_datum=a.datum, run=a.run,
                  grid_res_m=res, alignment="2 m lidar pixels binned into run-grid cells by pixel centre",
                  min_coverage=a.min_coverage, max_lidar_sd_m=a.max_lidar_sd, n_valid_cells=int(valid.sum()),
                  area_km2=float(valid.sum() * res**2 / 1e6))
    xy = np.c_[X.ravel(), Y.ravel()]

    # absolute and detrended error
    report["absolute"], report["detrended"], report["relative"] = {}, {}, {}
    for k in SURFACES:
        d = np.where(valid, S[k] - L, np.nan)
        ab = dict(overall=stats(d.ravel()), by_landcover={}, by_canopy={})
        for c in np.unique(lc[valid]):
            s = stats(d[(lc == c) & valid]); ab["by_landcover"][str(int(c))] = s
        for lo, hi in [(0, 2), (2, 10), (10, 20), (20, 100)]:
            ab["by_canopy"][f"{lo}-{hi}"] = stats(d[(chm >= lo) & (chm < hi) & valid])
        report["absolute"][k] = ab
        dm = d - np.nanmedian(d)  # constant datum offset removed
        det_poly = poly_detrend(dm.ravel(), xy).reshape(d.shape)
        det_hp = highpass(dm, int(round(2000 / res)))
        report["detrended"][k] = dict(median_removed=stats(dm.ravel()), poly2_removed=stats(det_poly.ravel()),
                                      moving_2km_mean_removed=stats(det_hp.ravel()))
        report["relative"][k] = relative(dm.ravel(), xy, a.seed, a.max_points)
        print(k, "median-removed", report["detrended"][k]["median_removed"])
    # the signal: true lidar height differences over the same baselines
    report["lidar_signal"] = relative(np.where(valid, L, np.nan).ravel(), xy, a.seed, a.max_points)["baselines"]

    # three-way table at ground points
    gp = gpd.read_file(f"{a.run}/ground_points.gpkg")
    gp = gp[gp["exclude_reason"].fillna("") == ""].copy()
    ci = np.floor((gp.x.values - t.c) / res).astype(int) - c0
    ri = np.floor((t.f - gp.y.values) / res).astype(int) - r0
    ok = (ri >= 0) & (ri < L.shape[0]) & (ci >= 0) & (ci < L.shape[1])
    gp = gp[ok].copy(); ri, ci = ri[ok], ci[ok]
    gp["lidar"] = L[ri, ci]; gp["lidar_sd"] = Lsd[ri, ci]
    gp = gp[np.isfinite(gp.lidar) & (gp.lidar_sd <= a.max_lidar_sd)]
    gp["dem_m_lidar"] = gp.dem - gp.lidar; gp["dem_m_ground"] = gp.dem - gp.H; gp["ground_m_lidar"] = gp.H - gp.lidar
    gp["geoid_n"] = gp.h_ell - gp.H
    tw = dict(n=int(len(gp)), geoid_n=stats(gp.geoid_n.values), by_landcover={}, by_canopy={})
    cols = ["dem_m_lidar", "dem_m_ground", "ground_m_lidar"]
    for c, q in gp.groupby("lc"):
        if len(q) >= 30:
            tw["by_landcover"][str(int(c))] = {k: stats(q[k].values) for k in cols}
    for lo, hi in [(0, 2), (2, 10), (10, 20), (20, 100)]:
        q = gp[(gp.chm >= lo) & (gp.chm < hi)]
        if len(q) >= 30:
            tw["by_canopy"][f"{lo}-{hi}"] = {k: stats(q[k].values) for k in cols}
    tw["overall"] = {k: stats(gp[k].values) for k in cols}
    q = gp[(gp.lc == 10) & (gp.chm < 2)]
    if len(q) > 50:
        tw["ground_m_lidar_vs_geoid_n_slope"] = float(np.polyfit(q.geoid_n, q.ground_m_lidar, 1)[0])
    gp["year"] = gpd.pd.to_datetime(gp.time).dt.year
    tw["ground_m_lidar_by_year"] = {int(y): float(v) for y, v in gp.groupby("year").ground_m_lidar.median().items()}
    report["three_way_points"] = tw

    with rasterio.open(grid) as g:
        prof = dict(driver="GTiff", dtype="float32", count=4, width=L.shape[1], height=L.shape[0], crs=g.crs,
                    transform=rasterio.Affine(res, 0, t.c + c0 * res, 0, -res, t.f - r0 * res), nodata=np.nan,
                    compress="deflate")
    with rasterio.open(f"{a.out}/lidar_on_grid.tif", "w", **prof) as o:
        for i, (arr, name) in enumerate([(L, "lidar_mean"), (Lsd, "lidar_sd"), (cov, "coverage"),
                                         (np.where(valid, S["dtm_smooth"] - L, np.nan), "smooth_minus_lidar")], 1):
            o.write(arr.astype("float32"), i); o.set_band_description(i, name)
    with open(f"{a.out}/lidar_compare.json", "w") as f:
        json.dump(report, f, indent=1)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
