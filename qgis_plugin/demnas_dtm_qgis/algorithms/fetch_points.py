import copy
import os

from qgis.core import (QgsProcessingException, QgsProcessingOutputFile, QgsProcessingOutputFolder,
                       QgsProcessingParameterBoolean, QgsProcessingParameterEnum,
                       QgsProcessingParameterFeatureSource, QgsProcessingParameterNumber,
                       QgsProcessingParameterString)

from ..core import config as cfgmod
from ..core.grid import crs_to_wkt
from .base import DemnasAlgorithm
from .compat import NUM_DOUBLE, NUM_INT, SRC_POLYGON
from .qgis_io import dissolved_wkt

DATASETS = ["icesat2_atl08", "gedi_l2a"]
G = cfgmod.DEFAULTS["ground"]


class FetchGroundPoints(DemnasAlgorithm):
    OUTPUT_FILES = ('ground_points_raw.gpkg',)
    NAME = "fetch_ground_points"
    TITLE = "5. Fetch ICESat-2 / GEDI ground points (optional, needs sliderule)"
    HELP = (
        "Requests ICESat-2 ATL08 terrain heights (PhoREAL, 100 m segments) and/or GEDI L2A ground "
        "elevations inside the AOI from SlideRule's public service and writes them as a point layer "
        "(ground_points_raw.gpkg, heights are ELLIPSOIDAL: tick that box in algorithm 2).\n\n"
        "This is the only algorithm that needs the extra Python package 'sliderule' (plus geopandas "
        "and shapely). In the OSGeo4W Shell:  python -m pip install sliderule geopandas shapely\n\n"
        "Without it, skip this algorithm and give algorithm 2 your own points (CSV, RTK survey, a "
        "layer exported earlier). The request fails loudly: an empty result or a failed tile is an "
        "error, not a silent run with placeholder values.\n\n"
        "Large AOIs are split into tiles (SlideRule refuses requests over ~300 granules). The time limit "
        "is sent with each request as timeout parameters (whether the service enforces it is not "
        "verified); Cancel in QGIS is honoured between tiles. The number of points the service "
        "returns can differ from one request to the next."
    )
    NEEDS = ("numpy", "pandas", "pyproj", "osgeo", "geopandas", "shapely", "sliderule")

    def define(self):
        self.basic(QgsProcessingParameterFeatureSource("AOI", "Area of interest", [SRC_POLYGON]))
        self.basic(QgsProcessingParameterEnum("DATASETS", "Datasets", DATASETS, allowMultiple=True, defaultValue=[0]))
        self.basic(QgsProcessingParameterString("T0", "Start time", defaultValue=G["t0"]))
        self.basic(QgsProcessingParameterString("T1", "End time", defaultValue=G["t1"]))
        self.out_dir_param()
        ic, ge = G["icesat2"], G["gedi"]
        self.advanced(QgsProcessingParameterNumber("TILE_DEG", "Tile size (degrees, 0 = no tiling)", type=NUM_DOUBLE,
                                                   defaultValue=G["tile_deg"], minValue=0))
        self.advanced(QgsProcessingParameterNumber("SIMPLIFY", "Simplify AOI before sending (degrees)", type=NUM_DOUBLE,
                                                   defaultValue=G["simplify_aoi_deg"], minValue=0))
        self.advanced(QgsProcessingParameterNumber("TIMEOUT", "Request time limit (s)", type=NUM_INT, defaultValue=900, minValue=30))
        self.advanced(QgsProcessingParameterBoolean("FAIL_TILE", "Stop if any tile fails", defaultValue=True))
        self.advanced(QgsProcessingParameterNumber("ATL08_LEN", "ATL08 segment length (m)", type=NUM_DOUBLE, defaultValue=ic["len"], minValue=10))
        self.advanced(QgsProcessingParameterNumber("ATL08_RES", "ATL08 step between segments (m)", type=NUM_DOUBLE, defaultValue=ic["res"], minValue=10))
        self.advanced(QgsProcessingParameterBoolean("NIGHT_ONLY", "ICESat-2: night passes only", defaultValue=ic["night_only"]))
        self.advanced(QgsProcessingParameterNumber("MIN_PHOTONS", "ICESat-2: minimum ground photons (0 = off)", type=NUM_INT,
                                                   defaultValue=ic["min_ground_photons"], minValue=0))
        self.advanced(QgsProcessingParameterNumber("GEDI_DEGRADE", "GEDI: degrade flag", type=NUM_INT, defaultValue=ge["degrade_flag"]))
        self.advanced(QgsProcessingParameterNumber("GEDI_QUALITY", "GEDI: L2 quality flag", type=NUM_INT, defaultValue=ge["l2_quality_flag"]))
        self.advanced(QgsProcessingParameterNumber("GEDI_SENS", "GEDI: minimum sensitivity (0 = off)", type=NUM_DOUBLE,
                                                   defaultValue=ge["min_sensitivity"], minValue=0, maxValue=1))
        self.addOutput(QgsProcessingOutputFolder("OUT_DIR", "Output folder"))
        self.addOutput(QgsProcessingOutputFile("OUT_POINTS", "ground_points_raw.gpkg"))

    def do_run(self, parameters, context, feedback):
        import numpy as np
        import pandas as pd
        import shapely.wkt
        from ..core.vecio import write_points_gpkg
        from shapely.geometry import box
        from ..core import ground_truth as gt

        g = copy.deepcopy(G)
        g["datasets"] = [DATASETS[i] for i in self.parameterAsEnums(parameters, "DATASETS", context)]
        if not g["datasets"]:
            raise QgsProcessingException("select at least one dataset")
        g["t0"] = self.parameterAsString(parameters, "T0", context)
        g["t1"] = self.parameterAsString(parameters, "T1", context)
        g["tile_deg"] = self.parameterAsDouble(parameters, "TILE_DEG", context)
        g["simplify_aoi_deg"] = self.parameterAsDouble(parameters, "SIMPLIFY", context)
        g["icesat2"].update(len=self.parameterAsDouble(parameters, "ATL08_LEN", context),
                            res=self.parameterAsDouble(parameters, "ATL08_RES", context),
                            night_only=self.parameterAsBoolean(parameters, "NIGHT_ONLY", context),
                            min_ground_photons=self.parameterAsInt(parameters, "MIN_PHOTONS", context))
        g["gedi"].update(degrade_flag=self.parameterAsInt(parameters, "GEDI_DEGRADE", context),
                         l2_quality_flag=self.parameterAsInt(parameters, "GEDI_QUALITY", context),
                         min_sensitivity=self.parameterAsDouble(parameters, "GEDI_SENS", context))
        timeout = self.parameterAsInt(parameters, "TIMEOUT", context)
        fail_tile = self.parameterAsBoolean(parameters, "FAIL_TILE", context)

        out = self.out_dir(parameters, context, feedback)
        aoi = shapely.wkt.loads(dissolved_wkt(self.parameterAsSource(parameters, "AOI", context), context))

        # SlideRule parameters are built inside ground_truth._fetch_one; inject the time limit
        # into the request dicts without editing that module.
        from sliderule import gedi, icesat2
        patched = []
        for mod, fn in ((gedi, "gedi02ap"), (icesat2, "atl08p")):
            orig = getattr(mod, fn)
            patched.append((mod, fn, orig))
            setattr(mod, fn, (lambda o: lambda parms, *a, **k: o({**parms, "timeout": timeout, "rqst-timeout": timeout,
                                                                   "node-timeout": timeout, "read-timeout": timeout},
                                                                  *a, **k))(orig))
        frames, nfail = [], 0
        try:
            x0, y0, x1, y1 = aoi.bounds
            tile = float(g["tile_deg"] or 0)
            if tile <= 0 or max(x1 - x0, y1 - y0) <= tile:
                parts = [aoi]
            else:
                parts = []
                for x in np.arange(x0, x1, tile):
                    for y in np.arange(y0, y1, tile):
                        part = aoi.intersection(box(x, y, min(x + tile, x1), min(y + tile, y1)))
                        if not part.is_empty and part.area >= 1e-6:
                            parts.append(part)
            feedback.pushInfo(f"SlideRule: {len(parts)} request(s)")
            for i, part in enumerate(parts):
                if feedback.isCanceled():
                    raise QgsProcessingException("cancelled")
                try:
                    r = gt._fetch_one(part, g)
                except Exception as e:
                    nfail += 1
                    feedback.reportError(f"SlideRule request {i + 1}/{len(parts)} failed: {e}", fatalError=False)
                    if fail_tile:
                        raise QgsProcessingException(f"SlideRule request failed: {e}")
                    continue
                if len(r):
                    frames.append(pd.DataFrame(r.drop(columns="geometry", errors="ignore")))
                feedback.setProgress(10 + 85 * (i + 1) / len(parts))
        finally:
            for mod, fn, orig in patched:
                setattr(mod, fn, orig)

        if not frames:
            raise QgsProcessingException(
                "SlideRule returned 0 points (no coverage, no network, or every request failed). "
                "Nothing was written.")
        df = pd.concat(frames, ignore_index=True)
        if nfail:
            feedback.pushWarning(f"{nfail} request(s) failed; the points are incomplete")
        p = os.path.join(out, "ground_points_raw.gpkg")
        write_points_gpkg(p, df, df["lon"].to_numpy(), df["lat"].to_numpy(), crs_to_wkt("EPSG:4326"), "ground_points_raw")
        feedback.pushInfo(f"{len(df)} points: " + str(df["source"].value_counts().to_dict()))
        self.load(context, p, "Ground points (raw)")
        feedback.setProgress(100)
        return {"OUT_DIR": out, "OUT_POINTS": p}
