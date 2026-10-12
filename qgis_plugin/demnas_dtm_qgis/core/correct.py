"""Stage 3: vegetation correction, masking, despike, smoothing, gap fill (mirrors demnas_dtm.run)."""
from __future__ import annotations

import logging

import numpy as np

from .grid import Grid
from .smoothing import class_lookup, coarse_median, fill_gaps, smooth

log = logging.getLogger("demnas_dtm")


def tables_from_calibration(cfg: dict, calib: dict | None):
    """k table, bias table and default bias after applying a calibration result (run() semantics:
    classes missing from the calibration get the global bias)."""
    k_table, b_table = dict(cfg["k_by_class"]), dict(cfg["bias_by_class"])
    b_def = cfg["bias_default"]
    if calib:
        for cls, e in calib["classes"].items():
            k_table[cls] = e["k"]
            b_table[cls] = e["bias"]
        b_def = calib["bias_global"]["value"]
    return k_table, b_table, b_def


def correct_and_smooth(dem, grid: Grid, lc, chm, vm, aoi_mask, cfg: dict, calib: dict | None,
                       feedback=None):
    shape = dem.shape

    def correct(k_table, k_def, b_table, b_def):
        k_ = class_lookup(lc, k_table, k_def, shape)
        b_ = class_lookup(lc, b_table, b_def, shape)
        corr = (k_ * chm if chm is not None else 0.0) + b_
        return (dem - corr).astype("float32"), k_, corr

    dtm_prior, _, _ = correct(cfg["k_by_class"], cfg["k_default"], cfg["bias_by_class"], cfg["bias_default"])
    k_table, b_table, b_def = tables_from_calibration(cfg, calib)
    dtm, k, correction = correct(k_table, cfg["k_default"], b_table, b_def)

    excl = np.zeros(shape, dtype=bool)
    if lc is not None:
        for cls in cfg["mask"]["landcover_classes"]:
            excl |= lc == int(cls)
    if vm is not None:
        excl |= vm
    base = np.where(excl, np.nan, dtm)

    spikes = np.zeros(shape, dtype=bool)
    if cfg["mask"]["despike"]:
        ref = coarse_median(base, grid, float(cfg["mask"]["despike_window_m"]))
        spikes = np.isfinite(base) & (np.abs(base - ref) > float(cfg["mask"]["despike_threshold_m"]))
        base[spikes] = np.nan
        log.info("despike: removed %.2f%% of cells", 100 * spikes.mean())

    smoothed = smooth(base, grid, cfg["smoothing"]["steps"], feedback)
    smoothed = fill_gaps(smoothed, int(cfg["smoothing"]["fill_max_search_px"]))
    if aoi_mask is not None:
        smoothed[~aoi_mask] = np.nan
    residual = dtm - smoothed
    return {"dtm_prior": dtm_prior, "dtm": dtm, "k": k, "correction": correction,
            "smoothed": smoothed, "residual": residual, "excl": excl, "spikes": spikes,
            "k_table": k_table, "b_table": b_table, "b_def": b_def}


def stats(a):
    a = a[np.isfinite(a)]
    if a.size == 0:
        return None
    return {"min": float(a.min()), "p05": float(np.percentile(a, 5)), "median": float(np.median(a)),
            "p95": float(np.percentile(a, 95)), "max": float(a.max())}
