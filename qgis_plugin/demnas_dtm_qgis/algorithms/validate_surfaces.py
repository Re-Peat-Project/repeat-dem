import os

from qgis.core import (QgsProcessingOutputFile, QgsProcessingOutputFolder, QgsProcessingParameterEnum,
                       QgsProcessingParameterFeatureSource, QgsProcessingParameterField,
                       QgsProcessingParameterMultipleLayers)

from ..core.grid import crs_to_wkt
from .base import DemnasAlgorithm
from .compat import FIELD_ANY, FIELD_NUMERIC, SRC_POINT, SRC_RASTER
from .qgis_io import raster_path, source_to_frame

SUBSETS = ["validation", "calibration", "all"]


class ValidateSurfaces(DemnasAlgorithm):
    NEEDS = ("numpy", "pandas", "pyproj", "osgeo")
    OUTPUT_FILES = ('validation.csv', 'ground_points_errors.gpkg')
    NAME = "validate"
    TITLE = "4. Validate surfaces against ground points"
    HELP = (
        "Samples any number of elevation rasters at the ground points and reports bias, RMSE, MAE and "
        "NMAD (m) for all points and per land cover class.\n\n"
        "Use ground_points.gpkg from algorithm 2 and select the held-out points ('validation'). Add the "
        "rasters you want to compare: dtm_smooth, dtm_corrected, dtm_prior_k, the raw DEM, and also "
        "FABDEM, Copernicus GLO-30, or an airborne lidar DTM (same vertical datum as the points!). "
        "Rasters may be in any CRS and resolution; values are read at the nearest cell.\n\n"
        "Outputs: validation.csv, and ground_points_errors.gpkg with the sampled value and error "
        "(surface - ground) of every raster at every point."
    )

    def define(self):
        self.basic(QgsProcessingParameterFeatureSource("POINTS", "Ground points (ground_points.gpkg from algorithm 2)", [SRC_POINT]))
        self.basic(QgsProcessingParameterMultipleLayers("SURFACES", "Surfaces to validate (raster layers)", layerType=SRC_RASTER))
        self.basic(QgsProcessingParameterEnum("SUBSET", "Points to use", SUBSETS, defaultValue=0))
        self.out_dir_param()
        self.advanced(QgsProcessingParameterField("H_FIELD", "Ground height field (m, same datum as the surfaces)",
                                                  parentLayerParameterName="POINTS", type=FIELD_NUMERIC, defaultValue="H"))
        self.advanced(QgsProcessingParameterField("SPLIT_FIELD", "Split field", parentLayerParameterName="POINTS",
                                                  type=FIELD_ANY, optional=True, defaultValue="split"))
        self.advanced(QgsProcessingParameterField("LC_FIELD", "Land cover class field (for the per-class table)",
                                                  parentLayerParameterName="POINTS", type=FIELD_NUMERIC, optional=True,
                                                  defaultValue="lc"))
        self.addOutput(QgsProcessingOutputFolder("OUT_DIR", "Output folder"))
        self.addOutput(QgsProcessingOutputFile("OUT_TABLE", "validation.csv"))

    def do_run(self, parameters, context, feedback):
        from ..core.validate import safe_name, validate
        from ..core.vecio import write_points_gpkg
        out = self.out_dir(parameters, context, feedback)
        src = self.parameterAsSource(parameters, "POINTS", context)
        df, lon, lat = source_to_frame(src, context)
        surfaces = {}
        for lyr in self.parameterAsLayerList(parameters, "SURFACES", context):
            name, i = safe_name(lyr.name()), 2
            while name in surfaces:
                name, i = f"{safe_name(lyr.name())}_{i}", i + 1
            surfaces[name] = raster_path(lyr)
        feedback.setProgress(10)
        tab, df = validate(df, lon, lat, surfaces,
                           self.parameterAsString(parameters, "H_FIELD", context),
                           self.parameterAsString(parameters, "SPLIT_FIELD", context) or None,
                           SUBSETS[self.parameterAsEnum(parameters, "SUBSET", context)],
                           self.parameterAsString(parameters, "LC_FIELD", context) or None)
        p = lambda n: os.path.join(out, n)
        tab.to_csv(p("validation.csv"), index=False)
        write_points_gpkg(p("ground_points_errors.gpkg"), df, lon, lat, crs_to_wkt("EPSG:4326"),
                          "ground_points_errors")
        for _, r in tab[tab["class"] == "all"].iterrows():
            feedback.pushInfo(f"{r['surface']:<18} n={int(r['n']):5d}  bias={r['bias_m']:6.2f}  "
                              f"RMSE={r['rmse_m']:6.2f}  NMAD={r['nmad_m']:5.2f}  (m)")
        self.load(context, p("ground_points_errors.gpkg"), "Ground points with errors")
        feedback.setProgress(100)
        return {"OUT_DIR": out, "OUT_TABLE": p("validation.csv")}
