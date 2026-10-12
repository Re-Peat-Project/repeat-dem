"""Masking and smoothing. The math is the same as demnas_dtm.py; only the raster calls differ
(rasterio.fill / rasterio.warp are replaced by the GDAL calls they wrap)."""
from __future__ import annotations

import logging
import math
import time
import warnings

import numpy as np
from osgeo import gdal
from scipy import ndimage

from .grid import Grid, mem_dataset

log = logging.getLogger("demnas_dtm")


def fillnodata(arr: np.ndarray, valid: np.ndarray, max_search_distance: float,
               smoothing_iterations: int = 0) -> np.ndarray:
    """GDALFillNodata (what rasterio.fill.fillnodata calls). `valid` != 0 marks known cells."""
    h, w = arr.shape
    g = Grid("", 0.0, float(h), 1.0, w, h)
    ds = mem_dataset(arr.astype("float32"), g)
    mk = mem_dataset(valid.astype("uint8"), g)
    gdal.FillNodata(ds.GetRasterBand(1), mk.GetRasterBand(1), float(max_search_distance),
                    int(smoothing_iterations))
    return ds.GetRasterBand(1).ReadAsArray().astype("float32")


def class_lookup(lc, table: dict, default: float, shape) -> np.ndarray:
    out = np.full(shape, float(default), dtype="float32")
    if lc is None:
        return out
    for k, v in table.items():
        out[lc == int(k)] = float(v)
    return out


def nan_gaussian(z: np.ndarray, sigma_px: float) -> np.ndarray:
    valid = np.isfinite(z)
    num = ndimage.gaussian_filter(np.where(valid, z, 0.0).astype("float64"), sigma_px, mode="nearest")
    den = ndimage.gaussian_filter(valid.astype("float64"), sigma_px, mode="nearest")
    out = np.where(den > 0.05, num / np.maximum(den, 1e-12), np.nan)
    return out.astype("float32")


def coarse_median(z: np.ndarray, grid: Grid, window_m: float) -> np.ndarray:
    """Robust large-window median: block-median to a coarse grid, 3x3 median, bilinear back."""
    cell_m = max(grid.res, window_m / 3.0)
    f = max(1, int(round(cell_m / grid.res)))
    h, w = z.shape
    H, W = math.ceil(h / f), math.ceil(w / f)
    pad = np.full((H * f, W * f), np.nan, dtype="float32")
    pad[:h, :w] = z
    blocks = pad.reshape(H, f, W, f).transpose(0, 2, 1, 3).reshape(H, W, f * f)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        coarse = np.nanmedian(blocks, axis=2).astype("float32")
    cmask = np.isfinite(coarse)
    if cmask.any() and (~cmask).any():
        coarse = fillnodata(coarse, cmask, 50)
    coarse = ndimage.median_filter(np.nan_to_num(coarse, nan=np.nanmean(coarse)), size=3, mode="nearest")
    coarse[~np.isfinite(coarse)] = np.nan
    cgrid = Grid(grid.crs_wkt, grid.left, grid.top, grid.res * f, W, H)
    src = mem_dataset(coarse.astype("float32"), cgrid, nodata=float("nan"))
    dst = mem_dataset(np.full(z.shape, np.nan, dtype="float32"), grid, nodata=float("nan"))
    gdal.Warp(dst, src, options=gdal.WarpOptions(resampleAlg="bilinear", srcNodata=float("nan"),
                                                dstNodata=float("nan")))
    return dst.GetRasterBand(1).ReadAsArray().astype("float32")


def poly_trend(z: np.ndarray, degree: int = 3, sample: int = 200_000, huber_m: float = 1.0,
               iters: int = 6, seed: int = 0) -> np.ndarray:
    """Robust polynomial trend surface (IRLS with Huber weights): dome-scale ground form."""
    h, w = z.shape
    rows, cols = np.nonzero(np.isfinite(z))
    if rows.size < 50:
        raise ValueError("too few valid cells for polynomial trend")
    rng = np.random.default_rng(seed)
    if rows.size > sample:
        sel = rng.choice(rows.size, sample, replace=False)
        rows, cols = rows[sel], cols[sel]
    x = cols / max(w - 1, 1) * 2 - 1
    y = rows / max(h - 1, 1) * 2 - 1
    terms = [(i, j) for i in range(degree + 1) for j in range(degree + 1 - i)]
    A = np.stack([x ** i * y ** j for i, j in terms], axis=1)
    b = z[rows, cols].astype("float64")
    wts = np.ones_like(b)
    coef = None
    for _ in range(iters):
        sw = np.sqrt(wts)
        coef, *_ = np.linalg.lstsq(A * sw[:, None], b * sw, rcond=None)
        r = np.abs(b - A @ coef)
        wts = np.where(r <= huber_m, 1.0, huber_m / np.maximum(r, 1e-9))
    out = np.empty((h, w), dtype="float32")
    xs = np.arange(w) / max(w - 1, 1) * 2 - 1
    for r0 in range(0, h, 512):
        r1 = min(h, r0 + 512)
        yy = (np.arange(r0, r1) / max(h - 1, 1) * 2 - 1)[:, None]
        acc = np.zeros((r1 - r0, w))
        for (i, j), c in zip(terms, coef):
            acc += c * (xs[None, :] ** i) * (yy ** j)
        out[r0:r1] = acc
    return out


def smooth(z: np.ndarray, grid: Grid, steps: list, feedback=None) -> np.ndarray:
    s = z.copy()
    for step in steps:
        if feedback is not None and feedback.isCanceled():
            raise RuntimeError("cancelled")
        m = step["method"]
        t0 = time.time()
        if m == "gaussian":
            s = nan_gaussian(s, float(step["sigma_m"]) / grid.res)
        elif m == "median":
            s = coarse_median(s, grid, float(step["window_m"]))
        elif m == "polynomial":
            s = poly_trend(s, int(step.get("degree", 3)), int(step.get("sample", 200_000)),
                           float(step.get("huber_m", 1.0)))
        else:
            raise ValueError(f"unknown smoothing method: {m}")
        log.info("smoothing step %s done (%.1f s)", m, time.time() - t0)
    return s


def fill_gaps(z: np.ndarray, max_px: int) -> np.ndarray:
    valid = np.isfinite(z)
    if valid.all() or not valid.any():
        return z
    filled = fillnodata(np.where(valid, z, 0).astype("float32"), valid, max_px, 0)
    filled[~valid & (filled == 0)] = np.nan
    return filled
