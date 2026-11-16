# ICESat-2 and GEDI calibration points under canopy, and the canopy factor (2026-11-16)

Every number below is read from the files named; results live in the KHG work folders
(`_khg/<code>_<name>/01_dem/benchmark/11_ground_points/` and `01_dem/benchmark_is2ph10/`).

## Question

The repeat-dem processing removes only half to two-thirds of the canopy effect from the surface models
(`script/dem_benchmark_canopy.py`; GLO-30 slope +0.65 to +0.27 m per m of canopy at Mendahara, +0.41 to +0.12 at Sugihan-Lumpur).
Its canopy factor k is fitted to ICESat-2 ground points. Are those points too high under forest, and does filtering them fix k?

## Literature

Berninger & Siegert 2020 (Remote Sensing 12:4175) found ICESat-2 terrain in Central Kalimantan peat swamp forest up to 10 m
above an airborne DTM under closed canopy of about 30 m. Cobb et al. 2023 (Science of Remote Sensing 7:100074) cut ICESat-2
RMSE in Brunei peat from 3.85 to 0.77 m with strong beams at night and a spatial filter, and GEDI from 15.98 to 1.97 m with a
spatial filter. Two multi-site comparisons against airborne lidar (doi:10.1016/j.srs.2022.100067; doi:10.1016/j.rse.2021.112571)
found both missions degrade under canopy cover above 90%, and ICESat-2 better than GEDI for terrain.

## What we found

1. **A fetch bug.** `repeat_common.fetch_icesat2` meant to drop 100 m segments with fewer than 10 ground photons, but checked a
   column SlideRule does not return (`ground_photon_count`; it is `gnd_ph_count`), so every finite segment was kept in every
   point file fetched before 2026-11-16. Fixed in repeat-common `42a57cc`.
2. **SlideRule drops granules.** Re-fetching on 2026-11-16 gave very different answers for the same tile (13,625 and 31,632
   segments). Joining several fetches (`--passes`, `--merge`) reached 61,792 segments at Mendahara (90% of the October fetch)
   and 245,989 at Sugihan-Lumpur (92%).
3. **Under tall forest the uncut points are too high** (`script/ground_points_canopy.py`; median of point − LiDAR after one datum
   offset per site; `11_ground_points/ground_points_summary.csv`):

   | Points | Mendahara, canopy ≥ 15 m | slope (m per m) | Sugihan-Lumpur, canopy ≥ 15 m | slope |
   |---|---|---|---|---|
   | ICESat-2, as used until now | +1.39 m (NMAD 2.76) | +0.20 | +0.18 m (NMAD 0.69) | +0.009 |
   | ICESat-2, ≥ 10 ground photons | +0.03 m (NMAD 0.75) | 0.00 | +0.09 m (NMAD 0.59) | +0.006 |
   | + strong beams at night + spatial filter | +0.20 m (NMAD 0.75) | +0.02 | +0.15 m (NMAD 0.55) | +0.009 |
   | GEDI L2A (quality 1, sensitivity ≥ 0.98) | +1.08 m (NMAD 1.53) | +0.11 | −4.10 m (NMAD 6.05) | −0.19 |

   At Mendahara the uncut points sit +2.8 m (20 to 25 m canopy) and +6.5 m (25 to 35 m) above the LiDAR. The 10-photon cut alone
   removes this; strong beams, night and the spatial filter add little and discard about 70% of the points. GEDI is not usable
   here: its error under canopy is large and changes sign between the sites.
4. **Filtering does not fix k** (`benchmark/*_is2ph10.yaml`, rule written before the run: GLO-30 and DEMNAS canopy slopes
   within ±0.05). Recalibrated on the 10-photon points, the canopy slopes stayed at +0.30 and +0.13 (GLO-30), +0.11 and +0.21
   (DEMNAS); the 1 km scores moved by at most 0.03 m, inside their intervals; k under tree cover even fell slightly (GLO-30 0.44
   to 0.40 at Mendahara). The biased points were too few (5% of Mendahara's points lie under canopy of 15 m or more) to drive
   the fit.

## Decision (2026-11-16)

- Keep the fetch fix: new point files carry the 10-photon cut, which removes the canopy bias at no cost. The point files of the
  14 KHG run so far have no photon count; they are re-fetched in the national run.
- Do not use GEDI for calibration.
- Park the canopy fix for the surface models. The likely cause left is regression dilution (a noisy canopy map shrinks a
  point-by-point slope); the next step would be a binned-median or errors-in-variables fit of k. It matters only for KHG
  without DeltaDTM: 13 of the 343 KHG with mapped canals have less than 90% DeltaDTM cover (3,921 km²). DeltaDTM's error does not
  depend on canopy height, and its 1 km score was unchanged (0.64 and 0.46 m).
- For those 13 KHG, prefer GEDTM30: its canopy slope after processing is +0.03 to +0.05 m per m.
