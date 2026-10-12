"""Scoped enums (QGIS 3.36+ and 4.x) with a fallback to the older class-level names (3.34)."""
from qgis.core import (Qgis, QgsProcessingParameterField, QgsProcessingParameterFile,
                       QgsProcessingParameterNumber)

try:
    NUM_DOUBLE = Qgis.ProcessingNumberParameterType.Double
    NUM_INT = Qgis.ProcessingNumberParameterType.Integer
    ADVANCED = Qgis.ProcessingParameterFlag.Advanced
    SRC_POLYGON = Qgis.ProcessingSourceType.VectorPolygon
    SRC_POINT = Qgis.ProcessingSourceType.VectorPoint
    SRC_ANY_VECTOR = Qgis.ProcessingSourceType.VectorAnyGeometry
    SRC_RASTER = Qgis.ProcessingSourceType.Raster
    FILE_BEHAVIOR_FILE = Qgis.ProcessingFileParameterBehavior.File
    FIELD_NUMERIC = Qgis.ProcessingFieldParameterDataType.Numeric
    FIELD_ANY = Qgis.ProcessingFieldParameterDataType.Any
except AttributeError:  # QGIS < 3.36
    NUM_DOUBLE = QgsProcessingParameterNumber.Double
    NUM_INT = QgsProcessingParameterNumber.Integer
    from qgis.core import QgsProcessing, QgsProcessingParameterDefinition
    ADVANCED = QgsProcessingParameterDefinition.FlagAdvanced
    SRC_POLYGON = QgsProcessing.TypeVectorPolygon
    SRC_POINT = QgsProcessing.TypeVectorPoint
    SRC_ANY_VECTOR = QgsProcessing.TypeVectorAnyGeometry
    SRC_RASTER = QgsProcessing.TypeRaster
    FILE_BEHAVIOR_FILE = QgsProcessingParameterFile.File
    FIELD_NUMERIC = QgsProcessingParameterField.Numeric
    FIELD_ANY = QgsProcessingParameterField.Any
