"""Algorithm 0 (DEMNAS download) against a local fake of BIG's tile index and download endpoints.

Run with QGIS's Python:  python tests/download_with_fake_server.py

Cuts two CRS-less tiles from _data_sample/DEMNAS_sebangau.tif around runs/aoi_window.gpkg, serves them
locally and checks: download in a worker thread, CRS assignment, clip, tile reuse, the HTML-error-page
guard, a bad link, and chaining into algorithm 1 (compared with runs/exp_base/dem_utm.tif).
It cannot test BIG's real server or a real login token.
"""
import sys, os, shutil, json, time, base64, threading, tempfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
from osgeo import gdal, ogr
gdal.UseExceptions()
OUT = tempfile.mkdtemp(prefix="demnas_dl_"); os.makedirs(os.path.join(OUT, "srv"))
SAMPLE = str(REPO / "_data_sample" / "DEMNAS_sebangau.tif")
AOI = str(REPO / "runs" / "aoi_window.gpkg")
REF = str(REPO / "runs" / "exp_base")

# AOI bbox in lon/lat, two tiles (left/right halves, padded), stripped of CRS like the real ones
src = ogr.Open(AOI); lyr = src.GetLayer(0); env = lyr.GetExtent()
from osgeo import osr
sr = lyr.GetSpatialRef(); sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER); ll = osr.SpatialReference(); ll.ImportFromEPSG(4326); ll.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
ct = osr.CoordinateTransformation(sr, ll); x0, y0, _ = ct.TransformPoint(env[0], env[2]); x1, y1, _ = ct.TransformPoint(env[1], env[3])
pad = 0.02; x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad; xm = (x0 + x1) / 2
boxes = {"1612-23": (x0, y0, xm, y1), "1612-24": (xm, y0, x1, y1)}
for nlp, (a, b, c, d) in boxes.items():
    p = OUT + rf"\srv\DEMNAS_{nlp}_v1.0.tif"
    gdal.Translate(p, SAMPLE, projWin=[a, d, c, b]); ds = gdal.Open(p, gdal.GA_Update); ds.SetProjection(""); ds = None
    print("tile", nlp, os.path.getsize(p) // 1024, "kB, has CRS:", bool(gdal.Open(p).GetProjection()))
FAKE_JWT = "e30." + base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + 3000}).encode()).decode().rstrip("=") + ".sig"
MODE = {"html": False}; HITS = []
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query); HITS.append(u.path)
        if u.path.endswith("/query"):
            feats = [{"attributes": {"Name": f"DEMNAS_{n}_v1.0"}, "geometry": {"rings": [[[a, b], [a, d], [c, d], [c, b], [a, b]]]}} for n, (a, b, c, d) in boxes.items()]
            body = json.dumps({"features": feats}).encode(); ctype = "application/json"
        elif u.path.endswith("/unduh/demnas"):
            if MODE["html"]: body = b"<html>token expired</html>"; ctype = "text/html"
            else: body = open(OUT + r"\srv\\" + q["filename"][0], "rb").read(); ctype = "image/tiff"
        else: self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
srv = ThreadingHTTPServer(("127.0.0.1", 0), H); port = srv.server_address[1]; threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{port}"; LINK = f"{BASE}/api-inageo/unduh/demnas?token={FAKE_JWT}&filename=DEMNAS_0917-14_v1.0.tif"

from qgis.core import QgsApplication, QgsProject, QgsVectorLayer, QgsProcessingContext, QgsProcessingFeedback, QgsProcessingAlgRunnerTask, QgsProcessingUtils, Qgis
app = QgsApplication([], False); app.initQgis()
sys.path.append(os.path.join(QgsApplication.prefixPath(), 'python', 'plugins'))  # for `processing`
from processing.core.Processing import Processing
Processing.initialize()
import demnas_dtm_qgis
PLUGIN = demnas_dtm_qgis.classFactory(None); PLUGIN.initProcessing()
print("QGIS", Qgis.version())
REG = QgsApplication.processingRegistry(); prj = QgsProject.instance()
aoi = QgsVectorLayer(AOI, "AOI", "ogr"); prj.addMapLayer(aoi)
class FB(QgsProcessingFeedback):
    def __init__(s): super().__init__(); s.msgs = []
    def pushInfo(s, m): s.msgs.append("info: " + m)
    def pushWarning(s, m): s.msgs.append("WARN: " + m)
    def reportError(s, m, fatal=False): s.msgs.append("ERROR: " + m)
