"""Check that script/tiled_dtm.py gives the same result as demnas_dtm.py, on a grid small enough for both.

    python script/check_tiling.py --config ../_khg/15.05-07-10.01_mendahara_batanghari/01_dem/benchmark/04_processed/glo30/config.yaml [--strip-rows 300]

Runs demnas_dtm.py once on the config (land cover and canopy height read from the files the config names, so both runs
use the same inputs), then tiled_dtm.py on the untiled run's exact grid (--grid-like its dem_utm.tif) in strips of
--strip-rows, and compares dem_utm, dtm_corrected and dtm_smooth cell by cell, plus the fitted tree-cover k and offset.
Writes <out>/tiling_check.csv (out defaults to a _tiling_check folder next to the config).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--strip-rows", type=int, default=300)
    ap.add_argument("--out")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    out = Path(a.out or Path(a.config).resolve().parent.parent / "_tiling_check")
    out.mkdir(parents=True, exist_ok=True)
    if cfg["corrections"]["mode"] == "download":
        sys.exit("use a config with local land cover and canopy height (both runs must read the same inputs)")
    runs = {}
    for name in ("untiled", "tiled"):
        c = dict(cfg, out=str((out / name).resolve()))
        p = out / f"{name}.yaml"
        p.write_text(yaml.safe_dump(c, sort_keys=False), encoding="utf-8")
        runs[name] = p
    with open(out / "untiled.log", "w") as f:
        subprocess.run([sys.executable, str(REPO / "demnas_dtm.py"), "--config", str(runs["untiled"])], stdout=f, stderr=subprocess.STDOUT, check=True)
    with open(out / "tiled.log", "w") as f:
        subprocess.run([sys.executable, str(HERE / "tiled_dtm.py"), "--config", str(runs["tiled"]), "--strip-rows", str(a.strip_rows),
                        "--grid-like", str(out / "untiled" / "dem_utm.tif")], stdout=f, stderr=subprocess.STDOUT, check=True)
    rows = []
    for n in ("dem_utm", "dtm_corrected", "dtm_smooth"):
        A = rasterio.open(out / "tiled" / f"{n}.tif").read(1)
        B = rasterio.open(out / "untiled" / f"{n}.tif").read(1)
        m = np.isfinite(A) & np.isfinite(B)
        d = np.abs(A[m] - B[m])
        rows.append({"layer": n, "same_shape": A.shape == B.shape, "cells": int(m.sum()),
                     "nan_mismatch": int((np.isfinite(A) != np.isfinite(B)).sum()), "max_abs_diff_m": float(d.max()) if d.size else None})
    for name in ("tiled", "untiled"):
        c = json.load(open(out / name / "run_report.json"))["calibration"]["classes"].get("10", {})
        rows.append({"layer": f"tree cover fit ({name})", "k": c.get("k"), "offset_m": c.get("bias")})
    pd.DataFrame(rows).to_csv(out / "tiling_check.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))
    print("wrote", out / "tiling_check.csv")


if __name__ == "__main__":
    main()
