# AGENTS.md: notes for whoever picks this repo up next

Last updated 2026-10-12. Read this first, then `README.md`, `docs/test-run-sebangau.md` and `docs/demnas-literature.md`.

## What this repo is, and why it is paused

`demnas_dtm.py` turns DEMNAS into a smoothed ground surface (`dtm_smooth.tif`) for the peat water-sharing "digital twin" (see the `re-peat` repo, methodology document and `docs/08-build-plan.md`). The pipeline works end to end on three real sites (Sebangau, Mendahara, Bengkalis). The **terrain accuracy is the open blocker**: the twin needs decimetre height differences over 0.5 to 2 km, and DEMNAS alone gives metres.

Work is paused until **airborne LiDAR (and ideally GNSS heights)** arrives. Until then, the twin is being built in `re-peat` against a synthetic testbed, so nothing here blocks that work. Do not spend more effort tuning k or smoothing on ICESat-2/GEDI alone; the three sites show it does not resolve the question.

## What we know (details in `docs/`)

- DEMNAS is a radar DSM (IFSAR, TerraSAR-X, ALOS PALSAR) blended toward stereo mass points. Canopy content and offset vary by source sheet. Published RMSE is 2.2 to 5.0 m at open-ground control points.
- Our smoothed RMSE against ICESat-2/GEDI is 1.2 to 2.8 m. No site meets the 0.25 m target in the methodology.
- Fitted tree-cover k is 0.04 to 0.21 at every site; the 0.8 prior is not supported.
- Median DEM − ground differs by site (−3.4, ≈0, +2.2 m). Sebangau open land sits about 4 m **below** lidar ground, which no paper explains.
- ICESat-2 and GEDI agree to about 0.25 m, but both use the same EGM2008 conversion, so a shared datum error cannot be excluded.

## Open questions the lidar should answer

1. **Datum or DEM error?** Does DEM − lidar show the same −4 m (Sebangau open land) as DEM − ICESat-2/GEDI? If yes, it is a DEMNAS property. If lidar agrees with DEMNAS, the satellite ground heights (or the shared geoid step) are wrong.
2. **Is the open-versus-forest height pattern real?** Lidar ground in open classes was 2 m higher than in forest, the DEM shows the reverse.
3. **Is the relative error small enough?** This is the decisive number for the twin (see below).
4. **Does the residual map to DEMNAS source sheets?** If so, calibrate per source area.
5. **Can a different base DEM beat DEMNAS?** FABDEM, Copernicus GLO-30, FathomDEM.

## Protocol when lidar is available

1. **Prepare the lidar DTM.** Record its vertical datum (ellipsoidal or orthometric, which geoid). Convert to the datum DEMNAS uses (EGM2008 per the papers; verify against DEMNAS metadata) with the same code path as the ground points. Record the acquisition year and apply the epoch shift (`ground.epoch`) if the lidar and DEMNAS years differ. Resample both to a common grid and keep the lidar as a held-out reference, never as a calibration input for the same evaluation.
2. **Compare at three sets of points:** lidar vs DEMNAS, lidar vs ICESat-2/GEDI, and DEMNAS vs ICESat-2/GEDI, by land-cover class and canopy height. This settles questions 1 and 2.
3. **Compute relative error.** A first pass against ICESat-2/GEDI exists: `script/relative_error.py` and the new section in `docs/test-run-sebangau.md` (smoothed-DTM error difference at 1 to 2 km is 1.1 to 2.6 m RMS at the three sites, against a 0.3 m head drop). Repeat it against the airborne lidar, and extend it for lidar-covered cells to:
   - detrended error (remove a low-order or 2 km-scale trend, then RMSE and NMAD of what remains);
   - slope error over 0.5, 1 and 2 km baselines;
   - the semivariogram of DEM − lidar (correlation length and sill);
   - the same for `dtm_corrected.tif` and `dtm_smooth.tif`.
   Compare slope error with the dome gradient (a few metres over several km). Report whether a 0.3 m head drop between blocks can be resolved on the smoothed surface.
4. **Test the source-sheet hypothesis.** Get BIG's DSM coverage index (sensor per area) or infer sheet boundaries from residual steps along tracks, and fit offset and k per source area (`ground.fit.joint_intercept` already fits per class). Ask D. Susetyo or BIG for per-sheet source metadata.
5. **Benchmark alternative base DEMs** at the same held-out points: FABDEM, Copernicus GLO-30, FathomDEM (check its licence first). Judge them on relative error as well as RMSE.
6. **Only if lidar spans several sheets or sites:** leave-one-site-out test of predicting the offset and k from covariates (canopy height, land cover, source sheet, embeddings). If it fails, a transferable learned terrain model needs more lidar than exists.
7. **Update the docs:** this repo's `docs/test-run-sebangau.md` and `docs/demnas-literature.md`, then sync `re-peat/docs/07-demnas-literature.md`, the data-preparation and accuracy rows of the methodology, and `re-peat/docs/08-build-plan.md` (terrain contract).

## What the digital twin needs back from this repo (the terrain contract)

Write these to the run output so the twin can read them without re-deriving anything:

| Output | Used by the twin for |
|---|---|
| `dtm_smooth.tif` (and the datum and epoch it is in) | surface elevation, delineation, flow direction |
| Per-class bias and RMSE, relative error, slope error | terrain Monte Carlo and "terrain-sensitive" flags |
| Correlation length and sill of the residual field | spatially correlated DTM error sampling |
| Raster of which source/sheet each cell came from | per-source uncertainty |
| A quality flag per cell (LiDAR / calibrated DEMNAS / uncalibrated) | wider uncertainty bands, which parts of the allocation to trust |

The twin must also accept heads from GNSS or levelling (canal water levels, block crests, logger tops) that override the DTM wherever they exist.

## Known code TODOs (from the test-run log)

- Fail loudly (or add a flag) when SlideRule returns 0 points or errors; today a failed fetch ends as a normal run with the unfitted prior k.
- Add a timeout to GEDI requests (one hung about 90 minutes at Mendahara).
- Cache downloaded canopy-height windows (4 to 5 min per tile).
- Replace the prior `k_by_class` of 0.8, or warn that it is unsupported.
- Rerun Mendahara with GEDI, and check Bengkalis cropland and shrubland (smoothed bias −5.2 m and −2.1 m).
- `khg-prioritisation-module` has its own copy of `demnas_dtm.py` that has diverged (≈35,128 vs 34,710 bytes). This repo is the source; merge into one package.

## Working conventions

- Runs and sample data are gitignored (`runs/`, `_data_sample/`); never commit rasters.
- Memory is tight on the development machine (1 to 2 GB free at times): average a tile to about 30 m first, or use a window, for tests. Redirect logs to a file instead of piping, or a run looks hung.
- Do not commit or push unless asked. Mark unverified literature with a dagger (†) as in `docs/demnas-literature.md`.
- Keep numbers in the docs traceable to a run folder or a paper.
