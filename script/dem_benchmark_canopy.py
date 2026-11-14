"""Does the repeat-dem processing remove the canopy, or only shift the level? Error against canopy height under tree cover.

    python script/dem_benchmark_canopy.py benchmark/mendahara.yaml benchmark/sugihan_lumpur.yaml

For every candidate, as delivered and processed: the error (candidate - LiDAR, 02_error_maps) at every LiDAR cell in
WorldCover tree cover, against the Meta/WRI canopy height at that cell (the
canopy map the processing itself uses, averaged into each 25 m LiDAR cell as the processing averages it into its own grid).
If the processing removes the canopy, the error no longer grows with canopy height:
the slope goes to about zero. If it only shifts the level (the per-class offset), the slope stays.

Decision rule, written 2026-11-13 before any slope was computed: the processing counts as removing the canopy for a candidate
when the processed slope is within +-0.05 m per m of canopy height (5% of the canopy left) and is less than a quarter of the
delivered slope. Slope: least squares on the medians of 2 m canopy-height bins from 0 to 30 m (bins with >= 1,000 cells),
so that the many low-canopy cells do not dominate it.

Writes 01_dem/benchmark/10_canopy/: canopy_bins.csv (median, NMAD and count per bin), canopy_slopes.csv (slope per candidate,
the rule's verdict), and canopy_vs_error_<theme>.png.
"""
import argparse
import os
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import rasterio
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dem_benchmark import out_dir  # noqa: E402


def canopy_on_grid(cfg, shape, tf, crs):
    """Meta/WRI canopy height averaged into each cell of the LiDAR grid, tile by tile (local tiles of processing.canopy)."""
    import glob
    from rasterio.warp import Resampling, reproject, transform_bounds
    data = Path(os.environ.get("REPEAT_DATA") or HERE.parents[1] / "_data")
    H, W = shape
    gb = transform_bounds(crs, 4326, tf.c, tf.f + tf.e * H, tf.c + tf.a * W, tf.f)
    out = np.full(shape, np.nan, dtype="float32")
    n = 0
    for f in sorted(glob.glob(str(data / cfg["processing"]["canopy"]))):
        with rasterio.open(f) as r:
            b = transform_bounds(r.crs, 4326, *r.bounds)
            if b[0] > gb[2] or b[2] < gb[0] or b[1] > gb[3] or b[3] < gb[1]:
                continue
            tmp = np.full(shape, np.nan, dtype="float32")
            reproject(rasterio.band(r, 1), tmp, src_nodata=r.nodata, dst_transform=tf, dst_crs=crs, dst_nodata=np.nan,
                      resampling=Resampling.average)
            fill = np.isnan(out) & np.isfinite(tmp)
            out[fill] = tmp[fill]
            n += 1
    print(f"{cfg['site']}: canopy from {n} tiles", flush=True)
    return out

NAMES = {"glo30": "Copernicus GLO-30 (DSM)", "demnas": "DEMNAS", "fabdem": "FABDEM v1.2", "gedtm30": "GEDTM30 v1.1",
         "gem15": "GEM-15 DTM", "klhk_modelled": "KLHK modelled DTM", "deltadtm": "DeltaDTM v1.1"}
BINS = np.arange(0, 32, 2)
THEMES = {"light": {"bg": "white", "fg": "#222222", "grid": "#dddddd", "raw": "#9e9e9e", "proc": "#d6604d"},
          "dark": {"bg": "#16181c", "fg": "#e8e8e8", "grid": "#33363c", "raw": "#8a8a8a", "proc": "#f4a582"}}


