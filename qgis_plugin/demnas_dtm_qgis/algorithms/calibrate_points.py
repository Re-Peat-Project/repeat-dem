import os

from qgis.core import (QgsProcessingException, QgsProcessingOutputFile, QgsProcessingOutputFolder,
                       QgsProcessingParameterBoolean, QgsProcessingParameterEnum,
                       QgsProcessingParameterFeatureSource, QgsProcessingParameterField,
                       QgsProcessingParameterMatrix, QgsProcessingParameterNumber,
                       QgsProcessingParameterRasterLayer, QgsProcessingParameterString)

from ..core import config as cfgmod
from ..core.grid import Grid, load_aligned, open_raster
from .base import DemnasAlgorithm, is_set, sibling
from .compat import FIELD_ANY, FIELD_NUMERIC, NUM_DOUBLE, NUM_INT, SRC_POINT
from .qgis_io import raster_path, source_to_frame

DATUM_MODES = ["pyproj", "raster", "constant", "none"]
G = cfgmod.DEFAULTS["ground"]


class CalibratePoints(DemnasAlgorithm):
    NEEDS = ("numpy", "scipy", "pandas", "pyproj", "osgeo")
    OUTPUT_FILES = ('ground_points.gpkg', 'calibration.json', 'datum_diagnostics.json')
    NAME = "calibrate"
    TITLE = "2. Calibrate against ground points (fit k and bias)"
    HELP = (
        "Takes ground heights (ICESat-2/GEDI points from algorithm 5, RTK survey points, or any point "
        "layer), converts them to the DEM's vertical datum, samples the DEM, canopy height and land "
        "cover at each point, drops unusable points, splits the rest into calibration and validation "
        "by 2 km spatial blocks and fits  DEM - ground = bias + k[class] x canopy height.\n\n"
        "Writes ground_points.gpkg (every point with its exclude_reason and split), calibration.json "
        "(feeds algorithm 3) and datum_diagnostics.json. Read the diagnostics: a median offset shared "
        "by all classes points to the datum, offsets that differ by class point to the DEM or the points.\n\n"
        "The rasters must share one grid (use the outputs of algorithm 1). The point heights must be in "
        "the same epoch as the DEM unless you set the DEM year and subsidence rates."
    )

    def define(self):
        self.basic(QgsProcessingParameterFeatureSource("POINTS", "Ground points", [SRC_POINT]))
        self.basic(QgsProcessingParameterField("H_FIELD", "Ground height field (m)", parentLayerParameterName="POINTS",
                                               type=FIELD_NUMERIC, defaultValue="h_ell"))
        self.basic(QgsProcessingParameterBoolean("ELLIPSOIDAL", "Heights are ellipsoidal (ICESat-2/GEDI are)", defaultValue=True))
        self.basic(QgsProcessingParameterRasterLayer("DEM", "DEM (from algorithm 1)"))
        self.basic(QgsProcessingParameterRasterLayer("LANDCOVER", "Land cover (WorldCover codes)", optional=True))
        self.basic(QgsProcessingParameterRasterLayer("CHM", "Canopy height (m)", optional=True))
        self.basic(QgsProcessingParameterRasterLayer("VMASK", "Vector mask raster (empty = vector_mask.tif next to the DEM, if any)", optional=True))
        self.out_dir_param()

        self.advanced(QgsProcessingParameterField("TIME_FIELD", "Time field (needed for the epoch shift)", parentLayerParameterName="POINTS",
                                                  type=FIELD_ANY, optional=True, defaultValue="time"))
        self.advanced(QgsProcessingParameterField("SOURCE_FIELD", "Source/dataset field", parentLayerParameterName="POINTS",
                                                  type=FIELD_ANY, optional=True, defaultValue="source"))
        d, e = G["datum"], G["epoch"]
        self.advanced(QgsProcessingParameterEnum("DATUM_MODE", "Datum conversion (ellipsoidal -> DEM datum)", DATUM_MODES, defaultValue=0))
        self.advanced(QgsProcessingParameterString("DATUM_TARGET", "Target vertical CRS (mode pyproj)", defaultValue=d["target"]))
        self.advanced(QgsProcessingParameterRasterLayer("GEOID", "Geoid undulation raster, N in m (mode raster)", optional=True))
        self.advanced(QgsProcessingParameterNumber("GEOID_CONST", "Constant geoid offset, m (mode constant)", type=NUM_DOUBLE,
                                                   defaultValue=d["constant_m"]))
        self.advanced(QgsProcessingParameterNumber("DEM_YEAR", "DEM acquisition year (empty = no subsidence shift)", type=NUM_INT,
                                                   optional=True, defaultValue=None))
        self.advanced(QgsProcessingParameterNumber("SUBS_DEFAULT", "Subsidence rate, default (m/yr)", type=NUM_DOUBLE,
                                                   defaultValue=e["subsidence_default_m_per_yr"]))
        self.advanced(QgsProcessingParameterMatrix("SUBS_TABLE", "Subsidence rate by land cover class (m/yr)",
                                                   headers=["Class", "m/yr"], numberRows=1, hasFixedNumberRows=False,
                                                   defaultValue=[], optional=True))
        x, s, f, dg = G["exclude"], G["split"], G["fit"], G["diagnostics"]
        self.advanced(QgsProcessingParameterString("EXCL_CLASSES", "Drop points in land cover classes (comma list)",
                                                   defaultValue=cfgmod.format_class_list(x["landcover_classes"])))
        self.advanced(QgsProcessingParameterNumber("EDGE_BUFFER", "Drop points within this distance of a land cover change (m)",
                                                   type=NUM_DOUBLE, defaultValue=x["edge_buffer_m"], minValue=0))
        self.advanced(QgsProcessingParameterBoolean("USE_VMASK", "Drop points inside the vector mask", defaultValue=x["use_vector_masks"]))
        self.advanced(QgsProcessingParameterNumber("MAX_RESID", "Drop points further than this from the DEM (m)", type=NUM_DOUBLE,
                                                   defaultValue=x["max_abs_residual_m"], minValue=0))
        self.advanced(QgsProcessingParameterNumber("VAL_FRACTION", "Validation fraction (of spatial blocks)", type=NUM_DOUBLE,
                                                   defaultValue=s["validation_fraction"], minValue=0, maxValue=0.9))
        self.advanced(QgsProcessingParameterNumber("BLOCK_SIZE", "Spatial block size (m)", type=NUM_DOUBLE,
                                                   defaultValue=s["block_size_m"], minValue=1))
        self.advanced(QgsProcessingParameterNumber("SEED", "Split random seed", type=NUM_INT, defaultValue=s["seed"]))
        self.advanced(QgsProcessingParameterNumber("MIN_POINTS", "Minimum points per class to fit k", type=NUM_INT,
                                                   defaultValue=f["min_points_per_class"], minValue=1))
        self.advanced(QgsProcessingParameterNumber("BIAS_CHM_BELOW", "Points with canopy below this (m) define the bias",
                                                   type=NUM_DOUBLE, defaultValue=f["bias_from_chm_below_m"], minValue=0))
        self.advanced(QgsProcessingParameterBoolean("BIAS_PER_CLASS", "Fit a bias per class", defaultValue=f["fit_bias_per_class"]))
        self.advanced(QgsProcessingParameterBoolean("JOINT_INTERCEPT", "Joint intercept per class (use when offsets differ by class)",
                                                    defaultValue=f["joint_intercept"]))
        self.advanced(QgsProcessingParameterNumber("K_MIN", "k lower bound", type=NUM_DOUBLE, defaultValue=f["k_bounds"][0]))
        self.advanced(QgsProcessingParameterNumber("K_MAX", "k upper bound", type=NUM_DOUBLE, defaultValue=f["k_bounds"][1]))
        self.advanced(QgsProcessingParameterNumber("HUBER", "Huber threshold (m)", type=NUM_DOUBLE, defaultValue=f["huber_m"], minValue=0.01))
        self.advanced(QgsProcessingParameterNumber("WARN_MEDIAN", "Warn when |median DEM - ground| exceeds (m)", type=NUM_DOUBLE,
                                                   defaultValue=dg["warn_median_m"]))
        self.advanced(QgsProcessingParameterNumber("WARN_SPREAD", "Warn when low-canopy offsets differ between classes by (m)",
                                                   type=NUM_DOUBLE, defaultValue=dg["warn_class_spread_m"]))
        self.advanced(QgsProcessingParameterMatrix("K_TABLE", "Prior k by land cover class (kept where too few points)",
                                                   headers=["Class", "k"], numberRows=len(cfgmod.DEFAULTS["k_by_class"]),
                                                   hasFixedNumberRows=False,
                                                   defaultValue=cfgmod.table_to_matrix(cfgmod.DEFAULTS["k_by_class"])))
        self.advanced(QgsProcessingParameterNumber("K_DEFAULT", "Prior k for other classes", type=NUM_DOUBLE,
                                                   defaultValue=cfgmod.DEFAULTS["k_default"]))
        self.config_param()

        self.addOutput(QgsProcessingOutputFolder("OUT_DIR", "Output folder"))
        self.addOutput(QgsProcessingOutputFile("OUT_CALIBRATION", "calibration.json"))
        self.addOutput(QgsProcessingOutputFile("OUT_POINTS", "ground_points.gpkg"))

    def do_run(self, parameters, context, feedback):
        import pandas as pd
        from ..core import calibrate as cal
        from ..core.vecio import write_points_gpkg
        cfg, y = self.base_cfg(parameters, context)
        P = lambda *a: self.put(cfg, y, *a)
        g = cfg["ground"]
        P(("ground", "datum", "mode"), DATUM_MODES[self.parameterAsEnum(parameters, "DATUM_MODE", context)])
        P(("ground", "datum", "target"), self.parameterAsString(parameters, "DATUM_TARGET", context))
        P(("ground", "datum", "constant_m"), self.parameterAsDouble(parameters, "GEOID_CONST", context))
        geoid = self.parameterAsRasterLayer(parameters, "GEOID", context)
        if geoid:
            g["datum"]["raster_path"] = raster_path(geoid)
        if is_set(parameters, "DEM_YEAR"):
            g["epoch"]["dem_year"] = self.parameterAsInt(parameters, "DEM_YEAR", context)
        P(("ground", "epoch", "subsidence_default_m_per_yr"), self.parameterAsDouble(parameters, "SUBS_DEFAULT", context))
        subs = cfgmod.matrix_to_table(self.parameterAsMatrix(parameters, "SUBS_TABLE", context))
        if subs or not y:
            g["epoch"]["subsidence_m_per_yr_by_class"] = subs
        P(("ground", "exclude", "landcover_classes"),
          cfgmod.parse_class_list(self.parameterAsString(parameters, "EXCL_CLASSES", context)))
        P(("ground", "exclude", "edge_buffer_m"), self.parameterAsDouble(parameters, "EDGE_BUFFER", context))
        P(("ground", "exclude", "use_vector_masks"), self.parameterAsBoolean(parameters, "USE_VMASK", context))
        P(("ground", "exclude", "max_abs_residual_m"), self.parameterAsDouble(parameters, "MAX_RESID", context))
        P(("ground", "split", "validation_fraction"), self.parameterAsDouble(parameters, "VAL_FRACTION", context))
        P(("ground", "split", "block_size_m"), self.parameterAsDouble(parameters, "BLOCK_SIZE", context))
        P(("ground", "split", "seed"), self.parameterAsInt(parameters, "SEED", context))
        P(("ground", "fit", "min_points_per_class"), self.parameterAsInt(parameters, "MIN_POINTS", context))
        P(("ground", "fit", "bias_from_chm_below_m"), self.parameterAsDouble(parameters, "BIAS_CHM_BELOW", context))
        P(("ground", "fit", "fit_bias_per_class"), self.parameterAsBoolean(parameters, "BIAS_PER_CLASS", context))
        P(("ground", "fit", "joint_intercept"), self.parameterAsBoolean(parameters, "JOINT_INTERCEPT", context))
        P(("ground", "fit", "k_bounds"), [self.parameterAsDouble(parameters, "K_MIN", context),
                                          self.parameterAsDouble(parameters, "K_MAX", context)])
        P(("ground", "fit", "huber_m"), self.parameterAsDouble(parameters, "HUBER", context))
        P(("ground", "diagnostics", "warn_median_m"), self.parameterAsDouble(parameters, "WARN_MEDIAN", context))
        P(("ground", "diagnostics", "warn_class_spread_m"), self.parameterAsDouble(parameters, "WARN_SPREAD", context))
        P(("k_by_class",), cfgmod.matrix_to_table(self.parameterAsMatrix(parameters, "K_TABLE", context)))
        P(("k_default",), self.parameterAsDouble(parameters, "K_DEFAULT", context))

        out = self.out_dir(parameters, context, feedback)
        dem_path = raster_path(self.parameterAsRasterLayer(parameters, "DEM", context))
        grid = Grid.from_dataset(open_raster(dem_path))
        dem = load_aligned(dem_path, grid)
        arrs = {}
        for key in ("LANDCOVER", "CHM", "VMASK"):
            lyr = self.parameterAsRasterLayer(parameters, key, context)
            arrs[key] = load_aligned(raster_path(lyr), grid, "nearest" if key != "CHM" else "average") if lyr else None
        if arrs["VMASK"] is None:
            sib = sibling(dem_path, "vector_mask.tif")
            if sib:
                feedback.pushInfo(f"using {sib} as the vector mask (found next to the DEM)")
                arrs["VMASK"] = load_aligned(sib, grid, "nearest")
        lc, chm, vm = arrs["LANDCOVER"], arrs["CHM"], arrs["VMASK"]
        if lc is not None:
            lc[lc == 0] = float("nan")
        if vm is not None:
            vm = vm == 1

        # ground points -> [lon, lat, h_ell, source, time]
        src = self.parameterAsSource(parameters, "POINTS", context)
        df, lon, lat = source_to_frame(src, context)
        hf = self.parameterAsString(parameters, "H_FIELD", context)
        tf = self.parameterAsString(parameters, "TIME_FIELD", context)
        sf = self.parameterAsString(parameters, "SOURCE_FIELD", context)
        if hf not in df.columns:
            raise QgsProcessingException(f"height field {hf!r} not found")
        pts = pd.DataFrame({"lon": lon, "lat": lat, "h_ell": pd.to_numeric(df[hf], errors="coerce").to_numpy(),
                            "source": df[sf].astype(str).to_numpy() if sf in df.columns else "local",
                            "time": df[tf].astype(str).to_numpy() if tf in df.columns else "",
                            "track": ""})
        pts.attrs["already_orthometric"] = not self.parameterAsBoolean(parameters, "ELLIPSOIDAL", context)
        feedback.pushInfo(f"{len(pts)} ground points read")
        feedback.setProgress(20)

        calib, table, diag = cal.calibrate(pts, grid, dem, lc, chm, vm, cfg)
        feedback.setProgress(80)

        p = lambda n: os.path.join(out, n)
        write_points_gpkg(p("ground_points.gpkg"), table, table["x"].to_numpy(), table["y"].to_numpy(),
                          grid.crs_wkt, "ground_points")
        cfgmod.dump_json(p("datum_diagnostics.json"), diag)
        results = {"OUT_DIR": out, "OUT_POINTS": p("ground_points.gpkg")}
        if calib:
            cfgmod.dump_json(p("calibration.json"), calib)
            results["OUT_CALIBRATION"] = p("calibration.json")
        else:
            feedback.pushWarning("no calibration could be fitted (too few usable points): "
                                 "algorithm 3 will keep the prior k values")
        self.load(context, p("ground_points.gpkg"), "Ground points")
        feedback.setProgress(100)
        return results
