"""DEM benchmark against airborne lidar for one KHG: every candidate surface, every lidar cell, native resolution.

    python script/dem_benchmark.py benchmark/mendahara.yaml

Steps, each a numbered folder under the config's `out`, the KHG work folder _khg/<code>_<name>/01_dem/benchmark/
(open any of them in QGIS):
  00_inputs/manifest.csv      every input file with size, modified date and sha256
  01_candidates/<name>.vrt    the candidate as delivered (tiles mosaicked by reference into _data, no copy, no resampling)
  02_error_maps/<name>_minus_lidar.tif   candidate - lidar on the lidar grid (nearest candidate cell to each lidar cell
                              centre), and landcover_on_lidar_grid.tif (ESA WorldCover, nearest)
  03_metrics/pointwise.csv    per candidate and land-cover class: n, median, NMAD, mean, RMSE, p05, p95 of the error
             height_difference.csv  error of the height difference over each baseline: e(x+L) - e(x) for every pair of
                              valid cells L apart along rows and columns (RMS, NMAD), with the lidar's own height difference
                              (the signal) for scale
             variogram.csv    semivariance of the error by lag (same shifts)
             criterion.csv    the pass/fail test written in the config before any result
  README.md                   generated index with the main table
No vertical datum conversion: a constant offset shows in the median and cancels in NMAD and in all height differences.
"""
import argparse
import glob
import hashlib
import os
import sys
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import yaml
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WC = {10: "tree cover", 20: "shrubland", 30: "grassland", 40: "cropland", 50: "built-up", 60: "bare", 80: "water",
      90: "herbaceous wetland", 95: "mangroves"}


def out_dir(cfg):
    """The benchmark folder of a site: cfg["out"] with ${REPEAT_KHG} (default: the workspace _khg) and ${REPEAT_DATA} expanded."""
    os.environ.setdefault("REPEAT_KHG", str(REPO.parent / "_khg"))
    os.environ.setdefault("REPEAT_DATA", str(REPO.parent / "_data"))
    return Path(os.path.expandvars(cfg["out"]))


def sha256(p, buf=1 << 22):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(buf):
            h.update(b)
    return h.hexdigest()


def write_vrt(files, dest, assign_crs=None):
    """Mosaic VRT of same-grid tiles (first file wins where they overlap)."""
    srcs = [rasterio.open(f) for f in files]
    crs = CRS.from_user_input(assign_crs) if assign_crs else srcs[0].crs
    a, e = srcs[0].transform.a, srcs[0].transform.e
    x0 = min(s.bounds.left for s in srcs); x1 = max(s.bounds.right for s in srcs)
    y0 = min(s.bounds.bottom for s in srcs); y1 = max(s.bounds.top for s in srcs)
    W, H = round((x1 - x0) / a), round((y1 - y0) / -e)
    dt = {"float32": "Float32", "float64": "Float64", "int16": "Int16", "uint8": "Byte", "uint32": "UInt32"}[srcs[0].dtypes[0]]
    nod = srcs[0].nodata
    # Sheets with different nodata values (DEMNAS: none, NaN, 1.18e-38, -3.0): each source masks its own, the gaps stay NaN.
    mixed = len({repr(s.nodata) for s in srcs}) > 1 and dt.startswith("Float")
    parts = [f'<VRTDataset rasterXSize="{W}" rasterYSize="{H}">', f"<SRS>{escape(crs.to_wkt())}</SRS>",
             f"<GeoTransform>{x0!r}, {a!r}, 0, {y1!r}, 0, {e!r}</GeoTransform>", f'<VRTRasterBand dataType="{dt}" band="1">']
    if mixed:
        parts.append("<NoDataValue>nan</NoDataValue>")
    elif nod is not None and not np.isnan(nod):
        parts.append(f"<NoDataValue>{nod!r}</NoDataValue>")
    for s, f in zip(srcs, files):
        xo, yo = round((s.bounds.left - x0) / a), round((y1 - s.bounds.top) / -e)
        kind = "ComplexSource" if mixed else "SimpleSource"
        own = f"<NODATA>{s.nodata!r}</NODATA>" if mixed and s.nodata is not None and not np.isnan(s.nodata) else ""
        parts.append(f'<{kind}><SourceFilename relativeToVRT="0">{escape(str(Path(f).resolve()))}</SourceFilename>'
                     f"<SourceBand>1</SourceBand><SrcRect xOff=\"0\" yOff=\"0\" xSize=\"{s.width}\" ySize=\"{s.height}\"/>"
                     f'<DstRect xOff="{xo}" yOff="{yo}" xSize="{s.width}" ySize="{s.height}"/>{own}</{kind}>')
        s.close()
    parts += ["</VRTRasterBand>", "</VRTDataset>"]
    Path(dest).write_text("\n".join(parts), encoding="utf-8")
    return dest


