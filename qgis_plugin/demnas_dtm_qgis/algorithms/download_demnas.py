"""Optional step 0: download DEMNAS tiles from BIG's Ina-Geoportal and clip them to an area.

Port of script/qgis_demnas_clip_download_helper.py into the plugin's base class (same logic).
The public ImageServer only serves a placeholder instead of heights, so the real GeoTIFF tiles
are fetched from tanahair.indonesia.go.id with the user's own session token."""
import base64
import json
import os
import re
import tempfile
import time
from urllib.parse import parse_qs, urlencode, urlparse

from osgeo import gdal
from qgis.PyQt.QtCore import QEventLoop, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import (QgsBlockingNetworkRequest, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsFeature, QgsFeatureRequest, QgsFileDownloader, QgsGeometry, QgsPointXY,
                       QgsProcessingException, QgsProcessingOutputFolder, QgsProcessingOutputRasterLayer,
                       QgsProcessingParameterBoolean, QgsProcessingParameterCrs, QgsProcessingParameterEnum,
                       QgsProcessingParameterExtent, QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFolderDestination, QgsProcessingParameterNumber,
                       QgsProcessingParameterString, QgsProcessingUtils, QgsVectorLayer)

from .base import DemnasAlgorithm
from .compat import NUM_DOUBLE, SRC_POLYGON

gdal.UseExceptions()

SERVICE_URL = "https://geoservices.big.go.id/raster/rest/services/DEMNAS/DEM_Indonesia/ImageServer"
TIFF_MAGIC = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")
NLP_RE = re.compile(r"(\d{4}-\d{2,3})")  # 1:50k = 2 digits, 1:25k = 3 digits
RESAMPLING = ["Nearest neighbour", "Bilinear", "Cubic"]


