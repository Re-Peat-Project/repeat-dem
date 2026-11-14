"""Confidence intervals for the benchmark's height-difference scores: a block bootstrap over the error maps.

    python script/dem_benchmark_ci.py benchmark/mendahara.yaml

Reads the error maps of dem_benchmark.py (02_error_maps/<candidate>_minus_lidar.tif: candidate - lidar on the lidar grid) and
writes 03_metrics/height_difference_ci.csv and 03_metrics/height_difference_ci_paired.csv.

Why: the score (RMS of e(x+L) - e(x) over every pair of lidar cells L apart along rows and columns) uses millions of pairs,
but neighbouring pairs carry nearly the same error, so they are far from independent. Resampling single pairs would give
intervals far too narrow. Here the KHG is cut into square blocks; each pair belongs to the block of its first cell; the
blocks are resampled with replacement (as many as there are blocks with pairs), and the score is recomputed from the
pairs of the drawn blocks. The same draws are used for every candidate, so the difference between two candidates gets its
own interval (paired file). Settings come from the config's `uncertainty` section, written before any interval was computed:
block sizes (the first is the main one, the others a sensitivity check), number of draws, seed, interval level.

height_difference_ci.csv          candidate, baseline, block size, blocks, score, interval, share of draws under the tier A
                                  threshold
height_difference_ci_paired.csv   candidate minus the config's reference candidate: the score difference and its interval
                                  (an interval that excludes 0 means the two differ beyond the sampling noise of this KHG)
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import yaml  # noqa: E402
from dem_benchmark import out_dir  # noqa: E402


def block_sums(e: np.ndarray, k: int, b: int):
    """Per block of b x b cells: sum of squared height-difference errors and number of pairs, over row and column pairs k apart."""
    H, W = e.shape
    nbr, nbc = -(-H // b), -(-W // b)
    ss = np.zeros(nbr * nbc)
    n = np.zeros(nbr * nbc)
    rows, cols = np.mgrid[0:H, 0:W]
    for d, r, c in ((e[:, k:] - e[:, :-k], rows[:, :-k], cols[:, :-k]), (e[k:, :] - e[:-k, :], rows[:-k, :], cols[:-k, :])):
        ok = np.isfinite(d)
        idx = (r[ok] // b) * nbc + c[ok] // b
        ss += np.bincount(idx, weights=d[ok] ** 2, minlength=ss.size)
        n += np.bincount(idx, minlength=n.size)
    return ss, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    u = cfg.get("uncertainty")
    if not u:
        sys.exit("no `uncertainty` section in the config: write it before computing any interval")
    out = out_dir(cfg)
    maps = sorted(p for p in (out / "02_error_maps").glob("*_minus_lidar.tif"))
    if not maps:
        sys.exit("no error maps: run dem_benchmark.py first")
    errs = {}
    for p in maps:
        with rasterio.open(p) as r:
            e = r.read(1).astype("float64")
            res = r.res[0]
        e[e == -9999.0] = np.nan
        errs[p.name.removesuffix("_minus_lidar.tif")] = e
    ref = u.get("paired_reference")
    level = float(u.get("level", 0.95))
    lo_q, hi_q = 100 * (1 - level) / 2, 100 * (1 + level) / 2
    tier_a = float(cfg["criterion"]["tier_a_rms_m"])
    rng_seed = int(u.get("seed", 20261113))
    rows, paired = [], []
    for L_m in cfg["metrics"]["shifts_m"]:
        k = int(round(L_m / res))
        for b_m in u["block_m"]:
            b = int(round(b_m / res))
            sums = {c: block_sums(e, k, b) for c, e in errs.items()}
            used = np.flatnonzero(sum(n for _, n in sums.values()) > 0)          # blocks with pairs in any candidate
            rng = np.random.default_rng(rng_seed)
            draws = rng.choice(used, size=(int(u["draws"]), used.size), replace=True)
            boot = {}
            for c, (ss, n) in sums.items():
                tot_n = n[draws].sum(1)
                boot[c] = np.sqrt(ss[draws].sum(1) / np.where(tot_n > 0, tot_n, np.nan))
                score = float(np.sqrt(ss.sum() / n.sum()))
                rows.append({"candidate": c, "baseline_m": L_m, "block_m": b_m, "main": b_m == u["block_m"][0], "blocks": int(used.size),
                             "pairs": int(n.sum()), "rms_m": round(score, 3),
                             "ci_low_m": round(float(np.nanpercentile(boot[c], lo_q)), 3),
                             "ci_high_m": round(float(np.nanpercentile(boot[c], hi_q)), 3),
                             "share_draws_under_tier_a": round(float(np.mean(boot[c] <= tier_a)), 3) if L_m == cfg["criterion"]["baseline_m"] else None})
            if ref in boot:
                for c in boot:
                    if c == ref:
                        continue
                    d = boot[c] - boot[ref]
                    ss_c, n_c = sums[c]
                    ss_r, n_r = sums[ref]
                    paired.append({"candidate": c, "minus": ref, "baseline_m": L_m, "block_m": b_m, "main": b_m == u["block_m"][0],
                                   "difference_m": round(float(np.sqrt(ss_c.sum() / n_c.sum()) - np.sqrt(ss_r.sum() / n_r.sum())), 3),
                                   "ci_low_m": round(float(np.nanpercentile(d, lo_q)), 3), "ci_high_m": round(float(np.nanpercentile(d, hi_q)), 3),
                                   "share_draws_candidate_better": round(float(np.mean(d < 0)), 3)})
            print(f"baseline {L_m} m, blocks {b_m} m: {used.size} blocks", flush=True)
    m = out / "03_metrics"
    pd.DataFrame(rows).to_csv(m / "height_difference_ci.csv", index=False)
    pd.DataFrame(paired).to_csv(m / "height_difference_ci_paired.csv", index=False)
    print(f"wrote {m / 'height_difference_ci.csv'} and height_difference_ci_paired.csv")


if __name__ == "__main__":
    main()
