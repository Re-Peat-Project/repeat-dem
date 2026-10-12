"""Stage 1: DEM mosaic/clip/reproject and the land cover + canopy height correction layers.
GDAL/OGR/pyproj only (the same GDAL warp engine rasterio calls)."""
from __future__ import annotations

import logging
import math
import uuid

import numpy as np
from osgeo import gdal, ogr, osr

from .grid import Grid, auto_utm, crs_to_wkt, mem_dataset, open_raster, read_band

gdal.UseExceptions()
log = logging.getLogger("demnas_dtm")

RESAMPLING = ["bilinear", "cubic", "nearest", "average"]


def _srs(user_input: str) -> osr.SpatialReference:
    sr = osr.SpatialReference()
    if sr.SetFromUserInput(user_input) != 0:
        raise ValueError(f"cannot interpret CRS {user_input!r}")
    sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return sr


def _transform_bounds(bounds, src_wkt_or_code: str, dst_wkt_or_code: str, densify: int = 21):
    import pyproj
    tr = pyproj.Transformer.from_crs(pyproj.CRS.from_user_input(src_wkt_or_code),
                                     pyproj.CRS.from_user_input(dst_wkt_or_code), always_xy=True)
    return tr.transform_bounds(*bounds, densify_pts=densify)


# --------------------------------------------------------------------------------------
# AOI and vector masks
# --------------------------------------------------------------------------------------
def buffered_aoi_ll(wkt_ll: str, buffer_m: float) -> str:
    """Dissolved AOI (WKT, EPSG:4326) -> buffered AOI (WKT, EPSG:4326). The buffer is applied in
    the UTM zone of the AOI centroid, like demnas_dtm.read_aoi."""
    g = ogr.CreateGeometryFromWkt(wkt_ll)
    ll = _srs("EPSG:4326")
    c = g.Centroid()
    utm = _srs(auto_utm(c.GetX(), c.GetY()))
    g.AssignSpatialReference(ll)
    g.TransformTo(utm)
    g = g.Buffer(float(buffer_m), 16)
    g.TransformTo(ll)
    return g.ExportToWkt()


def rasterize_wkts(wkts: list[str], grid: Grid) -> np.ndarray:
    """Boolean mask of cells whose centre falls inside any geometry (WKT in the grid CRS)."""
    out = np.zeros(grid.shape, dtype="uint8")
    if not wkts:
        return out.astype(bool)
    ds = mem_dataset(out, grid)
    drv = ogr.GetDriverByName("MEM") or ogr.GetDriverByName("Memory")  # "Memory" before GDAL 3.11
    vds = drv.CreateDataSource("m_" + uuid.uuid4().hex)
    sr = osr.SpatialReference()
    sr.ImportFromWkt(grid.crs_wkt)
    sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    lyr = vds.CreateLayer("m", sr)
    for w in wkts:
        geom = ogr.CreateGeometryFromWkt(w)
        if geom is None or geom.IsEmpty():
            continue
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetGeometry(geom)
        lyr.CreateFeature(f)
    gdal.RasterizeLayer(ds, [1], lyr, burn_values=[1])
    return ds.GetRasterBand(1).ReadAsArray().astype(bool)


# --------------------------------------------------------------------------------------
# DEM
# --------------------------------------------------------------------------------------
def suggested_grid(window, src_res: float, src_wkt: str, dst_wkt: str, res: float) -> Grid:
    """Target grid for a source window, the way rasterio.warp.calculate_default_transform does it
    with a resolution: GDAL's suggested warp output, upper-left kept, size rescaled (ceil)."""
    left, bottom, right, top = window
    w = int(round((right - left) / src_res))
    h = int(round((top - bottom) / src_res))
    probe = gdal.GetDriverByName("VRT").Create("", w, h, 1)
    probe.SetGeoTransform((left, src_res, 0.0, top, 0.0, -src_res))
    probe.SetProjection(src_wkt)
    sug = gdal.AutoCreateWarpedVRT(probe, src_wkt, dst_wkt)
    gt = sug.GetGeoTransform()
    width = max(1, int(math.ceil(sug.RasterXSize * gt[1] / res)))
    height = max(1, int(math.ceil(sug.RasterYSize * abs(gt[5]) / res)))
    return Grid(dst_wkt, gt[0], gt[3], res, width, height)