class DownloadDemnas(DemnasAlgorithm):
    NEEDS = ("osgeo",)
    OUTPUT_FILES = ("demnas_clipped.tif",)
    NAME = "download_demnas"
    TITLE = "0. Download DEMNAS from BIG (optional)"
    HELP = (
        "Downloads the real DEMNAS tiles from BIG's Ina-Geoportal (tanahair.indonesia.go.id) for the "
        "area of a polygon or extent and clips them to it. Skip this if you already have DEMNAS tiles.\n\n"
        "You must paste ONE fresh DEMNAS download link (it carries your login token, valid for about an "
        "hour). The token is reused for every tile. To get it: log in at tanahair.indonesia.go.id, open "
        "the DEMNAS download map, click any single tile and copy the URL that opens. Any tile works; the "
        "right ones are found from the area. The link is a credential: do not share it, and note that "
        "QGIS keeps run parameters in its Processing history.\n\n"
        "Give EITHER a boundary polygon OR an extent. The area is widened by a buffer (500 m by default, "
        "the margin algorithm 1 uses; set 0 for the exact area). Heights are in metres (EGM2008). Tiles are saved "
        "in a 'tiles' folder (or the folder you choose) and reused if they are already there.\n\n"
        "Result: demnas_clipped.tif in the output folder, in EPSG:4326 unless you pick another CRS "
        "(leave it empty when feeding algorithm 1, which reprojects to UTM itself). Use it as the DEM "
        "of algorithm 1."
    )

    def define(self):
        self.basic(QgsProcessingParameterFeatureSource("INPUT", "Boundary polygon (use this OR the extent)",
                                                       [SRC_POLYGON], optional=True))
        self.basic(QgsProcessingParameterExtent("EXTENT", "Or area by extent (canvas / layer / typed)", optional=True))
        self.basic(QgsProcessingParameterString("LINK", "DEMNAS download link (fresh, from Ina-Geoportal)"))
        self.basic(QgsProcessingParameterBoolean("CLIP", "Clip to the polygon shape (unchecked = keep whole tiles)",
                                                 defaultValue=True))
        self.basic(QgsProcessingParameterCrs("TARGET_CRS", "Reproject output to (empty = keep native EPSG:4326)", optional=True))
        self.out_dir_param()
        self.advanced(QgsProcessingParameterNumber("BUFFER", "Buffer around the area (m); keeps the margin algorithm 1 needs. 0 = exact area",
                                                   type=NUM_DOUBLE, defaultValue=500.0, minValue=0.0))
        self.advanced(QgsProcessingParameterEnum("RESAMPLING", "Resampling (only when reprojecting)", RESAMPLING, defaultValue=1))
        self.advanced(QgsProcessingParameterNumber("DELAY", "Pause between downloads (s)", type=NUM_DOUBLE,
                                                   defaultValue=2.0, minValue=0.0))
        self.advanced(QgsProcessingParameterString("VERSION", "Version suffix in tile filenames", defaultValue="v1.0"))
        self.advanced(QgsProcessingParameterNumber("NODATA", "Output NoData value", type=NUM_DOUBLE, defaultValue=-9999.0))
        self.advanced(QgsProcessingParameterFolderDestination(
            "TILE_FOLDER", "Folder to keep and reuse downloaded tiles (empty = 'tiles' in the output folder)",
            optional=True, createByDefault=False))
        self.advanced(QgsProcessingParameterString("SERVICE", "ImageServer URL (tile index)", defaultValue=SERVICE_URL))
        self.addOutput(QgsProcessingOutputFolder("OUT_DIR", "Output folder"))
        self.addOutput(QgsProcessingOutputRasterLayer("OUT_DEM", "DEMNAS clipped"))

    # ------------------------------------------------------------------ helpers
    def _wait(self):
        wait = self._delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _get(self, url, feedback, retries=3):
        """GET through the QGIS network stack (proxy and SSL settings apply)."""
        last = ""
        for attempt in range(1, retries + 1):
            if feedback.isCanceled():
                raise QgsProcessingException("Canceled")
            self._wait()
            req = QgsBlockingNetworkRequest()
            err = req.get(QNetworkRequest(QUrl(url)), True, feedback)
            if err == QgsBlockingNetworkRequest.ErrorCode.NoError:
                return req.reply().content().data()
            last = req.errorMessage()
            feedback.pushWarning(f"Request failed (attempt {attempt}/{retries}): {last}")
            time.sleep(4 * attempt)
        raise QgsProcessingException(f"Request failed: {last}")

    def _parse_link(self, link, feedback):
        """Token and download endpoint from the pasted URL (the token is never logged)."""
        link = link.strip().strip('"').strip("'")
        u = urlparse(link)
        if not u.scheme or "unduh" not in u.path:
            raise QgsProcessingException("That does not look like an Ina-Geoportal download link.")
        qs = parse_qs(u.query)
        token = (qs.get("token") or [""])[0]
        if not token:
            raise QgsProcessingException("No token found in the link.")
        endpoint = f"{u.scheme}://{u.netloc}{u.path}"
        try:  # read the (unverified) JWT expiry only to tell how much time is left
            pl = token.split(".")[1]
            pl += "=" * (-len(pl) % 4)
            exp = json.loads(base64.urlsafe_b64decode(pl)).get("exp")
            if exp:
                left = exp - time.time()
                if left <= 0:
                    raise QgsProcessingException("This token has expired: paste a fresh link.")
                feedback.pushInfo(f"Token valid for about {left / 60:.0f} more minute(s).")
        except QgsProcessingException:
            raise
        except Exception:
            feedback.pushWarning("Could not read the token expiry; continuing.")
        return token, endpoint

    def _query_tiles(self, service, bbox, feedback):
        """Footprint catalogue of the ImageServer: [(sheet number, QgsGeometry)] for primary rasters."""
        params = {"where": "Category = 1", "geometryType": "esriGeometryEnvelope", "inSR": 4326, "outSR": 4326,
                  "geometry": f"{bbox.xMinimum()},{bbox.yMinimum()},{bbox.xMaximum()},{bbox.yMaximum()}",
                  "spatialRel": "esriSpatialRelIntersects", "outFields": "Name", "returnGeometry": "true", "f": "json"}
        js = json.loads(self._get(f"{service}/query?{urlencode(params)}", feedback).decode("utf-8"))
        if "error" in js:
            raise QgsProcessingException(f"Tile-index query failed: {js['error']}")
        out, seen = [], set()
        for f in js.get("features", []):
            name = str(f.get("attributes", {}).get("Name", ""))
            m = NLP_RE.search(name)
            if not m or m.group(1) in seen:
                continue
            rings = f.get("geometry", {}).get("rings")
            if not rings:
                continue
            out.append((m.group(1), QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in ring] for ring in rings])))
            seen.add(m.group(1))
        if not out:
            raw = [str(f.get("attributes", {}).get("Name", "")) for f in js.get("features", [])]
            feedback.pushInfo(f"Raw Name values returned: {raw[:20]}")
            raise QgsProcessingException("No map-sheet numbers found in the tile index for this area "
                                         "(see the raw Name values in the log).")
        feedback.pushInfo("Tiles from index: " + ", ".join(sorted(seen)))
        return out

    def _download(self, endpoint, token, filename, dest, feedback, base, span):
        """Stream one tile to disk (no whole-file RAM buffer) and check it is really a GeoTIFF."""
        url = f"{endpoint}?{urlencode({'token': token, 'filename': filename})}"
        self._wait()
        tmp = dest + ".part"
        if os.path.exists(tmp):
            os.remove(tmp)
        loop = QEventLoop()
        state = {"ok": False, "err": []}
        try:
            dl = QgsFileDownloader(QUrl(url), tmp, delayStart=True)
        except TypeError:  # older constructor signature
            dl = QgsFileDownloader(QUrl(url), tmp, "", True)
        dl.downloadCompleted.connect(lambda *a: state.update(ok=True))
        dl.downloadError.connect(lambda errs: state["err"].extend(list(errs)))
        dl.downloadExited.connect(loop.quit)

        def progress(received, total):
            if feedback.isCanceled():
                dl.cancelDownload()
            elif span and total > 0:
                feedback.setProgress(base + span * received / total)

        dl.downloadProgress.connect(progress)
        dl.startDownload()
        loop.exec()

        def cleanup():
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

        if feedback.isCanceled():
            cleanup()
            raise QgsProcessingException("Canceled")
        if not state["ok"] or state["err"]:
            cleanup()
            raise QgsProcessingException(f"{filename}: download failed: {'; '.join(state['err']) or 'unknown error'}")
        with open(tmp, "rb") as fh:
            head = fh.read(4)
        if head not in TIFF_MAGIC:
            with open(tmp, "rb") as fh:
                snippet = fh.read(300).decode("utf-8", "replace")
            cleanup()
            raise QgsProcessingException(f"{filename}: not a GeoTIFF (token expired or tile missing?). Response: {snippet}")
        os.replace(tmp, dest)

    # ---------------------------------------------------------------- algorithm
    def do_run(self, parameters, context, feedback):
        import processing

        source = self.parameterAsSource(parameters, "INPUT", context)
        link = self.parameterAsString(parameters, "LINK", context)
        clip = self.parameterAsBoolean(parameters, "CLIP", context)
        target_crs = self.parameterAsCrs(parameters, "TARGET_CRS", context)
        resampling = self.parameterAsEnum(parameters, "RESAMPLING", context)
        version = self.parameterAsString(parameters, "VERSION", context).strip()
        nodata = self.parameterAsDouble(parameters, "NODATA", context)
        service = self.parameterAsString(parameters, "SERVICE", context).rstrip("/")
        self._delay = self.parameterAsDouble(parameters, "DELAY", context)
        self._last = 0.0

        out = self.out_dir(parameters, context, feedback)
        out_path = os.path.join(out, "demnas_clipped.tif")
        keep = self.parameterAsString(parameters, "TILE_FOLDER", context)
        tile_dir = keep if keep else os.path.join(out, "tiles")
        os.makedirs(tile_dir, exist_ok=True)

        token, endpoint = self._parse_link(link, feedback)
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        reproject = target_crs.isValid() and target_crs != wgs84

        # 1. area of interest in EPSG:4326
        rect = self.parameterAsExtent(parameters, "EXTENT", context, wgs84)
        if source is not None:
            if not rect.isEmpty():
                feedback.pushInfo("Both polygon and extent given; using the polygon.")
            xform = QgsCoordinateTransform(source.sourceCrs(), wgs84, context.transformContext())
            geoms = []
            for feat in source.getFeatures(QgsFeatureRequest().setNoAttributes()):
                g = feat.geometry()
                if g is None or g.isEmpty():
                    continue
                g = QgsGeometry(g)
                g.transform(xform)
                geoms.append(g)
            if not geoms:
                raise QgsProcessingException("Input layer has no geometries.")
            mask = QgsGeometry.unaryUnion(geoms)
            if not mask.isGeosValid():
                mask = mask.makeValid()
        elif not rect.isEmpty():
            mask = QgsGeometry.fromRect(rect)
        else:
            raise QgsProcessingException("Provide either a boundary polygon or an extent.")
        buffer_m = self.parameterAsDouble(parameters, "BUFFER", context)
        if buffer_m > 0:
            from ..core.prepare import buffered_aoi_ll
            mask = QgsGeometry.fromWkt(buffered_aoi_ll(mask.asWkt(), buffer_m))
        bbox = mask.boundingBox()
        feedback.pushInfo(f"Area extent (EPSG:4326): {bbox.toString(6)}")

        # 2. tiles that touch the area
        tiles = [(n, g) for n, g in self._query_tiles(service, bbox, feedback) if g.intersects(mask)]
        if not tiles:
            raise QgsProcessingException("No tiles intersect the area.")
        feedback.pushInfo(f"{len(tiles)} tile(s) to fetch: " + ", ".join(sorted(n for n, _ in tiles)))

        # 3. download (one token, reused)
        rasters = []
        for i, (nlp, _) in enumerate(sorted(tiles)):
            filename = f"DEMNAS_{nlp}_{version}.tif"
            dest = os.path.join(tile_dir, filename)
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                feedback.pushInfo(f"Tile {i + 1}/{len(tiles)}: {filename} (already in {tile_dir})")
            else:
                feedback.pushInfo(f"Tile {i + 1}/{len(tiles)}: {filename}")
                self._download(endpoint, token, filename, dest, feedback, 80.0 * i / len(tiles), 80.0 / len(tiles))
            rasters.append(dest)

        # 4. mosaic; the tiles ship without an embedded CRS, so assign EPSG:4326 (DEMNAS is geographic)
        work = tempfile.mkdtemp(prefix="demnas_", dir=QgsProcessingUtils.tempFolder())
        mosaic = os.path.join(work, "mosaic.vrt")
        gdal.BuildVRT(mosaic, rasters)
        ds = gdal.Open(mosaic, gdal.GA_Update)
        if ds is not None and not ds.GetProjectionRef():
            ds.SetProjection(wgs84.toWkt())
            feedback.pushInfo("Tiles had no CRS; assigned EPSG:4326 to the mosaic.")
        ds = None

        # 5. clip / reproject with the QGIS GDAL algorithms
        mask_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "aoi", "memory")
        mf = QgsFeature()
        mf.setGeometry(mask)
        mask_layer.dataProvider().addFeature(mf)
        mask_layer.updateExtents()
        opts = "COMPRESS=DEFLATE|PREDICTOR=3|TILED=YES|BIGTIFF=IF_SAFER"
        stage = mosaic
        child = dict(context=context, feedback=feedback, is_child_algorithm=True)
        feedback.pushInfo("Mosaicking, clipping and writing the output ...")
        if clip:
            dest = os.path.join(work, "clip.tif") if reproject else out_path
            processing.run("gdal:cliprasterbymasklayer", {
                "INPUT": stage, "MASK": mask_layer, "SOURCE_CRS": wgs84, "TARGET_CRS": None, "NODATA": nodata,
                "CROP_TO_CUTLINE": True, "KEEP_RESOLUTION": True, "MULTITHREADING": True, "DATA_TYPE": 0,
                "OPTIONS": opts, "OUTPUT": dest}, **child)
            stage = dest
        if reproject:
            processing.run("gdal:warpreproject", {
                "INPUT": stage, "SOURCE_CRS": wgs84, "TARGET_CRS": target_crs, "RESAMPLING": resampling,
                "NODATA": nodata, "DATA_TYPE": 0, "MULTITHREADING": True, "OPTIONS": opts, "OUTPUT": out_path}, **child)
        elif not clip:
            processing.run("gdal:translate", {"INPUT": stage, "DATA_TYPE": 0, "OPTIONS": opts, "OUTPUT": out_path}, **child)

        self.load(context, out_path, "DEMNAS clipped")
        feedback.pushInfo(f"Tiles are in {tile_dir}")
        feedback.setProgress(100)
        return {"OUT_DIR": out, "OUT_DEM": out_path}
