"""Grid description and GDAL raster I/O (no rasterio, no QGIS imports: runs in any GDAL Python)."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()
log = logging.getLogger("demnas_dtm")


class Affine:
    """Minimal north-up affine, enough for ground_truth.sample_arrays (`~t * (x, y)`)."""

    def __init__(self, a, c, e, f):
        self.a, self.c, self.e, self.f = a, c, e, f

    def __invert__(self):
        return _InvAffine(self)


class _InvAffine:
    def __init__(self, t):
        self.t = t

    def __mul__(self, xy):
        x, y = xy
        return (np.asarray(x) - self.t.c) / self.t.a, (np.asarray(y) - self.t.f) / self.t.e


@dataclass
class Grid:
    crs_wkt: str
    left: float
    top: float
    res: float
    width: int
    height: int

    @property
    def transform(self) -> Affine:
        return Affine(self.res, self.left, -self.res, self.top)

    @property
    def geotransform(self):
        return (self.left, self.res, 0.0, self.top, 0.0, -self.res)

    @property
    def bounds(self):
        return (self.left, self.top - self.height * self.res, self.left + self.width * self.res, self.top)

    @property
    def shape(self):
        return (self.height, self.width)

    @property
    def crs(self):
        import pyproj
        return pyproj.CRS.from_wkt(self.crs_wkt)

    def same_as(self, other: "Grid", tol: float = 1e-6) -> bool:
        return (self.width == other.width and self.height == other.height
                and abs(self.res - other.res) < tol and abs(self.left - other.left) < tol
                and abs(self.top - other.top) < tol and self.crs.equals(other.crs))

    @classmethod
    def from_dataset(cls, ds) -> "Grid":
        gt = ds.GetGeoTransform()
        if abs(gt[2]) > 0 or abs(gt[4]) > 0:
            raise ValueError("rotated rasters are not supported")
        if abs(abs(gt[1]) - abs(gt[5])) > 1e-9 * abs(gt[1]):
            raise ValueError("non-square pixels are not supported")
        return cls(ds.GetProjection(), gt[0], gt[3], abs(gt[1]), ds.RasterXSize, ds.RasterYSize)


def auto_utm(lon: float, lat: float) -> str:
    zone = int((lon + 180) // 6) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"


def crs_to_wkt(crs: str) -> str:
    sr = osr.SpatialReference()
    if sr.SetFromUserInput(str(crs)) != 0:
        raise ValueError(f"cannot interpret CRS {crs!r}")
    return sr.ExportToWkt()


# --------------------------------------------------------------------------------------
# Reading and writing
# --------------------------------------------------------------------------------------
def open_raster(path: str):
    ds = gdal.Open(str(path))
    if ds is None:
        raise RuntimeError(f"cannot open raster {path}")
    return ds


def read_band(ds, band: int = 1) -> np.ndarray:
    """float32 array with nodata -> NaN."""
    b = ds.GetRasterBand(band)
    arr = b.ReadAsArray().astype("float32")
    nd = b.GetNoDataValue()
    if nd is not None and not (isinstance(nd, float) and math.isnan(nd)):
        arr[arr == np.float32(nd)] = np.nan
    return arr


def mem_dataset(arr: np.ndarray, grid: Grid, nodata=None):
    dt = {"float32": gdal.GDT_Float32, "uint8": gdal.GDT_Byte, "int16": gdal.GDT_Int16,
          "float64": gdal.GDT_Float64}[str(arr.dtype)]
    ds = gdal.GetDriverByName("MEM").Create("", grid.width, grid.height, 1, dt)
    ds.SetGeoTransform(grid.geotransform)
    ds.SetProjection(grid.crs_wkt)
    b = ds.GetRasterBand(1)
    if nodata is not None:
        b.SetNoDataValue(nodata)
    b.WriteArray(arr)
    return ds


def write_raster(path, arr: np.ndarray, grid: Grid, dtype="float32", nodata=np.nan, compress="deflate"):
    if dtype != "float32" and isinstance(nodata, float) and math.isnan(nodata):
        nodata = 0
    gdt = {"float32": gdal.GDT_Float32, "uint8": gdal.GDT_Byte}[dtype]
    opts = ["TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"]
    if compress and compress.lower() != "none":
        opts.append(f"COMPRESS={compress.upper()}")
    try:
        ds = gdal.GetDriverByName("GTiff").Create(str(path), grid.width, grid.height, 1, gdt, opts)
    except RuntimeError as e:
        raise RuntimeError(f"cannot write {path}: {e}. If that file is loaded in QGIS, remove the layer "
                           "or choose another output folder.") from e
    ds.SetGeoTransform(grid.geotransform)
    ds.SetProjection(grid.crs_wkt)
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(float(nodata))
    b.WriteArray(arr.astype(dtype))
    b.FlushCache()
    ds = None
    log.info("wrote %s", path)


def load_aligned(path: str, grid: Grid, resampling: str = "nearest", nodata=None) -> np.ndarray:
    """Read a raster onto `grid`; warps only when its grid differs."""
    ds = open_raster(path)
    g = Grid.from_dataset(ds)
    if g.same_as(grid):
        return read_band(ds)
    log.warning("%s is not on the working grid; resampling (%s) onto it", path, resampling)
    out = np.full(grid.shape, np.nan, dtype="float32")
    dst = mem_dataset(out, grid, nodata=float("nan"))
    kw = dict(resampleAlg=resampling, dstNodata=float("nan"))
    if nodata is not None:
        kw["srcNodata"] = nodata
    gdal.Warp(dst, ds, options=gdal.WarpOptions(**kw))
    return dst.GetRasterBand(1).ReadAsArray().astype("float32")


def sample_nearest(path: str, x: np.ndarray, y: np.ndarray, crs_wkt_xy: str):
    """Nearest-cell values of band 1 at points given in `crs_wkt_xy`. Returns (values, inside)."""
    import pyproj
    ds = open_raster(path)
    g = Grid.from_dataset(ds)
    src = pyproj.CRS.from_wkt(crs_wkt_xy)
    if not src.equals(g.crs):
        x, y = pyproj.Transformer.from_crs(src, g.crs, always_xy=True).transform(x, y)
    cols = np.floor((np.asarray(x) - g.left) / g.res).astype(int)
    rows = np.floor((g.top - np.asarray(y)) / g.res).astype(int)
    inside = (rows >= 0) & (rows < g.height) & (cols >= 0) & (cols < g.width)
    arr = read_band(ds)
    v = np.full(len(cols), np.nan)
    v[inside] = arr[rows[inside], cols[inside]]
    return v, inside
