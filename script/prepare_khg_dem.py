"""Clip the elevation sources of each KHG to its boundary, into its work folder: _khg/<code>_<name>/01_dem/inputs/.

    python script/prepare_khg_dem.py [--khg "KHG ..." ...] [--buffer-m 0]

For every KHG work folder (default: all folders in $REPEAT_KHG, which defaults to the workspace _khg) this writes
  lidar_<source>.tif   each airborne LiDAR DTM in _data that covers part of the KHG (LIDAR below); those in NO_CLIP are
                       only listed in the manifest with their source path
  deltadtm.tif         DeltaDTM v1.1 (the per-KHG window fetched with repeat_common.gee into dem/open/deltadtm/)
  demnas.tif           DEMNAS from the BIG sheets in dem/demnas_tiles/ (repeat_common.fetch_demnas); written only when every
                       sheet that touches the KHG is on disk, otherwise the manifest lists the missing sheets
  manifest.csv         per product: source files (with size and sha256), grid, coverage of the KHG, height range
Each output keeps its source's own grid, CRS and data type: the source window around the KHG is cut out and cells outside
the boundary (plus --buffer-m) are set to nodata. Nothing is reprojected or resampled. Rasters are read and written in
blocks, so a 2 m LiDAR DTM over a whole island fits in memory. DEMNAS sheets carry no CRS; EPSG:4326 is assigned.
Also writes the summary over all KHG to ../re-peat/sites/khg_dem_inputs.csv.
"""
import argparse
import hashlib
import math
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.crs import CRS
from rasterio.features import geometry_mask
from rasterio.windows import Window

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WS = REPO.parent
sys.path.insert(0, str(WS / "repeat-common" / "src"))
sys.path.insert(0, str(HERE))
from repeat_common import khg  # noqa: E402
from repeat_common.fetch_demnas import sheets_for  # noqa: E402
from dem_benchmark import write_vrt  # noqa: E402

BOUNDARY = ("batas_khg_indonesia.gpkg", "nama__khg__indonesia__2017__rev_tipologi", "NAMA_KHG")
LIDAR = {  # name in the output: path in _data. Duplicate copies are left out (DEM_25m_MUBA = the Deltares grid, the 50 m
    # Jambi resample, and the two non-UTM Sugihan-Saleh copies); see the data catalogue.
    "padang_2016_2m": "lidar_pulau_padang_2016/DTM_2mFloat.tif",
    "sugihan_saleh_2020_20m": "lidar_klhk/sugihan_saleh_2020/lidar_dtm/LIDAR__KHG_Sugihan_Saleh__20m__UTM_48S.tif",
    "jambi25m": "lidar_klhk/dem_25m/DEM25M/Jambi25m.tif",
    "muba25": "lidar_klhk/dem_25m/DEM25M/Muba25.tif",
    "deltares_berbak_muba_25m": "lidar_klhk/dem_25m/LiDAR_DTM_25.0m_BerbakMuba_UTM48S_FINAL (Deltares, 16 Feb 2018)1.tif",
    "oki25": "lidar_klhk/dem_25m/DEM25M/OKI25.tif",
    "riau25m": "lidar_klhk/dem_25m/DEM25M/RIAU25m.tif",
    "kalbar25": "lidar_klhk/dem_25m/Kalbar25.tif",
}
NO_CLIP = {"padang_2016_2m": "14.10.01"}  # source: the KHG code it covers. Listed in the manifest with its source path, no clip written (owner's choice: use the source directly)
BLOCK = 4096
NODATA = -9999.0
COLS = ["khg", "folder", "product", "file", "sources", "source_mb", "source_sha256", "crs", "res_m", "dtype", "width", "height",
        "cover_pct", "z_p02", "z_p98", "note"]


def sha256(p, buf=1 << 22):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(buf):
            h.update(b)
    return h.hexdigest()