def load_dem(paths: list[str], aoi_ll_wkt: str | None, aoi_buffer_m: float, target_crs: str,
             res: float, valid_range, resampling: str = "bilinear"):
    """Returns (dem, grid, aoi_mask or None, buffered_aoi_ll_wkt or None)."""
    if not paths:
        raise ValueError("no DEM input given")
    log.info("DEM tiles: %d", len(paths))
    vrt_name = f"/vsimem/dem_{uuid.uuid4().hex}.vrt"
    vrt = gdal.BuildVRT(vrt_name, [str(p) for p in paths])
    first = open_raster(paths[0])
    src_wkt = vrt.GetProjection() or first.GetProjection()
    if not src_wkt:
        raise ValueError("DEM has no CRS")
    nd = first.GetRasterBand(1).GetNoDataValue()
    src_nodata = nd if nd is not None else -99999.0

    gt0 = vrt.GetGeoTransform()
    full = (gt0[0], gt0[3] + gt0[5] * vrt.RasterYSize, gt0[0] + gt0[1] * vrt.RasterXSize, gt0[3])
    aoi_buf = None
    if aoi_ll_wkt:
        aoi_buf = buffered_aoi_ll(aoi_ll_wkt, aoi_buffer_m)
        env = ogr.CreateGeometryFromWkt(aoi_buf).GetEnvelope()  # minx, maxx, miny, maxy
        window = _transform_bounds((env[0], env[2], env[1], env[3]), "EPSG:4326", src_wkt)
    else:
        window = full

    if str(target_crs).lower() == "auto-utm":
        lon0, lat0, lon1, lat1 = _transform_bounds(window, src_wkt, "EPSG:4326")
        dst_wkt = crs_to_wkt(auto_utm((lon0 + lon1) / 2, (lat0 + lat1) / 2))
    else:
        dst_wkt = crs_to_wkt(target_crs)
    grid = suggested_grid(window, abs(first.GetGeoTransform()[1]), src_wkt, dst_wkt, float(res))

    # Mosaic the window at source resolution (as rasterio.merge does), mask nodata and the valid
    # range there, then warp: invalid source cells must not be blended into the output.
    sres = abs(first.GetGeoTransform()[1])
    mgrid = Grid(src_wkt, window[0], window[3], sres, int(round((window[2] - window[0]) / sres)),
                 int(round((window[3] - window[1]) / sres)))
    mosaic = mem_dataset(np.full(mgrid.shape, np.nan, dtype="float32"), mgrid, nodata=float("nan"))
    gdal.Warp(mosaic, vrt, options=gdal.WarpOptions(resampleAlg="nearest", srcNodata=src_nodata,
                                                   dstNodata=float("nan")))
    vrt = None  # close before unlinking the in-memory VRT
    gdal.Unlink(vrt_name)
    src = mosaic.GetRasterBand(1).ReadAsArray()
    lo, hi = valid_range
    src[(src < lo) | (src > hi)] = np.nan
    mosaic.GetRasterBand(1).WriteArray(src)
    del src

    dst = mem_dataset(np.full(grid.shape, np.nan, dtype="float32"), grid, nodata=float("nan"))
    gdal.Warp(dst, mosaic, options=gdal.WarpOptions(resampleAlg=resampling, srcNodata=float("nan"),
                                                   dstNodata=float("nan")))
    dem = dst.GetRasterBand(1).ReadAsArray().astype("float32")
    mosaic = None

    aoi_mask = None
    if aoi_buf:
        g = ogr.CreateGeometryFromWkt(aoi_buf)
        g.AssignSpatialReference(_srs("EPSG:4326"))
        sr = osr.SpatialReference()
        sr.ImportFromWkt(dst_wkt)
        sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        g.TransformTo(sr)
        aoi_mask = rasterize_wkts([g.ExportToWkt()], grid)
        dem[~aoi_mask] = np.nan
    log.info("DEM grid: %s, %d x %d px at %.1f m", dst_wkt.split('"')[1], grid.width, grid.height, res)
    return dem, grid, aoi_mask, aoi_buf


