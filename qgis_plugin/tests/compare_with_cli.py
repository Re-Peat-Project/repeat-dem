"""Regression test: run the QGIS algorithms on a finished CLI run and compare with that run's files.

Run it with QGIS's Python (OSGeo4W Shell, or the python of a conda env that has qgis):

    python tests/compare_with_cli.py [runs/exp_base]

The run folder must hold dem_utm.tif, landcover.tif, canopy_height.tif, ground_points_raw.gpkg,
calibration.json, validation.csv and the CLI's dtm_*.tif. runs/exp_base (8 m, calibrated) does.
Needs network once (PROJ fetches the EGM2008 geoid grid for the datum step).
Algorithm 1 is compared in 'local' mode only, using the run's own land cover and canopy rasters.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
from osgeo import gdal

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
REF = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "runs" / "exp_base"
SAMPLE_DEM = REPO / "_data_sample" / "DEMNAS_sebangau.tif"
AOI = REPO / "runs" / "aoi_window.gpkg"

from qgis.core import QgsApplication  # noqa: E402

app = QgsApplication([], False)
app.initQgis()
import processing  # noqa: E402
from processing.core.Processing import Processing  # noqa: E402

Processing.initialize()
import demnas_dtm_qgis  # noqa: E402

PLUGIN = demnas_dtm_qgis.classFactory(None)  # keep a reference or the provider is garbage-collected
PLUGIN.initProcessing()
OUT = Path(tempfile.mkdtemp(prefix="demnas_cmp_"))
fails = []


def rd(p):
    ds = gdal.Open(str(p))
    b = ds.GetRasterBand(1)
    a = b.ReadAsArray().astype("float64")
    nd = b.GetNoDataValue()
    if nd is not None and not np.isnan(nd):
        a[a == nd] = np.nan
    return a


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def cmp_raster(name, ref, new, tol=1e-4, allow_footprint_diff=0):
    a, b = rd(ref), rd(new)
    if a.shape != b.shape:
        return check(name, False, f"shape {a.shape} vs {b.shape}")
    fa, fb = np.isfinite(a), np.isfinite(b)
    d = np.abs(a - b)[fa & fb]
    foot = int((fa != fb).sum())
    check(name, (d.max() if d.size else 0) <= tol and foot <= allow_footprint_diff,
          f"max|d|={d.max() if d.size else 0:.3g}  footprint cells differing={foot}")


# ---- 3. correct and smooth (reference inputs + the run's calibration.json) -------------
dem = rd(REF / "dem_utm.tif")
ds = gdal.Open(str(REF / "dem_utm.tif"))
aoi = OUT / "aoi_from_dem.tif"
m = gdal.GetDriverByName("GTiff").Create(str(aoi), ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Byte)
m.SetGeoTransform(ds.GetGeoTransform())
m.SetProjection(ds.GetProjection())
m.GetRasterBand(1).WriteArray(np.isfinite(dem).astype("uint8"))
m = None
o3 = OUT / "a3"
processing.run("demnas_dtm:correct_smooth", {
    "DEM": str(REF / "dem_utm.tif"), "LANDCOVER": str(REF / "landcover.tif"), "CHM": str(REF / "canopy_height.tif"),
    "AOI_MASK": str(aoi), "CALIBRATION": str(REF / "calibration.json"), "OUT_DIR": str(o3)})
for f in ("dtm_corrected", "dtm_residual", "correction_m", "k_factor", "excluded_mask"):
    cmp_raster("alg3 " + f, REF / (f + ".tif"), o3 / (f + ".tif"))
# the test's AOI mask is the DEM footprint, so interior DEM holes (gap-filled in the run) differ
cmp_raster("alg3 dtm_smooth", REF / "dtm_smooth.tif", o3 / "dtm_smooth.tif", allow_footprint_diff=2000)

# ---- 2. calibrate on the run's cached ground points ----------------------------------------
o2 = OUT / "a2"
processing.run("demnas_dtm:calibrate", {
    "POINTS": str(REF / "ground_points_raw.gpkg"), "H_FIELD": "h_ell", "ELLIPSOIDAL": True,
    "DEM": str(REF / "dem_utm.tif"), "LANDCOVER": str(REF / "landcover.tif"), "CHM": str(REF / "canopy_height.tif"),
    "OUT_DIR": str(o2)})
a = json.loads((REF / "calibration.json").read_text())
b = json.loads((o2 / "calibration.json").read_text())
ok = (a["n_points"] == b["n_points"] and a["n_validation"] == b["n_validation"]
      and abs(a["bias_global"]["value"] - b["bias_global"]["value"]) < 1e-9
      and all(abs(a["classes"][c]["k"] - b["classes"][c]["k"]) < 1e-9 for c in a["classes"]))
check("alg2 calibration.json", ok, f"n={b['n_points']} bias={b['bias_global']['value']:.4f}")

# ---- 4. validate (the run's own surfaces + the placeholder-k surface from alg 3) -------------
o4 = OUT / "a4"
processing.run("demnas_dtm:validate", {
    "POINTS": str(o2 / "ground_points.gpkg"), "SUBSET": 0, "OUT_DIR": str(o4),
    "SURFACES": [str(REF / "dem_utm.tif"), str(o3 / "dtm_prior_k.tif"), str(o3 / "dtm_corrected.tif"), str(o3 / "dtm_smooth.tif")]})
import pandas as pd  # noqa: E402

A = pd.read_csv(REF / "validation.csv")
B = pd.read_csv(o4 / "validation.csv")
A, B = A[A["class"].astype(str) == "all"], B[B["class"].astype(str) == "all"]
diff = np.abs(A[["n", "bias_m", "rmse_m", "mae_m", "nmad_m"]].to_numpy() - B[["n", "bias_m", "rmse_m", "mae_m", "nmad_m"]].to_numpy()).max()
check("alg4 validation.csv", diff < 1e-6, f"max diff {diff:.2g} over 4 surfaces")

# ---- 1. prepare inputs in local mode ---------------------------------------------------------
if SAMPLE_DEM.exists() and AOI.exists() and REF.name == "exp_base":
    o1 = OUT / "a1"
    processing.run("demnas_dtm:prepare_inputs", {
        "DEM": [str(SAMPLE_DEM)], "AOI": str(AOI), "RES": 8, "MODE": 1,
        "LANDCOVER": str(REF / "landcover.tif"), "CHM": str(REF / "canopy_height.tif"), "OUT_DIR": str(o1)})
    for f in ("dem_utm", "landcover", "canopy_height"):
        cmp_raster("alg1 " + f, REF / (f + ".tif"), o1 / (f + ".tif"))
else:
    print("SKIP alg1 (needs _data_sample/DEMNAS_sebangau.tif, runs/aoi_window.gpkg and runs/exp_base)")

app.exitQgis()
shutil.rmtree(OUT, ignore_errors=True)
print("\n" + ("ALL PASSED" if not fails else f"FAILED: {fails}"))
sys.exit(1 if fails else 0)
