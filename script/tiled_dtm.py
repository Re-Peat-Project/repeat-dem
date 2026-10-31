"""demnas_dtm.py in strips, for areas whose full-resolution grid does not fit in memory. Same method, same config.

    python script/tiled_dtm.py --config my_config.yaml [--strip-rows 2000]

Nothing is coarsened. The output grid is fixed once from the AOI (UTM, target_res_m), then processed in horizontal
strips of --strip-rows cells, each read with an overlap on both sides wide enough for every neighbourhood operation
(smoothing support, despike window, gap filling; at least 2 km). Two passes:
  1. per strip: DEM, land cover and canopy height on the strip grid; sample them at the ground points that fall in the
     strip core; then one k/bias fit over the whole AOI (demnas_dtm.fit_from_samples, as in the untiled run);
  2. per strip: correction with the fitted k/bias, masking, despike, smoothing and gap filling; the core rows go into
     the output rasters (dtm_smooth.tif, dtm_corrected.tif, dem_utm.tif, landcover.tif).
Validation at the held-out ground points and run_report.json as in demnas_dtm.py. Check against an untiled run on a
grid that fits (see --compare).
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.warp import Resampling, transform_bounds
from rasterio.windows import Window

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import demnas_dtm as dd  # noqa: E402
import ground_truth as gt  # noqa: E402

log = dd.log


def global_grid(cfg, aoi_ll):
    crs = rasterio.crs.CRS.from_string(dd.auto_utm(*aoi_ll.centroid.coords[0]) if cfg["target_crs"] == "auto-utm" else cfg["target_crs"])
    res = float(cfg["target_res_m"])
    x0, y0, x1, y1 = transform_bounds("EPSG:4326", crs, *aoi_ll.bounds, densify_pts=21)
    x0, y1 = math.floor(x0 / res) * res, math.ceil(y1 / res) * res
    W, H = math.ceil((x1 - x0) / res), math.ceil((y1 - y0) / res)
    return dd.Grid(crs, from_origin(x0, y1, res, res), W, H)


def sub_grid(grid, r0, r1):
    t = grid.transform
    return dd.Grid(grid.crs, rasterio.Affine(t.a, 0, t.c, 0, t.e, t.f + r0 * t.e), grid.width, r1 - r0)


def load_dem_into(cfg, grid, aoi_proj):
    dem = np.full((grid.height, grid.width), np.nan, dtype="float32")
    for p in cfg["dem"]:
        dd.warp_into(p, dem, grid, Resampling.bilinear, remote=False)
    lo, hi = cfg["dem_valid_range_m"]
    dem[(dem < lo) | (dem > hi)] = np.nan
    m = geometry_mask([aoi_proj], out_shape=dem.shape, transform=grid.transform, invert=True)
    dem[~m] = np.nan
    return dem, m


def strips(H, rows, pad):
    for c0 in range(0, H, rows):
        c1 = min(H, c0 + rows)
        yield c0, c1, max(0, c0 - pad), min(H, c1 + pad)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--strip-rows", type=int, default=2000)
    ap.add_argument("--grid-like", help="use the grid of this raster (e.g. an untiled run's dem_utm.tif, to check the tiling)")
    a = ap.parse_args()
    cfg = dd.load_config(argparse.Namespace(config=a.config, dem=None, aoi=None, out=None, peat_depth=None, res=None, crs=None,
                                            no_download=False, landcover=None, chm=None, ground=None, ground_points=None, datasets=None))
    out = Path(cfg["out"])
    out.mkdir(parents=True, exist_ok=True)
    dd.logging.basicConfig(level=dd.logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                           handlers=[dd.logging.FileHandler(out / "run.log", mode="w"), dd.logging.StreamHandler()])
    t_start = time.time()
    aoi_ll = dd.read_aoi(cfg["aoi"], cfg["aoi_buffer_m"])
    grid = global_grid(cfg, aoi_ll)
    if a.grid_like:
        with rasterio.open(a.grid_like) as gl:
            grid = dd.Grid(gl.crs, gl.transform, gl.width, gl.height)
    aoi_proj = gpd.GeoSeries([aoi_ll], crs=4326).to_crs(grid.crs).iloc[0]
    res = grid.res
    support_m = max([s.get("window_m", 0) * 1.5 + s.get("sigma_m", 0) * 4 for s in cfg["smoothing"]["steps"]] +
                    [cfg["mask"]["despike_window_m"] * 1.5]) * 2 + cfg["smoothing"]["fill_max_search_px"] * res
    pad = int(math.ceil(max(2000.0, support_m) / res))
    S = list(strips(grid.height, a.strip_rows, pad))
    log.info("grid %s %d x %d at %.1f m; %d strips of %d rows, overlap %d rows (%.0f m)",
             grid.crs, grid.width, grid.height, res, len(S), a.strip_rows, pad, pad * res)

    # pass 0: land cover and canopy height onto the global grid once (as demnas_dtm.get_corrections: nearest / average),
    # so the two passes below read them locally instead of fetching every strip twice
    if cfg["corrections"]["mode"] == "download":
        lp, cp = out / "landcover_input.tif", out / "canopy_height_input.tif"
        base_prof = {"driver": "GTiff", "width": grid.width, "height": grid.height, "count": 1, "crs": grid.crs,
                     "transform": grid.transform, "compress": "deflate", "tiled": True, "blockxsize": 512, "blockysize": 512,
                     "BIGTIFF": "IF_SAFER"}
        c = cfg["corrections"]
        with rasterio.open(lp, "w", **base_prof, dtype="uint8", nodata=0) as lo, \
                rasterio.open(cp, "w", **base_prof, dtype="float32", nodata=np.nan) as co:
            for i, (c0, c1, _, _) in enumerate(strips(grid.height, a.strip_rows, 0), 1):
                sg = sub_grid(grid, c0, c1)
                bll = dd.grid_bounds_ll(sg)
                lc = np.full((sg.height, sg.width), np.nan, dtype="float32")
                chm = np.full_like(lc, np.nan)
                with dd.gdal_cloud_env():
                    for t in dd.worldcover_tiles(bll):
                        dd.warp_into(c["worldcover_url"].format(tile=t), lc, sg, Resampling.nearest, remote=True, nodata_override=0)
                    for qk in dd.chm_quadkeys(bll, int(c["chm_quadkey_zoom"])):
                        src, remote = dd.chm_source(c, qk)
                        dd.warp_into(src, chm, sg, Resampling.average, remote=remote)
                w = Window(0, c0, grid.width, c1 - c0)
                lo.write(np.nan_to_num(lc, nan=0).astype("uint8"), 1, window=w)
                co.write(chm, 1, window=w)
                log.info("pass 0 strip %d: land cover and canopy height", i)
        c.update({"mode": "local", "landcover_path": str(lp), "chm_path": str(cp),
                  "fetched_from": {"worldcover_url": c["worldcover_url"], "chm_url": c["chm_url"]}})

    # pass 1: samples at ground points
    g = cfg["ground"]
    pts = gt.get_points(aoi_ll, g, out)
    x, y = gt.to_grid_xy(pts, grid)
    rows_pts = np.floor((y - grid.transform.f) / grid.transform.e).astype(np.int64)
    keys = ("dem", "chm", "lc", "edge", "vmask", "inside")
    samp = {k: np.full(len(pts), np.nan) for k in keys}
    samp["inside"] = np.zeros(len(pts), bool)
    has_lc = False
    for i, (c0, c1, p0, p1) in enumerate(S, 1):
        sel = (rows_pts >= c0) & (rows_pts < c1)
        if not sel.any():
            continue
        sg = sub_grid(grid, p0, p1)
        dem, _ = load_dem_into(cfg, sg, aoi_proj)
        lc, chm, _ = dd.get_corrections(cfg, sg)
        has_lc |= lc is not None
        s = dd.sample_for_calibration(cfg, sg, dem, lc, chm, None, x[sel], y[sel])
        for k in keys:
            if s.get(k) is not None:
                samp[k][sel] = s[k]
        log.info("pass 1 strip %d/%d: %d points sampled", i, len(S), int(sel.sum()))
        del dem, lc, chm
    calib, gpts, diag = dd.fit_from_samples(cfg, grid, pts, x, y, samp, has_lc, out)
    k_table, b_table, b_def = dict(cfg["k_by_class"]), dict(cfg["bias_by_class"]), cfg["bias_default"]
    if calib:
        for cls, e in calib["classes"].items():
            k_table[cls], b_table[cls] = e["k"], e["bias"]
        b_def = calib["bias_global"]["value"]

    # pass 2: correct, mask, smooth per strip; write the core rows
    prof = {"driver": "GTiff", "width": grid.width, "height": grid.height, "count": 1, "dtype": "float32", "crs": grid.crs,
            "transform": grid.transform, "nodata": np.nan, "compress": "deflate", "tiled": True, "blockxsize": 512,
            "blockysize": 512, "BIGTIFF": "IF_SAFER"}
    names = ["dtm_smooth", "dtm_corrected", "dem_utm"]
    outs = {n: rasterio.open(out / f"{n}.tif", "w", **prof) for n in names}
    lc_out = rasterio.open(out / "landcover.tif", "w", **(prof | {"dtype": "uint8", "nodata": 0}))
    excl_n = spike_n = cells = 0
    val_s = {n: np.full(len(pts), np.nan) for n in ("dem_raw", "dtm_calibrated", "dtm_smooth")}
    for i, (c0, c1, p0, p1) in enumerate(S, 1):
        sg = sub_grid(grid, p0, p1)
        dem, aoi_m = load_dem_into(cfg, sg, aoi_proj)
        lc, chm, _ = dd.get_corrections(cfg, sg)
        shape = dem.shape
        k_ = dd.class_lookup(lc, k_table, cfg["k_default"], shape)
        b_ = dd.class_lookup(lc, b_table, b_def, shape)
        dtm = (dem - ((k_ * chm if chm is not None else 0.0) + b_)).astype("float32")
        del k_, b_
        excl = np.zeros(shape, bool)
        if lc is not None:
            for cls in cfg["mask"]["landcover_classes"]:
                excl |= lc == int(cls)
        base = np.where(excl, np.nan, dtm)
        spikes = np.zeros(shape, bool)
        if cfg["mask"]["despike"]:
            ref = dd.coarse_median(base, sg, float(cfg["mask"]["despike_window_m"]))
            spikes = np.isfinite(base) & (np.abs(base - ref) > float(cfg["mask"]["despike_threshold_m"]))
            base[spikes] = np.nan
            del ref
        sm = dd.fill_gaps(dd.smooth(base, sg, cfg), int(cfg["smoothing"]["fill_max_search_px"]))
        sm[~aoi_m] = np.nan
        r0, r1 = c0 - p0, c1 - p0
        w = Window(0, c0, grid.width, c1 - c0)
        for n, arr in zip(names, (sm, dtm, dem)):
            outs[n].write(arr[r0:r1], 1, window=w)
        lc_out.write(np.nan_to_num(lc[r0:r1], nan=0).astype("uint8") if lc is not None else np.zeros((c1 - c0, grid.width), "uint8"), 1, window=w)
        excl_n += int((excl | spikes)[r0:r1].sum()); spike_n += int(spikes[r0:r1].sum()); cells += (c1 - c0) * grid.width
        sel = (rows_pts >= c0) & (rows_pts < c1)
        if sel.any():
            v = gt.sample_arrays(x[sel], y[sel], sg, {"dem_raw": dem, "dtm_calibrated": dtm, "dtm_smooth": sm})
            for n in val_s:
                val_s[n][sel] = v[n]
        log.info("pass 2 strip %d/%d done", i, len(S))
        del dem, lc, chm, dtm, base, sm, excl, spikes
    for o in list(outs.values()) + [lc_out]:
        o.close()

    validation = None
    if gpts is not None and len(gpts):
        for n in val_s:
            gpts["err_" + n] = val_s[n] - gpts["H"].to_numpy()
        gpts.to_file(out / "ground_points.gpkg", driver="GPKG")
        vsel = (gpts["split"] == "validation").to_numpy()
        if vsel.any():
            tab = gt.error_table(gpts["H"].to_numpy()[vsel], {n: val_s[n][vsel] for n in val_s}, gpts["lc"].to_numpy()[vsel], gt.WORLDCOVER_NAMES)
            tab.to_csv(out / "validation.csv", index=False)
            validation = tab[tab["class"] == "all"].to_dict(orient="records")
    report = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "runtime_s": round(time.time() - t_start, 1), "tiled": True,
              "strips": len(S), "strip_rows": a.strip_rows, "overlap_rows": pad,
              "grid": {"crs": grid.crs.to_string(), "res_m": res, "width": grid.width, "height": grid.height, "bounds": grid.bounds},
              "excluded_share": excl_n / max(cells, 1), "spike_share": spike_n / max(cells, 1), "calibration": calib,
              "datum_diagnostics": diag, "validation_all_classes": validation, "k_used": {k: float(v) for k, v in k_table.items()},
              "config": cfg}
    with open(out / "run_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    log.info("done in %.1f s -> %s", time.time() - t_start, out)


if __name__ == "__main__":
    main()
