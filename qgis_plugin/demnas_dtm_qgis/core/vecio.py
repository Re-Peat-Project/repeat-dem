"""Write a point table to GeoPackage with OGR (no geopandas, no QGIS API)."""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
from osgeo import ogr, osr

ogr.UseExceptions()


def write_points_gpkg(path, df: pd.DataFrame, x, y, crs_wkt: str, layer: str = "points"):
    path = str(path)
    drv = ogr.GetDriverByName("GPKG")
    try:
        if os.path.exists(path):
            drv.DeleteDataSource(path)
        ds = drv.CreateDataSource(path)
    except Exception as e:
        raise RuntimeError(f"cannot write {path}: {e}. If that file is loaded in QGIS, remove the layer "
                           "or choose another output folder.") from e
    sr = osr.SpatialReference()
    sr.ImportFromWkt(crs_wkt)
    sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    lyr = ds.CreateLayer(layer, sr, ogr.wkbPoint)
    kinds = {}
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_bool_dtype(s):
            t, k = ogr.OFTInteger, "i"
        elif pd.api.types.is_integer_dtype(s):
            t, k = ogr.OFTInteger64, "i"
        elif pd.api.types.is_float_dtype(s):
            t, k = ogr.OFTReal, "f"
        else:
            t, k = ogr.OFTString, "s"
        lyr.CreateField(ogr.FieldDefn(str(c), t))
        kinds[c] = k
    lyr.StartTransaction()
    cols = list(df.columns)
    vals = [df[c].to_numpy() for c in cols]
    for i in range(len(df)):
        f = ogr.Feature(lyr.GetLayerDefn())
        for j, c in enumerate(cols):
            v = vals[j][i]
            if v is None or (isinstance(v, float) and np.isnan(v)):
                continue
            k = kinds[c]
            f.SetField(j, int(v) if k == "i" else float(v) if k == "f" else str(v))
        pt = ogr.Geometry(ogr.wkbPoint)
        pt.AddPoint_2D(float(x[i]), float(y[i]))
        f.SetGeometry(pt)
        lyr.CreateFeature(f)
    lyr.CommitTransaction()
    ds = None