# --------------------------------------------------------------------------------------
# Corrections: land cover + canopy height
# --------------------------------------------------------------------------------------
class cloud_env:
    """GDAL settings for efficient, unsigned windowed reads of public COGs."""
    OPTS = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff",
            "GDAL_HTTP_MULTIRANGE": "YES", "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
            "GDAL_HTTP_MAX_RETRY": "4", "GDAL_HTTP_RETRY_DELAY": "2", "VSI_CACHE": "TRUE",
            "AWS_NO_SIGN_REQUEST": "YES"}

    def __enter__(self):
        self.old = {k: gdal.GetConfigOption(k) for k in self.OPTS}
        for k, v in self.OPTS.items():
            gdal.SetConfigOption(k, v)

    def __exit__(self, *exc):
        for k, v in self.old.items():
            gdal.SetConfigOption(k, v)
        return False


def grid_bounds_ll(grid: Grid):
    return _transform_bounds(grid.bounds, grid.crs_wkt, "EPSG:4326")


def worldcover_tiles(bounds_ll) -> list[str]:
    lon0, lat0, lon1, lat1 = bounds_ll
    tiles = []
    for lat in range(int(math.floor(lat0 / 3) * 3), int(math.floor(lat1 / 3) * 3) + 1, 3):
        for lon in range(int(math.floor(lon0 / 3) * 3), int(math.floor(lon1 / 3) * 3) + 1, 3):
            ns = "N" if lat >= 0 else "S"
            ew = "E" if lon >= 0 else "W"
            tiles.append(f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}")
    return tiles


