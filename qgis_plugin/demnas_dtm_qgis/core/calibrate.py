"""Stage 2: ground points -> datum, sampling, exclusions, block split, k/bias fit
(mirrors demnas_dtm.ground_calibration; the maths stays in ground_truth.py)."""
from __future__ import annotations

import copy
import logging

import numpy as np
import pandas as pd

from . import ground_truth as gt
from .grid import Grid, crs_to_wkt, sample_nearest

log = logging.getLogger("demnas_dtm")


def to_grid_xy(lon, lat, grid: Grid):
    import pyproj
    tr = pyproj.Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    x, y = tr.transform(np.asarray(lon, dtype="float64"), np.asarray(lat, dtype="float64"))
    return np.asarray(x), np.asarray(y)


def to_dem_datum(df: pd.DataFrame, g: dict, lc_at_points):
    """gt.to_dem_datum, with the geoid-raster mode done through GDAL instead of rasterio."""
    d = g["datum"]
    if d["mode"] == "raster" and not df.attrs.get("already_orthometric"):
        if not d.get("raster_path"):
            raise ValueError("datum mode 'raster' needs a geoid undulation raster")
        N, _ = sample_nearest(d["raster_path"], df["lon"].to_numpy(), df["lat"].to_numpy(),
                              crs_to_wkt("EPSG:4326"))
        tmp = df.copy()
        tmp.attrs = dict(df.attrs)
        tmp["h_ell"] = df["h_ell"].to_numpy(dtype="float64") - N
        g2 = copy.deepcopy(g)
        g2["datum"]["mode"] = "none"
        out = gt.to_dem_datum(tmp, g2, lc_at_points)
        out["h_ell"] = df["h_ell"].to_numpy()
        return out
    return gt.to_dem_datum(df, g, lc_at_points)


def calibrate(pts: pd.DataFrame, grid: Grid, dem, lc, chm, vm, cfg: dict):
    """pts: DataFrame [lon, lat, h_ell, (source, time)], attrs['already_orthometric'] optional.
    Returns (calib or None, df, diag). df holds every point with exclude_reason and split."""
    g = cfg["ground"]
    if len(pts) == 0:
        raise RuntimeError("the ground points layer is empty")
    x, y = to_grid_xy(pts["lon"], pts["lat"], grid)
    em = gt.edge_mask(lc, float(g["exclude"]["edge_buffer_m"]), grid.res)
    s = gt.sample_arrays(x, y, grid, {"dem": dem, "chm": chm, "lc": lc,
                                      "edge": None if em is None else em.astype("float32"),
                                      "vmask": None if vm is None else vm.astype("float32")})
    pts = to_dem_datum(pts, g, s["lc"])
    df = pts.copy()
    df["x"], df["y"] = x, y
    for k_ in ("dem", "chm", "lc", "edge", "vmask"):
        df[k_] = s[k_]
    df["chm"] = df["chm"].fillna(0.0)

    reason = np.full(len(df), "", dtype=object)
    reason[~s["inside"]] = "outside grid"
    reason[(reason == "") & ~np.isfinite(df["dem"].to_numpy())] = "no DEM"
    reason[(reason == "") & ~np.isfinite(df["H"].to_numpy())] = "no height"
    if lc is not None:
        reason[(reason == "") & df["lc"].isin([int(c) for c in g["exclude"]["landcover_classes"]]).to_numpy()] = "excluded class"
    reason[(reason == "") & (df["edge"].to_numpy() == 1)] = "near land-cover edge"
    if g["exclude"]["use_vector_masks"]:
        reason[(reason == "") & (df["vmask"].to_numpy() == 1)] = "inside vector mask"
    gross = np.abs(df["dem"].to_numpy() - df["H"].to_numpy()) > float(g["exclude"]["max_abs_residual_m"])
    reason[(reason == "") & gross] = "gross outlier"
    df["exclude_reason"] = reason
    use = reason == ""
    log.info("ground points usable: %d of %d", int(use.sum()), len(df))
    log.info("exclusions: %s", df.loc[~use, "exclude_reason"].value_counts().to_dict())
    diag = gt.datum_diagnostics(df, g["diagnostics"], float(g["fit"]["bias_from_chm_below_m"]))

    df["split"] = ""
    if use.any():
        val = gt.spatial_split(df["x"].to_numpy()[use], df["y"].to_numpy()[use], g["split"])
        df.loc[use, "split"] = np.where(val, "validation", "calibration")
    cal = df[df["split"] == "calibration"]
    if len(cal) < int(g["fit"]["min_points_per_class"]):
        log.warning("too few calibration points (%d); prior k values kept", len(cal))
        calib = None
    else:
        log.info("fitting k and bias on %d calibration points", len(cal))
        calib = gt.fit_k_bias(cal, cfg["k_by_class"], cfg["k_default"], g["fit"])
        calib["n_validation"] = int((df["split"] == "validation").sum())
    return calib, df, diag