def site(cfg_path):
    cfg = yaml.safe_load(open(cfg_path, encoding="utf-8"))
    out = out_dir(cfg)
    em = out / "02_error_maps"
    with rasterio.open(em / "landcover_on_lidar_grid.tif") as r:
        lc = r.read(1)
        tf, crs = r.transform, r.crs
    rr, cc = np.nonzero(lc == 10)
    chm = canopy_on_grid(cfg, lc.shape, tf, crs)[rr, cc]
    bins, slopes = [], []
    for name in NAMES:
        for tag, kind in (("", "as delivered"), ("__processed", "processed")):
            f = em / f"{name}{tag}_minus_lidar.tif"
            if not f.exists():
                continue
            with rasterio.open(f) as r:
                e = r.read(1)[rr, cc].astype("float64")
            e[e == -9999.0] = np.nan
            ok = np.isfinite(e) & np.isfinite(chm)
            idx = np.digitize(chm[ok], BINS) - 1
            mids, meds = [], []
            for i in range(len(BINS) - 1):
                v = e[ok][idx == i]
                if v.size >= 1000:
                    med = float(np.median(v))
                    bins.append({"site": cfg["site"], "candidate": name, "kind": kind, "canopy_m_from": BINS[i], "canopy_m_to": BINS[i + 1],
                                 "cells": int(v.size), "median_error_m": round(med, 3),
                                 "nmad_m": round(float(1.4826 * np.median(np.abs(v - med))), 3)})
                    mids.append(BINS[i] + 1)
                    meds.append(med)
            slope = float(np.polyfit(mids, meds, 1)[0]) if len(mids) >= 3 else np.nan
            slopes.append({"site": cfg["site"], "candidate": name, "kind": kind, "slope_m_per_m": round(slope, 3),
                           "bins": len(mids), "cells": int(ok.sum())})
    s = pd.DataFrame(slopes)
    w = s.pivot_table(index=["site", "candidate"], columns="kind", values="slope_m_per_m").reset_index()
    w["canopy_removed"] = (w["processed"].abs() <= 0.05) & (w["processed"].abs() < 0.25 * w["as delivered"].abs())
    dest = out / "10_canopy"
    dest.mkdir(exist_ok=True)
    pd.DataFrame(bins).to_csv(dest / "canopy_bins.csv", index=False)
    w.to_csv(dest / "canopy_slopes.csv", index=False)
    return cfg, pd.DataFrame(bins), w, dest, int(len(rr))


def plot(results, theme):
    th = THEMES[theme]
    cands = [c for c in NAMES if any(c in set(b.candidate) for _, b, _, _, _ in results)]
    fig, axes = plt.subplots(len(results), len(cands), figsize=(2.6 * len(cands), 2.9 * len(results) + 0.9), sharex=True, sharey=True,
                             squeeze=False)
    fig.patch.set_facecolor(th["bg"])
    for i, (cfg, b, w, _, n) in enumerate(results):
        for j, c in enumerate(cands):
            ax = axes[i, j]
            ax.set_facecolor(th["bg"])
            ax.tick_params(colors=th["fg"], labelsize=7)
            for sp in ax.spines.values():
                sp.set_color(th["grid"])
            ax.grid(color=th["grid"], lw=0.5)
            ax.axhline(0, color=th["fg"], lw=0.6, alpha=0.5)
            for kind, col in (("as delivered", th["raw"]), ("processed", th["proc"])):
                d = b[(b.candidate == c) & (b.kind == kind)]
                if len(d):
                    mid = (d.canopy_m_from + d.canopy_m_to) / 2
                    ax.fill_between(mid, d.median_error_m - d.nmad_m, d.median_error_m + d.nmad_m, color=col, alpha=0.15, lw=0)
                    ax.plot(mid, d.median_error_m, color=col, lw=1.6 if kind == "processed" else 1.1, marker="o", ms=2.5, label=kind)
            r = w[w.candidate == c]
            if len(r):
                r = r.iloc[0]
                txt = f"slope {r['as delivered']:+.2f} → {r['processed']:+.2f}" if np.isfinite(r.get("processed", np.nan)) else f"slope {r['as delivered']:+.2f}"
                ax.text(0.03, 0.95, txt, transform=ax.transAxes, va="top", fontsize=7, color=th["fg"])
            if i == 0:
                ax.set_title(NAMES[c], color=th["fg"], fontsize=8)
            if j == 0:
                ax.set_ylabel(f"{cfg['site']}\nerror vs LiDAR (m)", color=th["fg"], fontsize=8)
            if i == len(results) - 1:
                ax.set_xlabel("canopy height (m)", color=th["fg"], fontsize=8)
    axes[0, 0].legend(frameon=False, fontsize=7, labelcolor=th["fg"], loc="lower left")
    fig.suptitle("Does the processing remove the canopy? Error against canopy height, tree cover only", color=th["fg"],
                 fontsize=11, x=0.01, ha="left")
    fig.text(0.01, 0.945, "Median of candidate − LiDAR per 2 m canopy-height bin (Meta/WRI canopy map), band = ± NMAD. Slope in m "
             "of error per m of canopy. A flat processed line means the canopy is removed.", color=th["fg"], fontsize=8, alpha=0.8)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return fig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("configs", nargs="+")
    ap.add_argument("--theme", nargs="+", default=["light", "dark"])
    a = ap.parse_args()
    results = [site(c) for c in a.configs]
    for cfg, b, w, dest, n in results:
        print(f"{cfg['site']}: {n:,} tree-cover cells")
        print(w.to_string(index=False))
    for t in a.theme:
        fig = plot(results, t)
        for *_, dest, _ in results:
            fig.savefig(dest / f"canopy_vs_error_{t}.png", dpi=160, facecolor=THEMES[t]["bg"])
        plt.close(fig)
    print("wrote", ", ".join(str(r[3]) for r in results))


if __name__ == "__main__":
    main()