def sample(path, x, y, src_crs, chunk=2_000_000):
    """Nearest cell of raster `path` at points (x, y) given in src_crs; NaN where outside or nodata.
    Points come in lidar row order, so each chunk is a strip and only that strip of the raster is read."""
    out = np.full(len(x), np.nan)
    with rasterio.open(path) as d:
        tr = Transformer.from_crs(src_crs, d.crs, always_xy=True)
        for i0 in range(0, len(x), chunk):
            sx, sy = tr.transform(x[i0:i0 + chunk], y[i0:i0 + chunk])
            w = from_bounds(np.nanmin(sx), np.nanmin(sy), np.nanmax(sx), np.nanmax(sy), d.transform).round_offsets().round_lengths()
            w = Window(w.col_off - 1, w.row_off - 1, w.width + 3, w.height + 3).intersection(Window(0, 0, d.width, d.height))
            a = d.read(1, window=w).astype("float32")
            bad = ~np.isfinite(a) | (a < -100) | (a > 1e4)
            if d.nodata is not None:
                bad |= a == d.nodata
            a[bad] = np.nan
            t = d.window_transform(w)
            ci = np.floor((sx - t.c) / t.a).astype(np.int64)
            ri = np.floor((sy - t.f) / t.e).astype(np.int64)
            ok = (ci >= 0) & (ri >= 0) & (ci < a.shape[1]) & (ri < a.shape[0])
            o = np.full(len(sx), np.nan)
            o[ok] = a[ri[ok], ci[ok]]
            out[i0:i0 + chunk] = o
    return out


def robust(v):
    v = v[np.isfinite(v)]
    if not v.size:
        return {"n": 0}
    med = np.median(v)
    return {"n": int(v.size), "median": round(float(med), 3), "nmad": round(float(1.4826 * np.median(np.abs(v - med))), 3),
            "mean": round(float(v.mean()), 3), "rmse": round(float(np.sqrt(np.mean(v * v))), 3),
            "p05": round(float(np.percentile(v, 5)), 2), "p95": round(float(np.percentile(v, 95)), 2)}


