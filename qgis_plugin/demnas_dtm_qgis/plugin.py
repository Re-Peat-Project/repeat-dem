from qgis.core import QgsApplication

from .provider import DemnasProvider


class DemnasDtmPlugin:
    """Registers the 'DEMNAS to DTM' Processing provider (Processing toolbox)."""

    def __init__(self):
        self.provider = None

    def initProcessing(self):
        self.provider = DemnasProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