def clip(src_path, geom_ll, dest, assign_crs=None):
    """Cut the window around geom_ll out of src_path on its own grid, nodata outside geom_ll. Returns stats or None."""
    with rasterio.open(src_path) as d:
        crs = CRS.from_user_input(assign_crs) if assign_crs else d.crs
        geom = gpd.GeoSeries([geom_ll], crs=4326).to_crs(crs).iloc[0]
        t = d.transform
        x0, y0, x1, y1 = geom.bounds
        c0, c1 = max(0, math.floor((x0 - t.c) / t.a)), min(d.width, math.ceil((x1 - t.c) / t.a))
        r0, r1 = max(0, math.floor((y1 - t.f) / t.e)), min(d.height, math.ceil((y0 - t.f) / t.e))
        if c1 <= c0 or r1 <= r0:
            return None
        win = Window(c0, r0, c1 - c0, r1 - r0)
        wt = d.window_transform(win)
        dtype = d.dtypes[0]
        is_float = np.issubdtype(np.dtype(dtype), np.floating)
        nod = NODATA if is_float else d.nodata
        prof = {"driver": "GTiff", "width": int(win.width), "height": int(win.height), "count": 1, "dtype": dtype, "crs": crs,
                "transform": wt, "nodata": nod, "compress": "deflate", "tiled": True, "blockxsize": 512, "blockysize": 512,
                "BIGTIFF": "IF_SAFER"}
        if is_float:
            prof["predictor"] = 3
        valid = inside = 0
        sample = []
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part.tif")
        with rasterio.open(tmp, "w", **prof) as o:
            for rr in range(0, int(win.height), BLOCK):
                for cc in range(0, int(win.width), BLOCK):
                    b = Window(cc, rr, min(BLOCK, int(win.width) - cc), min(BLOCK, int(win.height) - rr))
                    src_b = Window(c0 + cc, r0 + rr, b.width, b.height)
                    a = d.read(1, window=src_b)
                    m = geometry_mask([geom], (int(b.height), int(b.width)), o.window_transform(b), invert=True)
                    ok = m.copy()
                    af = a.astype("float64")
                    ok &= np.isfinite(af) & (af > -100) & (af < 1e4)
                    if d.nodata is not None and not (isinstance(d.nodata, float) and math.isnan(d.nodata)):
                        ok &= a != d.nodata
                    out = np.where(ok, a, nod).astype(dtype)
                    o.write(out, 1, window=b)
                    inside += int(m.sum())
                    valid += int(ok.sum())
                    if ok.any():
                        v = af[ok]
                        sample.append(v[:: max(1, v.size // 20000)])
            o.update_tags(source=str(src_path), clipped_to="KHG boundary from batas_khg_indonesia.gpkg", crs_assigned=str(bool(assign_crs)))
        os.replace(tmp, dest)
        v = np.concatenate(sample) if sample else np.array([])
        res = abs(t.a) * (111320 if crs.is_geographic else 1)
        return {"crs": crs.to_string(), "res_m": round(res, 2), "dtype": dtype, "width": int(win.width), "height": int(win.height),
                "cover_pct": round(100 * valid / inside, 1) if inside else 0.0,
                "z_p02": round(float(np.percentile(v, 2)), 2) if v.size else None, "z_p98": round(float(np.percentile(v, 98)), 2) if v.size else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--khg", nargs="*")
    ap.add_argument("--buffer-m", type=float, default=0.0, help="margin around the boundary kept in the clips (default 0)")
    a = ap.parse_args()
    data = Path(os.environ.get("REPEAT_DATA") or WS / "_data")
    b = gpd.read_file(data / BOUNDARY[0], layer=BOUNDARY[1])
    folders = [khg.folder(n) for n in a.khg] if a.khg else sorted(p for p in khg.root().iterdir() if p.is_dir())
    sheets_on_disk = {p.stem.split("_")[1]: p for p in (data / "dem" / "demnas_tiles").glob("DEMNAS_*.tif")}
    summary = []
    for fol in folders:
        r = khg.lookup(fol.name.split("_")[0])
        sel = b[b[BOUNDARY[2]].map(khg.norm) == khg.norm(r["name"])]
        if sel.empty:
            print(f"{fol.name}: boundary not found in {BOUNDARY[0]}", flush=True)
            continue
        utm = sel.estimate_utm_crs()
        geom = sel.to_crs(utm).buffer(a.buffer_m).to_crs(4326).union_all() if a.buffer_m else sel.to_crs(4326).union_all()
        out = fol / "01_dem" / "inputs"
        rows = []

        def record(product, sources, stats, note=""):
            srcs = [Path(s) for s in sources]
            rows.append({"khg": r["name"], "folder": fol.name, "product": product, "file": f"{product}.tif" if stats else "",
                         "sources": "; ".join(s.relative_to(data).as_posix() for s in srcs),
                         "source_mb": round(sum(s.stat().st_size for s in srcs) / 1e6, 1),
                         "source_sha256": "; ".join(sha256(s)[:16] for s in srcs) if stats else "", **(stats or {}), "note": note})
            print(f"{fol.name}: {product} {stats['cover_pct'] if stats else '-'}% {note}", flush=True)

        for name, rel in LIDAR.items():
            if name in NO_CLIP:
                if fol.name.split("_")[0] == NO_CLIP[name]:
                    record(f"lidar_{name}", [data / rel], None, "airborne LiDAR; not clipped, use the source file")
                (out / f"lidar_{name}.tif").unlink(missing_ok=True)
                continue
            s = clip(data / rel, geom, out / f"lidar_{name}.tif")
            if s and s["cover_pct"] >= 1:
                record(f"lidar_{name}", [data / rel], s, "airborne LiDAR")
            else:
                (out / f"lidar_{name}.tif").unlink(missing_ok=True)
        slug = "_".join(w.capitalize() for w in khg.slug(r["name"]).split("_"))
        dd = data / "dem" / "open" / "deltadtm" / f"deltadtm_v1-1_{slug}.tif"
        if dd.exists():
            record("deltadtm", [dd], clip(dd, geom, out / "deltadtm.tif"), "DeltaDTM v1.1 via Earth Engine; land below about 10 m +MSL only")
        else:
            record("deltadtm", [], None, f"missing: fetch {dd.relative_to(data).as_posix()} with repeat_common.gee")
        need = sheets_for(gpd.GeoSeries([geom], crs=4326).to_crs(utm).buffer(500).to_crs(4326).iloc[0])
        missing = [s for s in need if s not in sheets_on_disk]
        if missing:
            (out / "demnas.tif").unlink(missing_ok=True)
            record("demnas", [], None, f"missing {len(missing)} of {len(need)} BIG sheets: {' '.join(missing)} (repeat_common.fetch_demnas)")
        else:
            files = [sheets_on_disk[s] for s in need]
            vrt = write_vrt(files, out / "demnas_sheets.vrt", "EPSG:4326")
            record("demnas", files, clip(vrt, geom, out / "demnas.tif", assign_crs="EPSG:4326"), f"BIG DEMNAS, {len(files)} sheets; DSM")
        pd.DataFrame(rows, columns=COLS).to_csv(out / "manifest.csv", index=False)
        summary += rows
    s = pd.DataFrame(summary, columns=COLS)
    dest = WS / "re-peat" / "sites" / "khg_dem_inputs.csv"
    if a.khg and dest.exists():  # partial run: replace only these KHG
        old = pd.read_csv(dest)
        s = pd.concat([old[~old.folder.isin(s.folder)], s])
    s[COLS].to_csv(dest, index=False)
    print("wrote", dest)


if __name__ == "__main__":
    main()
