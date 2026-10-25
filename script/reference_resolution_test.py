"""Is a ~25 m LiDAR reference fine enough? Test on the Pulau Padang 2 m LiDAR against its own block means.

    python script/reference_resolution_test.py [--block 12] [--out runs/checks/reference_resolution_padang.csv]

Averages the 2 m LiDAR DTM inside KHG Pulau Padang into blocks of --block x --block pixels (12 = 24 m, close to the
25 m KLHK LiDAR DEMs), using only blocks that lie fully inside the KHG with every pixel valid. Reports
- what a block reference loses: the spread of the 2 m heights inside each block (SD and max - min), and the share of
  blocks holding more than 1 m of relief (canals, ditches, embankments);
- what it keeps: the real height difference between block means 0.5, 1 and 2 km apart, over every pair of blocks along
  rows and columns (the same shifts as script/dem_benchmark.py).
The LiDAR is read in windows; nothing is held at full size. Output: one CSV of named values.
"""
import argparse
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import Window

REPO = Path(__file__).resolve().parents[1]
LIDAR = "lidar_pulau_padang_2016/DTM_2mFloat.tif"
KHG = "KHG Pulau Padang"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--block", type=int, default=12)
    ap.add_argument("--out", default=str(REPO / "runs" / "checks" / "reference_resolution_padang.csv"))
    a = ap.parse_args()
    data = Path(os.environ.get("REPEAT_DATA") or REPO.parent / "_data")
    F = a.block
    g = gpd.read_file(data / "batas_khg_indonesia.gpkg", layer="nama__khg__indonesia__2017__rev_tipologi")
    with rasterio.open(data / LIDAR) as d:
        geom = g[g.NAMA_KHG == KHG].to_crs(d.crs).union_all()
        res = abs(d.res[0])
        H, W = (d.height // F) * F, (d.width // F) * F
        mean = np.full((H // F, W // F), np.nan, np.float32)
        sd = np.full_like(mean, np.nan)
        rng = np.full_like(mean, np.nan)
        step = F * 256
        for r0 in range(0, H, step):
            for c0 in range(0, W, step):
                h, w = min(step, H - r0), min(step, W - c0)
                win = Window(c0, r0, w, h)
                z = d.read(1, window=win).astype("float64")
                z[(z == d.nodata) | (z < -100)] = np.nan
                z[~geometry_mask([geom], (h, w), d.window_transform(win), invert=True)] = np.nan
                b = z.reshape(h // F, F, w // F, F).transpose(0, 2, 1, 3).reshape(h // F, w // F, F * F)
                full = np.isfinite(b).all(-1)
                bb = np.where(full[..., None], b, 0.0)
                mu = bb.mean(-1)
                s = (r0 // F, c0 // F)
                sl = (slice(s[0], s[0] + h // F), slice(s[1], s[1] + w // F))
                mean[sl] = np.where(full, mu, np.nan)
                sd[sl] = np.where(full, np.sqrt(((bb - mu[..., None]) ** 2).mean(-1)), np.nan)
                rng[sl] = np.where(full, bb.max(-1) - bb.min(-1), np.nan)
    ok = np.isfinite(sd)
    rows = [("block_size_m", F * res), ("blocks_fully_inside", int(ok.sum())),
            ("within_block_sd_median_m", np.median(sd[ok])), ("within_block_sd_p90_m", np.percentile(sd[ok], 90)),
            ("within_block_sd_p99_m", np.percentile(sd[ok], 99)), ("within_block_range_median_m", np.median(rng[ok])),
            ("within_block_range_p90_m", np.percentile(rng[ok], 90)), ("share_blocks_range_gt_1m", float((rng[ok] > 1).mean()))]
    for L in (500, 1000, 2000):
        k = int(round(L / (F * res)))
        dz = np.concatenate([x[np.isfinite(x)] for x in (mean[:, k:] - mean[:, :-k], mean[k:, :] - mean[:-k, :])])
        rows.append((f"block_height_difference_rms_{L}m", float(np.sqrt(np.mean(dz ** 2)))))
        rows.append((f"block_pairs_{L}m", int(dz.size)))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=["name", "value"])
    df["value"] = df.value.map(lambda v: round(float(v), 4))
    df.to_csv(out, index=False)
    print(df.to_string(index=False))
    print("wrote", out)


if __name__ == "__main__":
    main()
