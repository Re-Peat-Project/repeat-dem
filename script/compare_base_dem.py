"""Compare Copernicus GLO-30 and FABDEM with DEMNAS against the cached ICESat-2/GEDI ground points of a run.

For the usable points of a run's ground_points.gpkg it samples GLO-30 (EGM2008 heights, 1 degree
COG tiles from the open AWS bucket) and FABDEM v1.2 (same grid, Hugging Face mirror; check its licence:
non-commercial), downloaded once into --cache, optionally smooths them like the
DEMNAS chain (median about 300 m, then gaussian about 150 m), and reports:
  - median DEM - ground by land-cover class and by canopy height;
  - RMS and NMAD of the error difference between point pairs, by distance (the relative error).
No calibration is applied to GLO-30, FABDEM or the raw DEMNAS column.

  python script/compare_base_dem.py runs/exp_joint runs/mendahara_30m --cache runs/glo30
"""
import argparse
import math
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from scipy import ndimage
from scipy.spatial import cKDTree

URL = "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM/Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM.tif"
FAB_URL = "https://huggingface.co/buckets/links-ads/fabdem/resolve/tiles/{block}_FABDEM_V1-2/{tile}_FABDEM_V1-2.tif"
BINS = [(0, 150), (300, 600), (1000, 2000), (4000, 8000)]


def _hemi(v: int, ns: bool) -> str:
    return ("N" if v >= 0 else "S") if ns else ("E" if v >= 0 else "W")


