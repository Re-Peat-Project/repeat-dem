"""Map the sub-KHG units of several pipeline variants side by side (step 05 of the DEM benchmark), with rivers and primary canals.

    python script/delineation_compare_map.py benchmark/sugihan_lumpur.yaml lidar lidar_smoothed_m300_g150 flat deltadtm_m300_g150

Writes <out>/05_pipeline/units_<variants>.png.
"""
import os
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dem_benchmark import out_dir  # noqa: E402

cfg = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
variants = sys.argv[2:]
base = out_dir(cfg) / "05_pipeline"
dc = yaml.safe_load(open(base / variants[0] / "delineate.yaml", encoding="utf-8"))
khg = gpd.read_file(dc["khg"])
crs = khg.estimate_utm_crs()
khg = khg.to_crs(crs)
canals = gpd.read_file(dc["vectors"]["canals"]).to_crs(crs)
field = dc["units"]["subkhg"].get("canal_class_field")
prim = canals[canals[field].isin(dc["units"]["subkhg"]["outlet_canal_classes"])] if field else canals
rivers = gpd.read_file(dc["vectors"]["rivers"]).to_crs(crs)
fig, axs = plt.subplots(1, len(variants), figsize=(5 * len(variants), 6.5), dpi=130)
for ax, v in zip(axs, variants):
    u = gpd.read_file(base / v / "delineate" / "subkhg_units.gpkg").to_crs(crs)
    u.plot(ax=ax, column="unit_id", cmap="tab20", linewidth=0, alpha=0.55)
    u.boundary.plot(ax=ax, color="#222222", linewidth=0.6)
    prim.plot(ax=ax, color="#d62728", linewidth=0.8)
    rivers.plot(ax=ax, color="#1f77b4", linewidth=1.0)
    khg.boundary.plot(ax=ax, color="#000000", linewidth=0.8)
    ax.set_title(f"{v} ({len(u)} units)", fontsize=10)
    ax.set_axis_off()
fig.text(0.5, 0.02, "red: primary canals (outlets)   blue: rivers   black lines: unit boundaries", ha="center", fontsize=9)
fig.tight_layout(rect=(0, 0.04, 1, 1))
dest = base / f"units_{'_vs_'.join(variants[:4])}.png"
fig.savefig(dest)
print("wrote", dest)