def _xy_tile(lon: float, lat: float, z: int):
    n = 2 ** z
    x = int(math.floor((lon + 180.0) / 360.0 * n))
    lat = max(min(lat, 85.0511287798066), -85.0511287798066)
    y = int(math.floor((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n))
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def chm_quadkeys(bounds_ll, zoom: int) -> list[str]:
    """Quadkeys of the web-mercator tiles covering the bounds (mercantile.tiles + quadkey)."""
    w, s, e, n = bounds_ll
    eps = 1e-11
    x0, y0 = _xy_tile(w, n, zoom)
    x1, y1 = _xy_tile(e - eps, s + eps, zoom)
    keys = []
    for x in range(x0, max(x0, x1) + 1):
        for y in range(y0, max(y0, y1) + 1):
            q = ""
            for i in range(zoom, 0, -1):
                m = 1 << (i - 1)
                q += str((1 if x & m else 0) + (2 if y & m else 0))
            keys.append(q)
    return keys


def pick_overview(ds, target_res_src_units: float):
    """Index of the coarsest overview whose resolution is still <= half the target resolution."""
    b = ds.GetRasterBand(1)
    res0 = abs(ds.GetGeoTransform()[1])
    best = None
    for i in range(b.GetOverviewCount()):
        f = round(b.XSize / b.GetOverview(i).XSize)
        if res0 * f <= target_res_src_units / 2:
            best = i
    return best


def warp_into(path: str, dst: np.ndarray, grid: Grid, resampling: str, remote: bool,
              nodata_override=None) -> bool:
    """Warp a (possibly remote) raster into dst where dst is still empty. Returns success."""
    vpath = f"/vsicurl/{path}" if remote and path.startswith("http") else path
    try:
        src = gdal.Open(vpath)
        sr = osr.SpatialReference()
        sr.ImportFromWkt(src.GetProjection())
        tgt = grid.res / 111320.0 if sr.IsGeographic() else grid.res
        ovl = pick_overview(src, tgt) if remote else None
        nod = nodata_override if nodata_override is not None else src.GetRasterBand(1).GetNoDataValue()
        tmpds = mem_dataset(np.full(dst.shape, np.nan, dtype="float32"), grid, nodata=float("nan"))
        kw = dict(resampleAlg=resampling, dstNodata=float("nan"),
                  overviewLevel=ovl if ovl is not None else "NONE")
        if nod is not None:
            kw["srcNodata"] = nod
        gdal.Warp(tmpds, src, options=gdal.WarpOptions(**kw))
        tmp = tmpds.GetRasterBand(1).ReadAsArray().astype("float32")
        fill = np.isnan(dst) & ~np.isnan(tmp)
        dst[fill] = tmp[fill]
        log.info("  read %s%s", path, f" (overview {ovl})" if ovl is not None else "")
        return True
    except Exception as e:  # missing tile (ocean, no data) or network error
        log.warning("  could not read %s: %s", path, e)
        return False


def get_corrections(c: dict, grid: Grid, check_cancel=None):
    """c = cfg['corrections']. Returns (landcover or None, chm or None, meta)."""
    meta = {"mode": c["mode"], "landcover_sources": [], "chm_sources": []}
    if c["mode"] == "none":
        log.info("Corrections: none (DEM used as is)")
        return None, None, meta
    lc = np.full(grid.shape, np.nan, dtype="float32")
    chm = np.full(grid.shape, np.nan, dtype="float32")
    if c["mode"] == "local":
        if c.get("landcover_path"):
            warp_into(c["landcover_path"], lc, grid, "nearest", remote=False)
            meta["landcover_sources"].append(c["landcover_path"])
        if c.get("chm_path"):
            warp_into(c["chm_path"], chm, grid, "average", remote=False)
            meta["chm_sources"].append(c["chm_path"])
    elif c["mode"] == "download":
        bll = grid_bounds_ll(grid)
        with cloud_env():
            log.info("Fetching ESA WorldCover tiles ...")
            for t in worldcover_tiles(bll):
                if check_cancel:
                    check_cancel()
                url = c["worldcover_url"].format(tile=t)
                if warp_into(url, lc, grid, "nearest", remote=True, nodata_override=0):
                    meta["landcover_sources"].append(url)
            log.info("Fetching canopy height tiles ...")
            for qk in chm_quadkeys(bll, int(c["chm_quadkey_zoom"])):
                if check_cancel:
                    check_cancel()
                url = c["chm_url"].format(quadkey=qk)
                if warp_into(url, chm, grid, "average", remote=True):
                    meta["chm_sources"].append(url)
    else:
        raise ValueError(f"unknown corrections mode: {c['mode']}")

    if not meta["landcover_sources"]:
        log.warning("No land cover available: k_default applied everywhere, no class masking.")
        lc = None
    if meta["chm_sources"]:
        chm = np.clip(chm, 0, float(c["chm_max_m"]))
        chm[chm < float(c["chm_min_m"])] = 0.0
    else:
        log.warning("No canopy height available.")
        chm = None
    fb = {int(k): float(v) for k, v in (c.get("chm_fallback_m") or {}).items()}
    if lc is not None and fb:
        if chm is None:
            chm = np.zeros(grid.shape, dtype="float32")
            meta["chm_fallback_used"] = "all"
        gaps = np.isnan(chm)
        for cls, h in fb.items():
            chm[gaps & (lc == cls)] = h
        chm[np.isnan(chm)] = 0.0
    elif chm is not None:
        chm[np.isnan(chm)] = 0.0
    return lc, chm, meta
