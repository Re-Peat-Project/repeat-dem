"""How much did the old demnas_dtm.load_dem crop shift the DEM? Old crop vs the fixed one, both against exact interpolation.

    python script/check_load_alignment.py [--out runs/checks/load_alignment_check.csv]

Until 2026-10-25, load_dem cropped the mosaic with rasterio.merge(bounds=AOI bounds). Those bounds were not aligned to the
source grid, so merge re-sampled the mosaic by a fraction of a cell (nearest), and the bilinear reprojection to UTM then
resampled it again. The fix snaps the bounds outward to whole source cells. This script runs both versions as the code
does (each builds its own UTM grid from its mosaic) for one GLO-30 tile over KHG Mendahara - Batanghari at 30 m, and compares
each with the exact bilinear interpolation of the source tile at every target cell centre at least one cell inside the tile.
"""
import argparse
import math
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.merge import merge
from rasterio.transform import from_origin
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds

REPO = Path(__file__).resolve().parents[1]
TILE = "dem/open/glo30/Copernicus_DSM_COG_10_S02_00_E103_00_DEM.tif"
KHG = "KHG Sungai Mendahara - Sungai Batanghari"
RES = 30.0


def load(src, bounds, crs):
    """As demnas_dtm.load_dem: merge with the given bounds, then a target grid from calculate_default_transform of that
    mosaic at RES, then bilinear reprojection. Returns the array and its transform."""
    mosaic, mt = merge([src], bounds=bounds, nodata=-99999.0, dtype="float32")
    dem = mosaic[0].astype("float32")
    dem[dem == -99999.0] = np.nan
    h, w = dem.shape
    left, top = mt.c, mt.f
    t, tw, th = calculate_default_transform(src.crs, crs, w, h, left, top + h * mt.e, left + w * mt.a, top, resolution=RES)
    gt = from_origin(t.c, t.f, RES, RES)
    out = np.full((th, tw), np.nan, "float32")
    reproject(dem, out, src_transform=mt, src_crs=src.crs, src_nodata=np.nan, dst_transform=gt, dst_crs=crs,
              dst_nodata=np.nan, resampling=Resampling.bilinear)
    return out, gt


def exact_bilinear(S, st, src_crs, gt, shape, crs):
    rr, cc = np.indices(shape)
    x, y = gt * (cc + 0.5, rr + 0.5)
    lon, lat = Transformer.from_crs(crs, src_crs, always_xy=True).transform(x, y)
    fc = (lon - st.c) / st.a - 0.5
    fr = (lat - st.f) / st.e - 0.5
    ok = (fc >= 1) & (fr >= 1) & (fc < S.shape[1] - 2) & (fr < S.shape[0] - 2)   # one cell clear of the tile edge
    c0, r0 = np.floor(fc[ok]).astype(int), np.floor(fr[ok]).astype(int)
    wx, wy = fc[ok] - c0, fr[ok] - r0
    return ok, S[r0, c0] * (1 - wx) * (1 - wy) + S[r0, c0 + 1] * wx * (1 - wy) + S[r0 + 1, c0] * (1 - wx) * wy + S[r0 + 1, c0 + 1] * wx * wy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "runs" / "checks" / "load_alignment_check.csv"))
    a = ap.parse_args()
    data = Path(os.environ.get("REPEAT_DATA") or REPO.parent / "_data")
    g = gpd.read_file(data / "batas_khg_indonesia.gpkg", layer="nama__khg__indonesia__2017__rev_tipologi")
    sel = g[g.NAMA_KHG == KHG]
    aoi = sel.to_crs(sel.estimate_utm_crs()).buffer(500).to_crs(4326).union_all()   # the benchmark AOI: KHG + aoi_buffer_m 500
    crs = rasterio.crs.CRS.from_epsg(32748)
    with rasterio.open(data / TILE) as src:
        old_b = transform_bounds("EPSG:4326", src.crs, *aoi.bounds)
        st = src.transform
        new_b = (st.c + math.floor((old_b[0] - st.c) / st.a) * st.a, st.f + math.ceil((old_b[1] - st.f) / st.e) * st.e,
                 st.c + math.ceil((old_b[2] - st.c) / st.a) * st.a, st.f + math.floor((old_b[3] - st.f) / st.e) * st.e)
        S = src.read(1).astype("float64")
        rows = []
        for k, bnd in (("old_crop", old_b), ("fixed_crop", new_b)):
            v, gt = load(src, bnd, crs)
            ok, exact = exact_bilinear(S, st, src.crs, gt, v.shape, crs)
            d = v[ok] - exact
            d = d[np.isfinite(d)]
            rows.append({"loader": k, "grid_origin": f"{gt.c:.2f},{gt.f:.2f}", "cells": int(d.size), "median_m": round(float(np.median(d)), 4),
                         "nmad_m": round(float(1.4826 * np.median(np.abs(d - np.median(d)))), 4), "max_abs_m": round(float(np.abs(d).max()), 3)})
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    print(pd.DataFrame(rows).to_string(index=False))
    print("wrote", out)


if __name__ == "__main__":
    main()
