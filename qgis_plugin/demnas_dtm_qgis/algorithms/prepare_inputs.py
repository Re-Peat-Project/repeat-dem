import os

from qgis.core import (QgsProcessingOutputFolder, QgsProcessingOutputRasterLayer,
                       QgsProcessingParameterBoolean, QgsProcessingParameterCrs,
                       QgsProcessingParameterEnum, QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterMultipleLayers, QgsProcessingParameterNumber,
                       QgsProcessingParameterRasterLayer, QgsProcessingParameterString)

from ..core import config as cfgmod
from ..core import prepare
from ..core.grid import write_raster
from .base import DemnasAlgorithm
from .compat import NUM_DOUBLE, NUM_INT, SRC_ANY_VECTOR, SRC_POLYGON, SRC_RASTER
from .qgis_io import dissolved_wkt, layers_wkt, raster_path

MODES = ["download", "local", "none"]
COMPRESS = ["deflate", "lzw", "none"]


class PrepareInputs(DemnasAlgorithm):
    NEEDS = ("numpy", "pyproj", "osgeo")
    OUTPUT_FILES = ('dem_utm.tif', 'landcover.tif', 'canopy_height.tif', 'aoi_mask.tif', 'vector_mask.tif')
    NAME = "prepare_inputs"
    TITLE = "1. Prepare inputs (DEMNAS, land cover, canopy height)"
    HELP = (
        "Mosaics the DEMNAS tiles, clips them to the AOI (plus a buffer), reprojects to UTM and puts "
        "land cover and canopy height on the same grid.\n\n"
        "Land cover (ESA WorldCover) and canopy height (Meta/WRI) are read straight from public cloud "
        "COGs by window, or from your own rasters (mode 'local'). WorldCover class codes are expected.\n\n"
        "Results are written to the output folder: dem_utm.tif, landcover.tif, canopy_height.tif, "
        "aoi_mask.tif and (if you give canal/settlement layers) vector_mask.tif. They feed algorithms "
        "2 and 3.\n\n"
        "Needs a network connection for 'download' mode. Large AOIs at 8 m use a lot of memory; try "
        "30 m first."
    )

    def define(self):
        self.basic(QgsProcessingParameterMultipleLayers("DEM", "DEMNAS tiles (raster layers)", layerType=SRC_RASTER))
        self.basic(QgsProcessingParameterFeatureSource("AOI", "Area of interest (e.g. KHG polygon; empty = whole DEM)",
                                                       [SRC_POLYGON], optional=True))
        self.basic(QgsProcessingParameterNumber("RES", "Output resolution (m)", type=NUM_DOUBLE,
                                                defaultValue=cfgmod.DEFAULTS["target_res_m"], minValue=1))
        self.basic(QgsProcessingParameterCrs("CRS", "Target CRS (empty = UTM zone of the AOI)", optional=True))
        self.basic(QgsProcessingParameterEnum("MODE", "Correction layers", MODES, defaultValue=0))
        self.basic(QgsProcessingParameterRasterLayer("LANDCOVER", "Local land cover raster (mode 'local')", optional=True))
        self.basic(QgsProcessingParameterRasterLayer("CHM", "Local canopy height raster in m (mode 'local')", optional=True))
        self.basic(QgsProcessingParameterMultipleLayers(
            "MASK_VECTORS", "Vector layers to keep out of the smoothing (canals, settlements)",
            layerType=SRC_ANY_VECTOR, optional=True))
        self.basic(QgsProcessingParameterNumber("MASK_BUFFER", "Buffer around those vectors (m)", type=NUM_DOUBLE,
                                                defaultValue=15.0, minValue=0))
        self.out_dir_param()

        c = cfgmod.DEFAULTS["corrections"]
        self.advanced(QgsProcessingParameterNumber("AOI_BUFFER", "AOI buffer (m) so smoothing has context at the edge",
                                                   type=NUM_DOUBLE, defaultValue=cfgmod.DEFAULTS["aoi_buffer_m"], minValue=0))
        self.advanced(QgsProcessingParameterNumber("VALID_MIN", "Valid DEM range: minimum (m)", type=NUM_DOUBLE,
                                                   defaultValue=cfgmod.DEFAULTS["dem_valid_range_m"][0]))
        self.advanced(QgsProcessingParameterNumber("VALID_MAX", "Valid DEM range: maximum (m)", type=NUM_DOUBLE,
                                                   defaultValue=cfgmod.DEFAULTS["dem_valid_range_m"][1]))
        self.advanced(QgsProcessingParameterEnum("DEM_RESAMPLING", "DEM resampling", prepare.RESAMPLING, defaultValue=0))
        self.advanced(QgsProcessingParameterString("WORLDCOVER_URL", "WorldCover URL template ({tile})",
                                                   defaultValue=c["worldcover_url"]))
        self.advanced(QgsProcessingParameterString("CHM_URL", "Canopy height URL template ({quadkey})",
                                                   defaultValue=c["chm_url"]))
        self.advanced(QgsProcessingParameterNumber("CHM_ZOOM", "Canopy height quadkey zoom", type=NUM_INT,
                                                   defaultValue=c["chm_quadkey_zoom"], minValue=1))
        self.advanced(QgsProcessingParameterNumber("CHM_MIN", "Canopy below this is treated as 0 (m)", type=NUM_DOUBLE,
                                                   defaultValue=c["chm_min_m"], minValue=0))
        self.advanced(QgsProcessingParameterNumber("CHM_MAX", "Canopy height clipped at (m)", type=NUM_DOUBLE,
                                                   defaultValue=c["chm_max_m"], minValue=0))
        self.advanced(QgsProcessingParameterString("CHM_FALLBACK", "Fallback canopy height per class where no CHM tile exists (class:m; ...)",
                                                   defaultValue=cfgmod.format_fallback(c["chm_fallback_m"]), optional=True))
        self.advanced(QgsProcessingParameterEnum("COMPRESS", "GeoTIFF compression", COMPRESS, defaultValue=0))
        self.config_param()

        self.addOutput(QgsProcessingOutputFolder("OUT_DIR", "Output folder"))
        for k, t in (("OUT_DEM", "DEM on the working grid"), ("OUT_LC", "Land cover"), ("OUT_CHM", "Canopy height")):
            self.addOutput(QgsProcessingOutputRasterLayer(k, t))

    def do_run(self, parameters, context, feedback):
        cfg, y = self.base_cfg(parameters, context)
        cc = cfg["corrections"]
        P = lambda *a: self.put(cfg, y, *a)
        P(("target_res_m",), self.parameterAsDouble(parameters, "RES", context))
        P(("aoi_buffer_m",), self.parameterAsDouble(parameters, "AOI_BUFFER", context))
        P(("dem_valid_range_m",), [self.parameterAsDouble(parameters, "VALID_MIN", context),
                                   self.parameterAsDouble(parameters, "VALID_MAX", context)])
        P(("corrections", "mode"), MODES[self.parameterAsEnum(parameters, "MODE", context)])
        P(("corrections", "worldcover_url"), self.parameterAsString(parameters, "WORLDCOVER_URL", context))
        P(("corrections", "chm_url"), self.parameterAsString(parameters, "CHM_URL", context))
        P(("corrections", "chm_quadkey_zoom"), self.parameterAsInt(parameters, "CHM_ZOOM", context))
        P(("corrections", "chm_min_m"), self.parameterAsDouble(parameters, "CHM_MIN", context))
        P(("corrections", "chm_max_m"), self.parameterAsDouble(parameters, "CHM_MAX", context))
        P(("corrections", "chm_fallback_m"), cfgmod.parse_fallback(self.parameterAsString(parameters, "CHM_FALLBACK", context)))
        crs = self.parameterAsCrs(parameters, "CRS", context)
        if crs.isValid():
            cfg["target_crs"] = crs.authid() or crs.toWkt()
        lc_layer = self.parameterAsRasterLayer(parameters, "LANDCOVER", context)
        chm_layer = self.parameterAsRasterLayer(parameters, "CHM", context)
        if lc_layer:
            cc["landcover_path"] = raster_path(lc_layer)
        if chm_layer:
            cc["chm_path"] = raster_path(chm_layer)
        compress = COMPRESS[self.parameterAsEnum(parameters, "COMPRESS", context)]

        out = self.out_dir(parameters, context, feedback)
        dems = [raster_path(l) for l in self.parameterAsLayerList(parameters, "DEM", context)]
        aoi_src = self.parameterAsSource(parameters, "AOI", context)
        aoi_wkt = dissolved_wkt(aoi_src, context) if aoi_src else None

        feedback.setProgress(5)
        dem, grid, aoi_mask, aoi_buf = prepare.load_dem(
            dems, aoi_wkt, cfg["aoi_buffer_m"], cfg["target_crs"], cfg["target_res_m"],
            cfg["dem_valid_range_m"], prepare.RESAMPLING[self.parameterAsEnum(parameters, "DEM_RESAMPLING", context)])
        feedback.setProgress(30)
        check = self.cancel_check(feedback)
        check()

        lc, chm, meta = prepare.get_corrections(cc, grid, check)
        feedback.setProgress(80)

        results = {"OUT_DIR": out}
        p = lambda n: os.path.join(out, n)
        write_raster(p("dem_utm.tif"), dem, grid, compress=compress)
        results["OUT_DEM"] = p("dem_utm.tif")
        if aoi_mask is not None:
            write_raster(p("aoi_mask.tif"), aoi_mask.astype("uint8"), grid, "uint8", 255, compress)
        if lc is not None:
            import numpy as np
            write_raster(p("landcover.tif"), np.nan_to_num(lc, nan=0), grid, "uint8", 0, compress)
            results["OUT_LC"] = p("landcover.tif")
        if chm is not None:
            write_raster(p("canopy_height.tif"), chm, grid, compress=compress)
            results["OUT_CHM"] = p("canopy_height.tif")

        mask_layers = self.parameterAsLayerList(parameters, "MASK_VECTORS", context)
        if mask_layers:
            wkts = layers_wkt(mask_layers, context, grid.crs_wkt, self.parameterAsDouble(parameters, "MASK_BUFFER", context))
            vm = prepare.rasterize_wkts(wkts, grid)
            feedback.pushInfo(f"vector mask: {len(wkts)} features, {100 * vm.mean():.2f}% of cells")
            write_raster(p("vector_mask.tif"), vm.astype("uint8"), grid, "uint8", 255, compress)

        cfgmod.dump_json(p("prepare_report.json"), {
            "grid": {"crs": grid.crs_wkt, "res_m": grid.res, "width": grid.width, "height": grid.height,
                     "bounds": grid.bounds},
            "corrections": meta, "config": {k: cfg[k] for k in ("target_res_m", "target_crs", "aoi_buffer_m",
                                                                "dem_valid_range_m", "corrections")}})
        for key, title in (("OUT_DEM", "DEM (working grid)"), ("OUT_LC", "Land cover"), ("OUT_CHM", "Canopy height")):
            if key in results:
                self.load(context, results[key], title)
        for fn, title in (("aoi_mask.tif", "AOI mask"), ("vector_mask.tif", "Vector mask")):
            if os.path.isfile(p(fn)):
                self.load(context, p(fn), title)
        feedback.setProgress(100)
        return results
