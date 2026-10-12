from qgis.core import QgsProcessingProvider

from .algorithms.calibrate_points import CalibratePoints
from .algorithms.correct_smooth import CorrectSmooth
from .algorithms.fetch_points import FetchGroundPoints
from .algorithms.prepare_inputs import PrepareInputs
from .algorithms.validate_surfaces import ValidateSurfaces


class DemnasProvider(QgsProcessingProvider):
    def id(self):
        return "demnas_dtm"

    def name(self):
        return "DEMNAS to DTM"

    def longName(self):
        return "DEMNAS to DTM: vegetation correction, calibration, smoothing and validation"

    def loadAlgorithms(self):
        for cls in (PrepareInputs, FetchGroundPoints, CalibratePoints, CorrectSmooth, ValidateSurfaces):
            self.addAlgorithm(cls())
