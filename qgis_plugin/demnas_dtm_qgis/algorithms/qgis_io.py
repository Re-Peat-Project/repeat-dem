"""Conversions between QGIS layers and the plain numpy/pandas/WKT the core works with."""
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry,
                       QgsProcessingException)

LL = QgsCoordinateReferenceSystem("EPSG:4326")


def raster_path(layer) -> str:
    if layer is None:
        return None
    src = layer.source()
    return src.split("|")[0]


def dissolved_wkt(source, context, crs="EPSG:4326") -> str:
    """All features of a vector source, dissolved and transformed to `crs`, as WKT."""
    geoms = [f.geometry() for f in source.getFeatures() if not f.geometry().isNull()]
    if not geoms:
        raise QgsProcessingException("the polygon layer has no features")
    g = QgsGeometry.unaryUnion(geoms)
    dst = QgsCoordinateReferenceSystem(crs) if isinstance(crs, str) else crs
    if source.sourceCrs() != dst:
        g.transform(QgsCoordinateTransform(source.sourceCrs(), dst, context.transformContext()))
    return g.asWkt()


def layers_wkt(layers, context, grid_crs_wkt: str, buffer_m: float) -> list:
    """Geometries of several vector layers in the grid CRS, buffered, as WKT strings."""
    dst = QgsCoordinateReferenceSystem.fromWkt(grid_crs_wkt)
    out = []
    for lyr in layers:
        ct = QgsCoordinateTransform(lyr.crs(), dst, context.transformContext())
        for f in lyr.getFeatures():
            g = QgsGeometry(f.geometry())
            if g.isNull() or g.isEmpty():
                continue
            g.transform(ct)
            if buffer_m > 0:
                g = g.buffer(float(buffer_m), 16)
            out.append(g.asWkt())
    return out


def _clean(v):
    if v is None or (hasattr(v, "isNull") and v.isNull()):  # None, NULL, null QVariant/QDateTime
        return None
    if hasattr(v, "toString") and not isinstance(v, str):  # QDateTime / QDate
        try:
            return v.toString("yyyy-MM-ddTHH:mm:ss")
        except TypeError:
            return v.toString()
    return v


def source_to_frame(source, context):
    """Point source -> (DataFrame of all attributes, lon array, lat array) in EPSG:4326."""
    import pandas as pd
    ct = QgsCoordinateTransform(source.sourceCrs(), LL, context.transformContext())
    names = [f.name() for f in source.fields()]
    rows, lon, lat = [], [], []
    for feat in source.getFeatures():
        g = QgsGeometry(feat.geometry())
        if g.isNull() or g.isEmpty():
            continue
        g.transform(ct)
        p = g.asMultiPoint()[0] if g.isMultipart() else g.asPoint()
        lon.append(p.x())
        lat.append(p.y())
        rows.append([_clean(v) for v in feat.attributes()])
    df = pd.DataFrame(rows, columns=names)
    for c in df.columns:
        if df[c].dtype == object:
            try:
                df[c] = pd.to_numeric(df[c])
            except (ValueError, TypeError):
                pass
    return df, pd.Series(lon, dtype="float64").to_numpy(), pd.Series(lat, dtype="float64").to_numpy()