def shift_diffs(a, k):
    """a(x+k) - a(x) along columns and rows, for all pairs where both are finite."""
    d = [a[:, k:] - a[:, :-k], a[k:, :] - a[:-k, :]]
    v = np.concatenate([x[np.isfinite(x)].ravel() for x in d])
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    data = Path(os.environ.get("REPEAT_DATA") or REPO.parent / "_data")
    out = out_dir(cfg)
    dirs = {k: out / k for k in ("00_inputs", "01_candidates", "02_error_maps", "03_metrics")}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    t0 = datetime.now()

    # 00 inputs
    files = {"lidar": [data / cfg["lidar"]["path"]], "landcover": sorted(Path(p) for p in glob.glob(str(data / cfg["landcover"])))}
    for k, c in cfg["candidates"].items():
        files[k] = sorted(Path(p) for p in glob.glob(str(data / c["path"])))
        if not files[k]:
            sys.exit(f"{k}: no files match {c['path']}")
    man = [{"role": k, "path": p.relative_to(data).as_posix(), "bytes": p.stat().st_size,
            "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"), "sha256": sha256(p)}
           for k, ps in files.items() for p in ps]
    pd.DataFrame(man).to_csv(dirs["00_inputs"] / "manifest.csv", index=False)
    print(f"manifest: {len(man)} files", flush=True)

    # 01 candidates as VRT
    vrt = {}
    for k, c in cfg["candidates"].items():
        vrt[k] = write_vrt(files[k], dirs["01_candidates"] / f"{k}.vrt", c.get("assign_crs"))
    lc_vrt = write_vrt(files["landcover"], dirs["01_candidates"] / "landcover_worldcover.vrt")

    # lidar inside the KHG, full resolution
    b = gpd.read_file(data / cfg["boundary"][0], layer=cfg["boundary"][1])
    with rasterio.open(files["lidar"][0]) as L:
        geom = b[b[cfg["boundary"][2]] == cfg["khg"]].to_crs(L.crs).union_all()
        w = from_bounds(*geom.bounds, L.transform).round_offsets().round_lengths().intersection(Window(0, 0, L.width, L.height))
        z = L.read(1, window=w).astype("float64")
        bad = ~np.isfinite(z) | (z < -100) | (z > 1e4) | (z == L.nodata if L.nodata is not None else False)
        z[bad] = np.nan
        tf = L.window_transform(w)
        z[~geometry_mask([geom], z.shape, tf, invert=True)] = np.nan
        crs, res = L.crs, abs(L.res[0])
        prof = {"driver": "GTiff", "width": z.shape[1], "height": z.shape[0], "count": 1, "dtype": "float32", "crs": crs,
                "transform": tf, "nodata": -9999.0, "compress": "deflate", "tiled": True, "blockxsize": 256, "blockysize": 256}
    rr, cc = np.nonzero(np.isfinite(z))
    x, y = tf * (cc + 0.5, rr + 0.5)
    print(f"lidar: {len(rr):,} cells inside the KHG at {res:g} m", flush=True)

    lc = np.full(z.shape, np.nan)
    lc[rr, cc] = sample(lc_vrt, x, y, crs)
    with rasterio.open(dirs["02_error_maps"] / "landcover_on_lidar_grid.tif", "w", **(prof | {"dtype": "uint8", "nodata": 0})) as o:
        o.write(np.nan_to_num(lc, nan=0).astype("uint8"), 1)

    # references: the lidar as is, and (for the processed surfaces) the lidar smoothed exactly like them
    refs = {"lidar": z}
    proc = {}
    for k in cfg["candidates"]:
        f = out / "04_processed" / k / "dtm_smooth.tif"
        if f.exists():
            proc[f"{k}__processed"] = write_vrt([f], dirs["01_candidates"] / f"{k}__processed.vrt")
    if proc:
        sys.path.insert(0, str(REPO))
        import demnas_dtm as dd
        pc = dd.deep_update(__import__("copy").deepcopy(dd.DEFAULTS), (cfg.get("processing") or {}).get("config") or {})
        zm = np.where(np.isin(lc, [int(v) for v in pc["mask"]["landcover_classes"]]), np.nan, z).astype("float32")
        zs = dd.smooth(zm, dd.Grid(crs, tf, z.shape[1], z.shape[0]), pc)
        zs[~np.isfinite(z)] = np.nan
        refs["lidar_smoothed"] = zs.astype("float64")
        with rasterio.open(dirs["02_error_maps"] / "lidar_smoothed.tif", "w", **prof) as o:
            o.write(np.nan_to_num(zs, nan=-9999.0).astype("float32"), 1)
    surfaces = {**vrt, **proc}
    sig = {(r, L_m): shift_diffs(refs[r], int(round(L_m / res))) for r in refs for L_m in cfg["metrics"]["shifts_m"]}

    pw, hd, vg, crit = [], [], [], []
    for k, path in surfaces.items():
        s = np.full(z.shape, np.nan)
        s[rr, cc] = sample(path, x, y, crs)
        for ref in (["lidar"] if k in vrt else list(refs)):
            e = s - refs[ref]
            tag = "" if ref == "lidar" else "_vs_smoothed"
            with rasterio.open(dirs["02_error_maps"] / f"{k}_minus_lidar{tag}.tif", "w", **prof) as o:
                o.write(np.nan_to_num(e, nan=-9999.0).astype("float32"), 1)
                o.update_tags(candidate=str(path), reference=ref, meaning="candidate minus reference (m), no datum conversion")
            cover = 100 * np.isfinite(e).sum() / len(rr)
            row = {"candidate": k, "reference": ref}
            pw.append({**row, "class": "all", "cover_pct": round(cover, 1), **robust(e)})
            for code, name in WC.items():
                m = lc == code
                if m.sum() >= 1000:
                    pw.append({**row, "class": name, "cover_pct": round(100 * m.sum() / len(rr), 1), **robust(e[m])})
            for L_m in cfg["metrics"]["shifts_m"]:
                d = shift_diffs(e, int(round(L_m / res)))
                sg = sig[(ref, L_m)]
                hd.append({**row, "baseline_m": L_m, "pairs": int(d.size), "rms_m": round(float(np.sqrt(np.mean(d * d))), 3),
                           "nmad_m": round(float(1.4826 * np.median(np.abs(d - np.median(d)))), 3),
                           "reference_signal_rms_m": round(float(np.sqrt(np.mean(sg * sg))), 3)})
            for lag in cfg["metrics"]["variogram_lags_m"]:
                kk = int(round(lag / res))
                if 1 <= kk < min(z.shape):
                    d = shift_diffs(e, kk)
                    vg.append({**row, "lag_m": lag, "pairs": int(d.size), "semivariance_m2": round(float(0.5 * np.mean(d * d)), 4)})
            r1 = next(h for h in hd if h["candidate"] == k and h["reference"] == ref and h["baseline_m"] == cfg["criterion"]["baseline_m"])
            thr_b = cfg["criterion"]["tier_b_fraction_of_signal"] * r1["reference_signal_rms_m"]
            crit.append({**row, "rms_1km_m": r1["rms_m"], "tier_a_threshold_m": cfg["criterion"]["tier_a_rms_m"],
                         "tier_a_pass": r1["rms_m"] <= cfg["criterion"]["tier_a_rms_m"], "tier_b_threshold_m": round(thr_b, 3),
                         "tier_b_pass": r1["rms_m"] <= thr_b})
            nmad = next(p_ for p_ in pw if p_["candidate"] == k and p_["reference"] == ref and p_["class"] == "all")["nmad"]
            print(f"{k} vs {ref}: cover {cover:.0f}%, NMAD {nmad} m, 1 km height-difference RMS {r1['rms_m']} m", flush=True)

    m = dirs["03_metrics"]
    pd.DataFrame(pw).to_csv(m / "pointwise.csv", index=False)
    pd.DataFrame(hd).to_csv(m / "height_difference.csv", index=False)
    pd.DataFrame(vg).to_csv(m / "variogram.csv", index=False)
    pd.DataFrame(crit).to_csv(m / "criterion.csv", index=False)

    # README index
    P, H, C = pd.DataFrame(pw), pd.DataFrame(hd), pd.DataFrame(crit)
    lines = [f"# DEM benchmark: {cfg['khg']}", "", f"Generated by `script/dem_benchmark.py {a.config}` on {date.today()} "
             f"({(datetime.now() - t0).seconds} s). Reference: `{cfg['lidar']['path']}` ({res:g} m, {len(rr):,} cells inside the KHG). "
             "Do not edit; rerun. `__processed` = the candidate after step 04 (ICESat-2 class offsets and smoothing, "
             "script/dem_benchmark_process.py); `lidar_smoothed` = the lidar smoothed the same way.", ""]
    for ref in refs:
        sub = P[(P.reference == ref) & (P["class"] == "all")].set_index("candidate")
        hh = H[H.reference == ref].pivot(index="candidate", columns="baseline_m", values="rms_m")
        cc_ = C[C.reference == ref].set_index("candidate")
        sig1 = H[(H.reference == ref) & (H.baseline_m == cfg["criterion"]["baseline_m"])].reference_signal_rms_m.iloc[0]
        lines += [f"## Against `{ref}` (real height difference at {cfg['criterion']['baseline_m']} m: {sig1} m RMS)", "",
                  "| Candidate | Cover | Median (m) | NMAD (m) | p05..p95 (m) | " + " | ".join(f"Δh error {b_} m" for b_ in hh.columns) +
                  " | Tier A | Tier B |", "|---" * (7 + len(hh.columns)) + "|"]
        for k in sub.index:
            r = sub.loc[k]
            lines.append(f"| {k} | {r.cover_pct:g}% | {r['median']:+.2f} | {r.nmad:.2f} | {r.p05:.1f}..{r.p95:.1f} | " +
                         " | ".join(f"{hh.loc[k, b_]:.2f}" for b_ in hh.columns) +
                         f" | {'pass' if cc_.loc[k, 'tier_a_pass'] else 'fail'} | {'pass' if cc_.loc[k, 'tier_b_pass'] else 'fail'} |")
        lines.append("")
    lines += [f"Tier A: 1 km Δh error ≤ {cfg['criterion']['tier_a_rms_m']} m. Tier B: ≤ {cfg['criterion']['tier_b_fraction_of_signal']} × "
              "the reference's own 1 km height difference. Both written in the config before any result.", "",
              "Folders: `00_inputs/manifest.csv` (inputs with sha256), `01_candidates/*.vrt` (open in QGIS), "
              "`02_error_maps/*_minus_lidar*.tif` (candidate − reference, m), `03_metrics/*.csv`, `04_processed/<candidate>/` "
              "(demnas_dtm outputs and the exact config used)."]
    (out / "README.md").write_text(chr(10).join(lines), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
