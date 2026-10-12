import json
import os
import time

import numpy as np
from qgis.core import (QgsProcessingOutputFile, QgsProcessingOutputFolder, QgsProcessingOutputRasterLayer,
                       QgsProcessingParameterBoolean, QgsProcessingParameterEnum, QgsProcessingParameterFile,
                       QgsProcessingParameterMatrix, QgsProcessingParameterNumber,
                       QgsProcessingParameterRasterLayer, QgsProcessingParameterString)

from ..core import config as cfgmod
from ..core.grid import Grid, load_aligned, open_raster, write_raster
from .base import DemnasAlgorithm, sibling
from .compat import FILE_BEHAVIOR_FILE, NUM_DOUBLE, NUM_INT
from .qgis_io import raster_path

COMPRESS = ["deflate", "lzw", "none"]
D = cfgmod.DEFAULTS


class CorrectSmooth(DemnasAlgorithm):
    NEEDS = ("numpy", "scipy", "pyproj", "osgeo")
    OUTPUT_FILES = ('dtm_smooth.tif', 'dtm_corrected.tif', 'run_report.json')
    NAME = "correct_smooth"
    TITLE = "3. Correct and smooth (DEM to dome-scale ground surface)"
    HELP = (
        "Applies  DTM = DEM - k[land cover] x canopy height - bias[land cover], masks water, built-up "
        "land and vector masks, removes spikes, smooths and fills gaps.\n\n"
        "k and bias come from the tables below, or from calibration.json (algorithm 2), which overrides "
        "them class by class. Without a calibration the placeholder k values are used and the report says so. "
        "Those placeholders are not supported by data (fitted k at the test sites was 0.04 to 0.21).\n\n"
        "Smoothing steps run in order, written as  method:value ; method:value :\n"
        "  median:300        large-window robust median (window in m)\n"
        "  gaussian:150      NaN-aware gaussian (sigma in m)\n"
        "  polynomial:3      robust trend surface (degree), optional keys: sample=, huber_m=\n"
        "Example for one dome:  polynomial:4; gaussian:100\n\n"
        "Outputs: dtm_smooth.tif (the result), dtm_corrected.tif (unsmoothed), dtm_prior_k.tif "
        "(placeholder-k surface, so algorithm 4 can compare), dtm_residual.tif, run_report.json. "
        "Treat dtm_smooth.tif as good for dome shape and regional slope, not for decimetre heights."
    )

    def define(self):
        self.basic(QgsProcessingParameterRasterLayer("DEM", "DEM (from algorithm 1)"))
        self.basic(QgsProcessingParameterRasterLayer("LANDCOVER", "Land cover", optional=True))
        self.basic(QgsProcessingParameterRasterLayer("CHM", "Canopy height", optional=True))
        self.basic(QgsProcessingParameterRasterLayer("VMASK", "Vector mask raster (empty = vector_mask.tif next to the DEM, if any)", optional=True))
        self.basic(QgsProcessingParameterRasterLayer("AOI_MASK", "AOI mask raster (empty = aoi_mask.tif next to the DEM, if any)", optional=True))
        self.basic(QgsProcessingParameterFile("CALIBRATION", "calibration.json from algorithm 2 (optional)",
                                              behavior=FILE_BEHAVIOR_FILE, extension="json", optional=True))
        self.basic(QgsProcessingParameterString("SMOOTHING", "Smoothing steps", defaultValue=cfgmod.format_steps(D["smoothing"]["steps"])))
        self.out_dir_param()

        self.advanced(QgsProcessingParameterMatrix("K_TABLE", "Placeholder k by land cover class", headers=["Class", "k"],
                                                   numberRows=len(D["k_by_class"]), hasFixedNumberRows=False,
                                                   defaultValue=cfgmod.table_to_matrix(D["k_by_class"])))
        self.advanced(QgsProcessingParameterNumber("K_DEFAULT", "k for other classes", type=NUM_DOUBLE, defaultValue=D["k_default"]))
        self.advanced(QgsProcessingParameterMatrix("BIAS_TABLE", "Constant offset by class (m)", headers=["Class", "bias m"],
                                                   numberRows=1, hasFixedNumberRows=False, defaultValue=[], optional=True))
        self.advanced(QgsProcessingParameterNumber("BIAS_DEFAULT", "Offset for other classes (m)", type=NUM_DOUBLE,
                                                   defaultValue=D["bias_default"]))
        m, s = D["mask"], D["smoothing"]
        self.advanced(QgsProcessingParameterString("MASK_CLASSES", "Land cover classes kept out of the smoothing (comma list)",
                                                   defaultValue=cfgmod.format_class_list(m["landcover_classes"]), optional=True))
        self.advanced(QgsProcessingParameterBoolean("DESPIKE", "Remove spikes", defaultValue=m["despike"]))
        self.advanced(QgsProcessingParameterNumber("DESPIKE_WINDOW", "Spike reference window (m)", type=NUM_DOUBLE,
                                                   defaultValue=m["despike_window_m"], minValue=1))
        self.advanced(QgsProcessingParameterNumber("DESPIKE_THRESHOLD", "Spike threshold (m)", type=NUM_DOUBLE,
                                                   defaultValue=m["despike_threshold_m"], minValue=0))
        self.advanced(QgsProcessingParameterNumber("FILL_PX", "Gap filling: maximum search distance (pixels)", type=NUM_INT,
                                                   defaultValue=s["fill_max_search_px"], minValue=0))
        self.advanced(QgsProcessingParameterBoolean("INTERMEDIATES", "Also write corrected DTM, correction, k and exclusion rasters",
                                                    defaultValue=D["outputs"]["write_intermediates"]))
        self.advanced(QgsProcessingParameterEnum("COMPRESS", "GeoTIFF compression", COMPRESS, defaultValue=0))
        self.config_param()

        self.addOutput(QgsProcessingOutputFolder("OUT_DIR", "Output folder"))
        self.addOutput(QgsProcessingOutputRasterLayer("OUT_SMOOTH", "dtm_smooth"))
        self.addOutput(QgsProcessingOutputFile("OUT_REPORT", "run_report.json"))

    def do_run(self, parameters, context, feedback):
        from ..core.correct import correct_and_smooth, stats
        t_start = time.time()
        cfg, y = self.base_cfg(parameters, context)
        P = lambda *a: self.put(cfg, y, *a)
        steps = cfgmod.parse_steps(self.parameterAsString(parameters, "SMOOTHING", context))
        if not steps:
            raise ValueError("no smoothing steps given")
        P(("smoothing", "steps"), steps)
        P(("k_by_class",), cfgmod.matrix_to_table(self.parameterAsMatrix(parameters, "K_TABLE", context)))
        P(("k_default",), self.parameterAsDouble(parameters, "K_DEFAULT", context))
        bt = cfgmod.matrix_to_table(self.parameterAsMatrix(parameters, "BIAS_TABLE", context))
        if bt or not y:
            cfg["bias_by_class"] = bt
        P(("bias_default",), self.parameterAsDouble(parameters, "BIAS_DEFAULT", context))
        P(("mask", "landcover_classes"), cfgmod.parse_class_list(self.parameterAsString(parameters, "MASK_CLASSES", context)))
        P(("mask", "despike"), self.parameterAsBoolean(parameters, "DESPIKE", context))
        P(("mask", "despike_window_m"), self.parameterAsDouble(parameters, "DESPIKE_WINDOW", context))
        P(("mask", "despike_threshold_m"), self.parameterAsDouble(parameters, "DESPIKE_THRESHOLD", context))
        P(("smoothing", "fill_max_search_px"), self.parameterAsInt(parameters, "FILL_PX", context))
        P(("outputs", "write_intermediates"), self.parameterAsBoolean(parameters, "INTERMEDIATES", context))
        compress = COMPRESS[self.parameterAsEnum(parameters, "COMPRESS", context)]

        out = self.out_dir(parameters, context, feedback)
        dem_path = raster_path(self.parameterAsRasterLayer(parameters, "DEM", context))
        grid = Grid.from_dataset(open_raster(dem_path))
        dem = load_aligned(dem_path, grid)
        got = {}
        for key, rs in (("LANDCOVER", "nearest"), ("CHM", "average"), ("VMASK", "nearest"), ("AOI_MASK", "nearest")):
            lyr = self.parameterAsRasterLayer(parameters, key, context)
            got[key] = load_aligned(raster_path(lyr), grid, rs) if lyr else None
        used = {}
        for key, fn in (("VMASK", "vector_mask.tif"), ("AOI_MASK", "aoi_mask.tif")):
            lyr = self.parameterAsRasterLayer(parameters, key, context)
            if lyr is not None:
                used[key] = raster_path(lyr)
                continue
            sib = sibling(dem_path, fn)
            used[key] = sib
            if sib:
                feedback.pushInfo(f"using {sib} (found next to the DEM)")
                got[key] = load_aligned(sib, grid, "nearest")
        if used["VMASK"] is None:
            feedback.pushWarning("no vector mask: canals/settlements are not kept out of the smoothing")
        if used["AOI_MASK"] is None:
            feedback.pushWarning("no AOI mask: the surface is gap-filled beyond the AOI edge")
        lc, chm = got["LANDCOVER"], got["CHM"]
        vm = None if got["VMASK"] is None else got["VMASK"] == 1
        aoi = None if got["AOI_MASK"] is None else got["AOI_MASK"] == 1
        if chm is not None:
            chm = np.nan_to_num(chm, nan=0.0)

        calib = None
        cpath = self.parameterAsFile(parameters, "CALIBRATION", context)
        if cpath:
            with open(cpath, "r", encoding="utf-8") as f:
                calib = json.load(f)
            feedback.pushInfo(f"calibration loaded from {cpath}")
        else:
            feedback.pushWarning("no calibration: k and bias are the placeholder values (not supported by data)")
        feedback.setProgress(15)

        r = correct_and_smooth(dem, grid, lc, chm, vm, aoi, cfg, calib, feedback)
        feedback.setProgress(85)

        p = lambda n: os.path.join(out, n)
        smoothed, dtm = r["smoothed"], r["dtm"]
        write_raster(p("dtm_smooth.tif"), smoothed, grid, compress=compress)
        write_raster(p("dtm_residual.tif"), r["residual"], grid, compress=compress)
        write_raster(p("dtm_prior_k.tif"), r["dtm_prior"], grid, compress=compress)
        write_raster(p("dtm_corrected.tif"), dtm, grid, compress=compress)
        if cfg["outputs"]["write_intermediates"]:
            write_raster(p("correction_m.tif"), np.where(np.isfinite(dem), r["correction"], np.nan), grid, compress=compress)
            write_raster(p("k_factor.tif"), r["k"], grid, compress=compress)
            write_raster(p("excluded_mask.tif"), (r["excl"] | r["spikes"]).astype("uint8"), grid, "uint8", 255, compress)

        report = {
            "created": time.strftime("%Y-%m-%d %H:%M:%S"), "runtime_s": round(time.time() - t_start, 1),
            "grid": {"crs": grid.crs_wkt, "res_m": grid.res, "width": grid.width, "height": grid.height, "bounds": grid.bounds},
            "excluded_share": float((r["excl"] | r["spikes"]).mean()), "spike_share": float(r["spikes"].mean()),
            "stats": {"dem": stats(dem), "correction_m": stats(np.where(np.isfinite(dem), r["correction"], np.nan)),
                      "dtm_smooth": stats(smoothed), "residual": stats(r["residual"])},
            "masks_used": used, "calibration": calib, "k_used": {k: float(v) for k, v in r["k_table"].items()},
            "bias_used": {k: float(v) for k, v in r["b_table"].items()}, "bias_default_used": float(r["b_def"]),
            "config": cfg,
            "note": ("k and bias fitted from ground points" if calib else
                     "k and bias are uncalibrated placeholders (no ground calibration applied)"),
        }
        cfgmod.dump_json(p("run_report.json"), report)
        self.load(context, p("dtm_smooth.tif"), "DTM smoothed")
        feedback.pushInfo(f"done in {time.time() - t_start:.1f} s")
        feedback.setProgress(100)
        return {"OUT_DIR": out, "OUT_SMOOTH": p("dtm_smooth.tif"), "OUT_REPORT": p("run_report.json")}
