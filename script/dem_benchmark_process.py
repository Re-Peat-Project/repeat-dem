"""Step 04 of the DEM benchmark: every candidate through the repeat-dem method (ICESat-2 class offsets + smoothing).

    python script/dem_benchmark_process.py benchmark/mendahara.yaml [--only deltadtm klhk_modelled]

For each candidate in the benchmark config this writes <out>/04_processed/<name>/config.yaml (out: the benchmark folder in the KHG work folder) (the
full demnas_dtm config used, so the run can be repeated from that folder alone) and runs script/tiled_dtm.py with it.
The AOI is the KHG boundary (00_inputs/aoi_khg.gpkg), the DEM is the candidate VRT from step 01, land cover (WorldCover) and canopy
height (Meta/WRI) are the curated tiles in $REPEAT_DATA, ground points the curated ICESat-2 file. The lidar is not read here. Then rerun script/dem_benchmark.py to score the
processed surfaces next to the raw ones.
"""
import argparse
import copy
import glob
import os
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
import demnas_dtm as dd  # noqa: E402
sys.path.insert(0, str(HERE))
from dem_benchmark import out_dir, write_vrt  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--strip-rows", type=int, default=2000)
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    data = Path(os.environ.get("REPEAT_DATA") or REPO.parent / "_data")
    site = out_dir(cfg)
    if not (site / "01_candidates").exists():
        sys.exit(f"run script/dem_benchmark.py {a.config} first (step 01 builds the candidate VRTs)")
    aoi = site / "00_inputs" / "aoi_khg.gpkg"
    b = gpd.read_file(data / cfg["boundary"][0], layer=cfg["boundary"][1])
    b[b[cfg["boundary"][2]] == cfg["khg"]][[cfg["boundary"][2], "geometry"]].dissolve().to_file(aoi, driver="GPKG")
    p = cfg["processing"]
    chm_files = sorted(glob.glob(str(data / p["canopy"])))
    if not chm_files:
        sys.exit(f"no canopy height tiles match {p['canopy']}")
    chm_vrt = write_vrt(chm_files, site / "01_candidates" / "canopy_height_meta.vrt")
    for name in cfg["candidates"]:
        if a.only and name not in a.only:
            continue
        out = site / "04_processed" / name
        out.mkdir(parents=True, exist_ok=True)
        c = dd.deep_update(copy.deepcopy(dd.DEFAULTS), copy.deepcopy(p.get("config") or {}))
        c["dem"] = [str((site / "01_candidates" / f"{name}.vrt").resolve())]
        c["aoi"] = str(aoi.resolve())
        c["out"] = str(out.resolve())
        c["target_res_m"] = float(p["res_m"][name])
        if name in p.get("dtm_candidates", []):
            c["k_by_class"] = {k: 0.0 for k in c["k_by_class"]}
            c["k_default"] = 0.0
        # land cover and canopy height from the curated copies in $REPEAT_DATA (same sources as demnas_dtm's download mode)
        c["corrections"].update({"mode": "local", "landcover_path": str((site / "01_candidates" / "landcover_worldcover.vrt").resolve()),
                                 "chm_path": str(chm_vrt.resolve())})
        c["ground"]["source"] = "local"
        c["ground"]["local"].update({"path": str((data / p["ground_points"]).resolve()), "h_col": "h_ell", "source_col": "source",
                                     "time_col": "time", "height_is_ellipsoidal": True})
        cpath = out / "config.yaml"
        cpath.write_text(yaml.safe_dump(c, sort_keys=False), encoding="utf-8")
        print(f"## {name}: {c['target_res_m']:g} m -> {out}", flush=True)
        r = subprocess.run([sys.executable, str(HERE / "tiled_dtm.py"), "--config", str(cpath), "--strip-rows", str(a.strip_rows)],
                           stdout=open(out / "stdout.log", "w"), stderr=subprocess.STDOUT)
        print(f"   exit {r.returncode}; log {out / 'run.log'}", flush=True)


if __name__ == "__main__":
    main()
