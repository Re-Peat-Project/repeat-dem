"""Shared plumbing for the DEMNAS DTM algorithms."""
import datetime
import importlib
import os
import traceback

from qgis.core import (QgsProcessingAlgorithm, QgsProcessingContext, QgsProcessingException,
                       QgsProcessingParameterFile, QgsProcessingParameterFolderDestination,
                       QgsProject)

from ..core import config as cfgmod
from .compat import ADVANCED, FILE_BEHAVIOR_FILE

GROUP = "DEMNAS to DTM"
PIP = {"yaml": "pyyaml", "osgeo": "gdal"}   # import name -> pip name, where they differ


def default_out_dir(alg_name: str) -> str:
    """<project or home>/demnas_dtm/<algorithm>_<timestamp>: every run gets its own folder, so
    re-running with other parameters never overwrites files that are open in QGIS."""
    try:
        home = QgsProject.instance().homePath()
    except Exception:
        home = ""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.join(home or os.path.expanduser("~"), "demnas_dtm", f"{alg_name}_{stamp}")


def sibling(path, name):
    """`name` in the same folder as `path` (e.g. aoi_mask.tif next to dem_utm.tif), if it exists."""
    p = os.path.join(os.path.dirname(path), name)
    return p if os.path.isfile(p) else None


def is_set(parameters, name) -> bool:
    v = parameters.get(name)
    return v is not None and v != "" and str(v) != "NULL"


class DemnasAlgorithm(QgsProcessingAlgorithm):
    """Subclasses set NAME, TITLE, HELP, implement define() and do_run()."""

    NAME = ""
    TITLE = ""
    HELP = ""
    NEEDS = ()          # Python modules this algorithm imports, e.g. ("numpy", "scipy")
    OUTPUT_FILES = ()   # files it writes into the output folder (used to detect a previous run)

    # ---- QGIS boilerplate -------------------------------------------------------------
    def createInstance(self):
        return self.__class__()

    def name(self):
        return self.NAME

    def displayName(self):
        return self.TITLE

    def group(self):
        return GROUP

    def groupId(self):
        return "demnas_dtm"

    def shortHelpString(self):
        return self.HELP

    def initAlgorithm(self, config=None):
        self.define()

    # ---- parameter helpers ------------------------------------------------------------
    def basic(self, p):
        self.addParameter(p)
        return p

    def advanced(self, p):
        p.setFlags(p.flags() | ADVANCED)
        self.addParameter(p)
        return p

    def out_dir_param(self, name="OUT_DIR", desc="Output folder (a new one per run by default)"):
        return self.basic(QgsProcessingParameterFolderDestination(name, desc, defaultValue=default_out_dir(self.NAME)))

    def config_param(self):
        return self.advanced(QgsProcessingParameterFile(
            "CONFIG", "Config YAML (optional; same schema as the command-line tool). "
                      "A widget you change overrides the file; a widget left at its default value does not.",
            behavior=FILE_BEHAVIOR_FILE, extension="yaml", optional=True))

    # ---- config assembly --------------------------------------------------------------
    def base_cfg(self, parameters, context):
        """Defaults, overlaid by the optional YAML. Returns (cfg, yaml_given)."""
        path = self.parameterAsFile(parameters, "CONFIG", context) if "CONFIG" in self.parameterDefinitions_names() else ""
        return cfgmod.base_config(path or None), bool(path)

    def parameterDefinitions_names(self):
        return [p.name() for p in self.parameterDefinitions()]

    @staticmethod
    def put(cfg, yaml_given, path, value):
        """Widget value wins unless a YAML was given and the widget is still at its default."""
        if not yaml_given or value != cfgmod.get_path(cfgmod.DEFAULTS, path):
            cfgmod.set_path(cfg, path, value)

    def out_dir(self, parameters, context, feedback=None) -> str:
        """The output folder. If it already holds this algorithm's results (the dialog stays open
        after a run, with those results loaded in the project, and Run is pressed again), use a
        new sibling folder `<folder>_<HHMMSS>` instead of overwriting files that may be open."""
        d = self.parameterAsString(parameters, "OUT_DIR", context).rstrip("/\\")
        if any(os.path.exists(os.path.join(d, f)) for f in self.OUTPUT_FILES):
            stamp = datetime.datetime.now().strftime("%H%M%S")
            new, i = f"{d}_{stamp}", 2
            while os.path.exists(new):
                new, i = f"{d}_{stamp}_{i}", i + 1
            if feedback is not None:
                feedback.pushInfo(f"{d} already holds results of this algorithm; writing to {new} instead")
            d = new
        os.makedirs(d, exist_ok=True)
        return d

    def load(self, context, path, title):
        """Add a result to the project when the algorithm finishes (the GUI does the loading).
        The run folder is part of the layer name, so repeated runs can be told apart."""
        name = f"{title} [{os.path.basename(os.path.dirname(str(path)))}]"
        context.addLayerToLoadOnCompletion(
            str(path), QgsProcessingContext.LayerDetails(name, context.project(), title))

    # ---- run --------------------------------------------------------------------------
    def check_deps(self):
        missing = []
        for mod in self.NEEDS:
            try:
                importlib.import_module(mod)
            except ImportError:
                missing.append(mod)
        if missing:
            pkgs = [PIP.get(m, m) for m in missing]
            raise QgsProcessingException(
                "QGIS's Python is missing: " + ", ".join(missing) + ".\n"
                "Install them once, either in the OSGeo4W Shell:  python -m pip install " + " ".join(pkgs) +
                "\nor with the OSGeo4W installer (Advanced Install): packages " +
                ", ".join("python3-" + p for p in pkgs) + ".\nThen restart QGIS.")

    def processAlgorithm(self, parameters, context, feedback):
        self.check_deps()
        try:
            with cfgmod.bridge_logging(feedback):
                return self.do_run(parameters, context, feedback)
        except QgsProcessingException:
            raise
        except Exception as e:
            feedback.pushDebugInfo(traceback.format_exc())
            raise QgsProcessingException(f"{type(e).__name__}: {e}")

    @staticmethod
    def cancel_check(feedback):
        def f():
            if feedback.isCanceled():
                raise RuntimeError("cancelled by user")
        return f