def run(alg_id, params):
    ctx = QgsProcessingContext(); ctx.setProject(prj); fb = FB(); alg = REG.createAlgorithmById(alg_id); done = {}
    task = QgsProcessingAlgRunnerTask(alg, params, ctx, fb); task.executed.connect(lambda ok, res: done.update(ok=ok, res=res))
    QgsApplication.taskManager().addTask(task); t0 = time.time()
    while "ok" not in done and time.time() - t0 < 300: QgsApplication.processEvents(); time.sleep(0.05)
    assert "ok" in done, "timed out"
    return done["ok"], done["res"], ctx, fb.msgs
def rd(p):
    ds = gdal.Open(p); b = ds.GetRasterBand(1); a = b.ReadAsArray().astype("float64"); nd = b.GetNoDataValue()
    if nd is not None: a[a == nd] = np.nan
    return ds, a

base = {"INPUT": aoi.id(), "LINK": LINK, "SERVICE": BASE, "DELAY": 0.0}
ok, res, ctx, msgs = run("demnas_dtm:download_demnas", {**base, "OUT_DIR": OUT + r"\d1"})
print("run 1 ok:", ok, "| result:", os.path.basename(res.get("OUT_DEM", "")) if res else res)
for m in msgs:
    if "Tile" in m or "CRS" in m or "WARN" in m or "ERROR" in m or "valid" in m: print("  ", m[:200])
print("  tiles saved:", sorted(os.listdir(OUT + r"\d1\tiles")), "| layers to load:", [d.name for d in ctx.layersToLoadOnCompletion().values()])
ds, a = rd(OUT + r"\d1\demnas_clipped.tif"); print("  output:", ds.RasterXSize, "x", ds.RasterYSize, "| CRS:", ds.GetSpatialRef().GetAuthorityCode(None), "| nodata:", ds.GetRasterBand(1).GetNoDataValue(), "| finite share %.2f" % np.isfinite(a).mean())
full = gdal.Open(SAMPLE); gt = ds.GetGeoTransform(); fg = full.GetGeoTransform()
c0 = int(round((gt[0] - fg[0]) / fg[1])); r0 = int(round((gt[3] - fg[3]) / fg[5]))
ref = full.GetRasterBand(1).ReadAsArray(c0, r0, ds.RasterXSize, ds.RasterYSize).astype("float64")
both = np.isfinite(a) & np.isfinite(ref); print("  values vs the original sample over the clip: max|d| =", float(np.abs(a - ref)[both].max()), "on", int(both.sum()), "cells")
# rerun with the tiles folder given: tiles are reused, no downloads
hits0 = sum(1 for h in HITS if h.endswith("/unduh/demnas"))
ok, res, ctx, msgs = run("demnas_dtm:download_demnas", {**base, "OUT_DIR": OUT + r"\d2", "TILE_FOLDER": OUT + r"\d1\tiles"})
print("run 2 (tile folder reused) ok:", ok, "| new downloads:", sum(1 for h in HITS if h.endswith("/unduh/demnas")) - hits0, "|", [m[:90] for m in msgs if "already in" in m])
# error page instead of a tile
MODE["html"] = True
ok, res, ctx, msgs = run("demnas_dtm:download_demnas", {**base, "OUT_DIR": OUT + r"\d3"}); print("run 3 (server returns an HTML page) ok:", ok, "|", [m[:160] for m in msgs if m.startswith("ERROR")])
MODE["html"] = False
ok, res, ctx, msgs = run("demnas_dtm:download_demnas", {**base, "LINK": "https://example.org/x?token=abc", "OUT_DIR": OUT + r"\d4"}); print("run 4 (bad link) ok:", ok, "|", [m[:160] for m in msgs if m.startswith("ERROR")])
# chain into algorithm 1 and compare with the CLI-prepared DEM
ok, res, ctx, msgs = run("demnas_dtm:prepare_inputs", {"DEM": [OUT + r"\d1\demnas_clipped.tif"], "AOI": aoi.id(), "RES": 8, "MODE": 2, "OUT_DIR": OUT + r"\p"})
print("chain into alg 1 ok:", ok, [m[:140] for m in msgs if m.startswith("ERROR")])
if ok:
    _, n = rd(OUT + r"\p\dem_utm.tif"); _, r_ = rd(REF + r"\dem_utm.tif")
    if n.shape == r_.shape:
        both = np.isfinite(n) & np.isfinite(r_); d = np.abs(n - r_)[both]; print("  dem_utm vs CLI's on the same grid: finite", int(np.isfinite(n).sum()), int(np.isfinite(r_).sum()), "| max|d| %.3g" % d.max(), "| mean|d| %.3g" % d.mean())
    else: print("  grid differs", n.shape, r_.shape)
app.exitQgis(); srv.shutdown(); shutil.rmtree(OUT, ignore_errors=True)
