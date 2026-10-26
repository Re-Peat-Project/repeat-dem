"""Step 05 of the DEM benchmark: the site's pipeline (delineation, neraca air) with only the DTM changed.

    python script/dem_benchmark_pipeline.py benchmark/sugihan_lumpur.yaml [--only lidar deltadtm__processed]

Reads the tracked site configs (pipeline.site_configs: delineate.yaml, neraca.yaml), substitutes ${REPEAT_KHG} and
${REPEAT_DATA}, changes only the DTM, the output folder and the delineation cache, and writes the variant configs next to
their outputs in <out>/05_pipeline/<variant>/ (out: the benchmark folder in the KHG work folder). Each module runs in its own checkout and environment
(../repeat-delineation/.venv, ../repeat-neraca/.venv). Neraca runs every variant on the sub-KHG units of
pipeline.units_from (the lidar), so differences come from the terrain alone. Then compares:
  05_pipeline/delineation_compare.csv   units per variant, and agreement with the lidar units (best-match IoU, share of
                                        the KHG area in matched overlap)
  05_pipeline/neraca_compare.csv        neraca_khg.csv of every variant side by side
  05_pipeline/neraca_unit_compare.csv   per-unit numeric outputs against the lidar run: difference, rank correlation
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WS = REPO.parent
sys.path.insert(0, str(HERE))
from dem_benchmark import out_dir  # noqa: E402


def load_sub(path, env):
    txt = Path(path).read_text(encoding="utf-8")
    txt = re.sub(r"\$\{(\w+)\}", lambda m: env.get(m.group(1), m.group(0)), txt)
    return yaml.safe_load(txt)


def run(cmd, cwd, log):
    with open(log, "w", encoding="utf-8") as f:
        r = subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT)
    return r.returncode


def iou_compare(ref, other, khg_area):
    ref = ref.to_crs(ref.estimate_utm_crs()); other = other.to_crs(ref.crs)
    ious, inter_sum = [], 0.0
    for g in ref.geometry:
        best, bi = 0.0, 0.0
        for h in other.geometry[other.intersects(g)]:
            i = g.intersection(h).area
            u = g.union(h).area
            if u and i / u > best:
                best, bi = i / u, i
        ious.append(best)
        inter_sum += bi
    return float(np.mean(ious)), float(np.median(ious)), inter_sum / khg_area


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--no-neraca", action="store_true", help="delineation only")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    p = cfg["pipeline"]
    data = Path(os.environ.get("REPEAT_DATA") or WS / "_data").resolve()
    site = out_dir(cfg)
    base = site / "05_pipeline"
    base.mkdir(parents=True, exist_ok=True)
    env = {"REPEAT_KHG": Path(os.environ["REPEAT_KHG"]).resolve().as_posix(), "REPEAT_DATA": data.as_posix()}
    sc = REPO / p["site_configs"]
    dl_py, nr_py = WS / "repeat-delineation" / ".venv" / "Scripts" / "python.exe", WS / "repeat-neraca" / ".venv" / "Scripts" / "python.exe"

    def dtm_path(v):
        rel = p["variants"][v]
        if rel == "flat":   # control: a constant surface on the grid of the lidar variant, so only the mapped channels shape the units
            f = base / v / "flat_dtm.tif"
            if not f.exists():
                import rasterio
                f.parent.mkdir(parents=True, exist_ok=True)
                with rasterio.open(dtm_path(p["units_from"])) as d:
                    a = d.read(1, masked=True)
                    prof = d.profile | {"dtype": "float32", "nodata": -9999.0, "compress": "deflate"}
                    with rasterio.open(f, "w", **prof) as o:
                        o.write(np.where(a.mask, -9999.0, 5.0).astype("float32"), 1)
            return str(f.resolve())
        f = site / rel if rel.startswith(("01_", "02_", "04_", "05_")) else data / rel
        if not f.exists():
            sys.exit(f"{v}: {f} not found (run step 04 first?)")
        return str(f.resolve())

    order = [p["units_from"]] + [v for v in p["variants"] if v != p["units_from"]]
    units_ref = base / p["units_from"] / "delineate" / "subkhg_units.gpkg"
    for v in order:
        if a.only and v not in a.only and v != p["units_from"]:
            continue
        out = base / v
        out.mkdir(parents=True, exist_ok=True)
        dc = load_sub(sc / "delineate.yaml", env)
        dc["rasters"]["dtm"] = dtm_path(v)
        dc["out"] = str((out / "delineate").resolve())
        dc["cache_dir"] = str((out / "delineate_cache").resolve())   # the cache is keyed by file name: one per variant
        (out / "delineate.yaml").write_text(yaml.safe_dump(dc, sort_keys=False), encoding="utf-8")
        if not (out / "delineate" / "subkhg_units.gpkg").exists():
            rc = run([str(dl_py), "-m", "repeat_delineation", "--config", str((out / "delineate.yaml").resolve())],
                     WS / "repeat-delineation", out / "delineate.log")
            print(f"{v}: delineation exit {rc}", flush=True)
        if a.no_neraca:
            continue
        nc = load_sub(sc / "neraca.yaml", env)
        nc["dtm"] = dtm_path(v)
        nc["units"] = str(units_ref.resolve())
        (out / "neraca.yaml").write_text(yaml.safe_dump(nc, sort_keys=False), encoding="utf-8")
        rc = run([str(nr_py), "scripts/run_neraca.py", "--config", str((out / "neraca.yaml").resolve()), *p["neraca_args"],
                  "--out", str((out / "neraca").resolve())], WS / "repeat-neraca", out / "neraca.log")
        print(f"{v}: neraca exit {rc}", flush=True)

    # comparisons
    khg = gpd.read_file(load_sub(sc / "neraca.yaml", env)["khg"])
    khg_area = khg.to_crs(khg.estimate_utm_crs()).area.sum()
    ref_units = gpd.read_file(units_ref)
    rows, nk, nu = [], [], []
    ref_unit = pd.read_csv(base / p["units_from"] / "neraca" / "neraca_unit.csv") if (base / p["units_from"] / "neraca" / "neraca_unit.csv").exists() else None
    for v in p["variants"]:
        uf = base / v / "delineate" / "subkhg_units.gpkg"
        if uf.exists():
            u = gpd.read_file(uf)
            m_iou, med_iou, share = iou_compare(ref_units, u, khg_area)
            rows.append({"variant": v, "units": len(u), "mean_best_iou_vs_lidar": round(m_iou, 3),
                         "median_best_iou_vs_lidar": round(med_iou, 3), "khg_area_in_matched_overlap": round(share, 3)})
        kf = base / v / "neraca" / "neraca_khg.csv"
        if kf.exists():
            nk.append(pd.read_csv(kf).assign(variant=v))
        uf2 = base / v / "neraca" / "neraca_unit.csv"
        if uf2.exists() and ref_unit is not None:
            d = pd.read_csv(uf2)
            key = "unit_id" if "unit_id" in d else d.columns[0]
            j = ref_unit.merge(d, on=key, suffixes=("_lidar", ""))
            for c in d.select_dtypes("number").columns:
                if c + "_lidar" in j:
                    x, y = j[c + "_lidar"], j[c]
                    nu.append({"variant": v, "column": c, "units": len(j), "mean_abs_diff": round(float((y - x).abs().mean()), 4),
                               "spearman_vs_lidar": round(float(x.rank().corr(y.rank())), 3) if x.nunique() > 1 and y.nunique() > 1 else None})
    pd.DataFrame(rows).to_csv(base / "delineation_compare.csv", index=False)
    if nk:
        pd.concat(nk).to_csv(base / "neraca_compare.csv", index=False)
    pd.DataFrame(nu).to_csv(base / "neraca_unit_compare.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))
    print("wrote", base)


if __name__ == "__main__":
    main()