def tile_path(lon: float, lat: float, cache: Path, source: str = "glo30") -> Path:
    la, lo = math.floor(lat), math.floor(lon)
    ns, ew = _hemi(la, True), _hemi(lo, False)
    path = cache / f"{source}_{ns}{abs(la):02d}_{ew}{abs(lo):03d}.tif"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        if source == "glo30":
            url = URL.format(ns=ns, lat=abs(la), ew=ew, lon=abs(lo))
        else:
            la0, lo0 = (la // 10) * 10, (lo // 10) * 10
            block = (f"{_hemi(la0, True)}{abs(la0):02d}{_hemi(lo0, False)}{abs(lo0):03d}-"
                     f"{_hemi(la0 + 10, True)}{abs(la0 + 10):02d}{_hemi(lo0 + 10, False)}{abs(lo0 + 10):03d}")
            url = FAB_URL.format(block=block, tile=f"{ns}{abs(la):02d}{ew}{abs(lo):03d}")
        urllib.request.urlretrieve(url, path)
    return path


def sample_dem(lon, lat, cache: Path, smooth: bool, source: str = "glo30"):
    out = np.full(len(lon), np.nan)
    keys = {(math.floor(x), math.floor(y)) for x, y in zip(lon, lat)}
    for lo, la in keys:
        m = (np.floor(lon) == lo) & (np.floor(lat) == la)
        try:
            with rasterio.open(tile_path(lo + 0.5, la + 0.5, cache, source)) as r:
                a = r.read(1).astype(float)
                bad = (a <= -9000) | ~np.isfinite(a)
                if bad.any() and not bad.all():
                    idx = ndimage.distance_transform_edt(bad, return_distances=False, return_indices=True)
                    a = a[tuple(idx)]
                if smooth:
                    a = ndimage.gaussian_filter(ndimage.median_filter(a, size=11, mode="nearest"), sigma=5, mode="nearest")
                rows, cols = rasterio.transform.rowcol(r.transform, lon[m], lat[m])
                out[m] = a[np.clip(rows, 0, a.shape[0] - 1), np.clip(cols, 0, a.shape[1] - 1)]
        except Exception as e:  # tile missing over sea
            print(f"  {source} tile {lo},{la} unavailable: {e}")
    return out


sample_glo30 = lambda lon, lat, cache, smooth: sample_dem(lon, lat, cache, smooth, "glo30")  # noqa: E731


def pair_row(e, xy, max_points=9000, seed=0):
    ok = np.isfinite(e)
    e, xy = e[ok], xy[ok]
    if len(e) > max_points:
        i = np.random.default_rng(seed).choice(len(e), max_points, replace=False)
        e, xy = e[i], xy[i]
    e = e - np.median(e)
    p = cKDTree(xy).query_pairs(BINS[-1][1], output_type="ndarray")
    d = np.hypot(*(xy[p[:, 0]] - xy[p[:, 1]]).T)
    de = e[p[:, 0]] - e[p[:, 1]]
    cells = []
    for lo, hi in BINS:
        m = (d >= lo) & (d < hi)
        cells.append(f"{lo}-{hi} m {np.sqrt(np.mean(de[m]**2)):.2f}/{1.4826*np.median(np.abs(de[m]-np.median(de[m]))):.2f}")
    return f"sd {e.std():.2f} | " + " | ".join(cells)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--cache", default="runs/glo30")
    a = ap.parse_args()
    cache = Path(a.cache)
    for run in a.runs:
        g = gpd.read_file(f"{run}/ground_points.gpkg")
        g = g[g["exclude_reason"].fillna("") == ""].copy()
        lon, lat = g["lon"].to_numpy(float), g["lat"].to_numpy(float)
        for src, tag in (("glo30", "glo"), ("fabdem", "fab")):
            g[f"{tag}_raw"] = sample_dem(lon, lat, cache, False, src)
            g[f"{tag}_sm"] = sample_dem(lon, lat, cache, True, src)
        xy = np.c_[g["x"].to_numpy(float), g["y"].to_numpy(float)]
        print(f"\n{run}: {len(g)} usable points; pair columns are RMS/NMAD of error difference (m)")
        rows = (("DEMNAS raw", "dem"), ("GLO-30 raw", "glo_raw"), ("GLO-30 smoothed", "glo_sm"),
                ("FABDEM raw", "fab_raw"), ("FABDEM smoothed", "fab_sm"))
        for name, col in rows:
            print(f"  {name:<18} {pair_row((g[col] - g['H']).to_numpy(float), xy)}")
        print(f"  {'DEMNAS calib+smooth':<18} {pair_row(g['err_dtm_smooth'].to_numpy(float), xy)}")
        for nm, mask in (("canopy < 2 m", g["chm"] < 2), ("canopy >= 2 m", g["chm"] >= 2)):
            d = g[mask]
            if len(d):
                print(f"  median DEM - ground, {nm} (n={len(d)}): DEMNAS {np.nanmedian(d['dem']-d['H']):+.2f} m, "
                      f"GLO-30 {np.nanmedian(d['glo_raw']-d['H']):+.2f} m, FABDEM {np.nanmedian(d['fab_raw']-d['H']):+.2f} m")
        names = {10: "tree cover", 20: "shrubland", 30: "grassland", 40: "cropland", 90: "wetland", 95: "mangrove"}
        print("  by land cover: n, median DEM - ground (m) / NMAD of the error (m) for DEMNAS, GLO-30, FABDEM")
        for lc, d in g.groupby("lc"):
            if len(d) < 30:
                continue
            cells = []
            for lab, col in (("DEMNAS", "dem"), ("GLO-30", "glo_raw"), ("FABDEM", "fab_raw")):
                e = (d[col] - d["H"]).to_numpy(float)
                e = e[np.isfinite(e)]
                cells.append(f"{lab} {np.median(e):+.2f}/{1.4826*np.median(np.abs(e-np.median(e))):.2f}")
            print(f"    {names.get(int(lc), int(lc))} (n={len(d)}): " + " | ".join(cells))
        # relative error by land-cover group after removing each class's median offset (a light calibration)
        groups = {"all classes": np.ones(len(g), bool),
                  "non-forest (shrub, grass, crop, wetland)": g["lc"].isin([20, 30, 40, 90]).to_numpy(),
                  "tree cover": (g["lc"] == 10).to_numpy(), "mangrove": (g["lc"] == 95).to_numpy()}
        print("  relative error by group, class offsets removed (RMS/NMAD in m; DEMNAS = raw, GLO-30 and FABDEM smoothed):")
        for gname, m in groups.items():
            if m.sum() < 200:
                continue
            for name, col in (("DEMNAS raw", "dem"), ("GLO-30 smoothed", "glo_sm"), ("FABDEM smoothed", "fab_sm")):
                e = (g[col] - g["H"]).to_numpy(float).copy()
                for lc in np.unique(g["lc"][m]):
                    k = m & (g["lc"] == lc).to_numpy()
                    e[k] -= np.nanmedian(e[k])
                print(f"    {gname[:26]:<26} {name:<16} {pair_row(e[m], xy[m])}")

