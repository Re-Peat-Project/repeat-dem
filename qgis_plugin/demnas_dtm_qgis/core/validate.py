"""Stage 4: error statistics of any set of surfaces at ground points."""
from __future__ import annotations

import logging
import re

import numpy as np
import pandas as pd

from . import ground_truth as gt
from .grid import crs_to_wkt, sample_nearest

log = logging.getLogger("demnas_dtm")


def safe_name(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]+", "_", name).strip("_") or "surface"


def validate(df: pd.DataFrame, lon, lat, surfaces: dict, h_col: str, split_col: str | None,
             which: str, lc_col: str | None):
    """surfaces: {name: raster path}. which: 'validation' | 'calibration' | 'all'.
    Returns (table, df with err_<name> columns)."""
    df = df.copy()
    H = df[h_col].to_numpy(dtype="float64")
    wkt = crs_to_wkt("EPSG:4326")
    for name, path in surfaces.items():
        v, _ = sample_nearest(path, np.asarray(lon, dtype="float64"), np.asarray(lat, dtype="float64"), wkt)
        df["z_" + name] = v
        df["err_" + name] = v - H
    sel = np.isfinite(H)
    if "exclude_reason" in df.columns:
        sel &= (df["exclude_reason"].fillna("") == "").to_numpy()
    if which != "all":
        if not split_col or split_col not in df.columns:
            raise ValueError(f"the points have no '{split_col}' field; choose 'all points' instead")
        sel &= (df[split_col] == which).to_numpy()
    if not sel.any():
        raise RuntimeError(f"no points to validate against (selection: {which})")
    log.info("validating on %d of %d points (%s)", int(sel.sum()), len(df), which)
    lc = (df[lc_col].to_numpy(dtype="float64") if lc_col and lc_col in df.columns
          else np.full(len(df), np.nan))
    tab = gt.error_table(H[sel], {n: df["z_" + n].to_numpy()[sel] for n in surfaces}, lc[sel],
                         gt.WORLDCOVER_NAMES)
    for _, r in tab[tab["class"] == "all"].iterrows():
        log.info("  validation %-15s n=%5d bias=%6.2f  RMSE=%6.2f  NMAD=%5.2f",
                 r["surface"], r["n"], r["bias_m"], r["rmse_m"], r["nmad_m"])
    return tab, df
