# Test run on the Sebangau sample: log of runs and decisions

Date: 2026-10-08. Input: `_data_sample/DEMNAS_sebangau.tif` (gitignored).
Purpose: check that `demnas_dtm.py` runs end to end on real DEMNAS data, including ground truthing.

## Input

| Property | Value |
|---|---|
| CRS | EPSG:4326 |
| Size | 17,341 x 9,323 px (about 7.5e-5 deg, roughly 8 m) |
| Extent | lon 113.581 to 114.280, lat -3.469 to -2.169 |
| Nodata | -9999 |
| Valid data | A diagonal strip, not the whole rectangle. Heights up to about 25 m on a coarse read. |

## Environment

- Python 3.14.7 in a throwaway venv (not in the repo). `pip install -r requirements.txt` worked unchanged, with no build problems on 3.14.
- No code in the repo was changed during these runs. The only repo changes are `.gitignore` (ignores `runs/`, `_data_sample/`, `__pycache__/`) and this report.
- Run outputs live in `runs/` (gitignored). Seen from `runs/`:

| Folder | What |
|---|---|
| `sebangau_30m/` | Run 1, full tile, no ground truthing |
| `aoi_window.gpkg` | AOI for run 3 |
| `window_calib/` | Run 3, windowed, with ground truthing |
| `window_calib.log` | Log of run 3 |

## Runs

### Run 1: full tile, 30 m, ground truthing off

Command: `python demnas_dtm.py --dem _data_sample/DEMNAS_sebangau.tif --out runs/sebangau_30m --res 30 --ground none`

**Decision: resolution 30 m and no ground truthing.** The tile is about 160 million cells at native resolution, and a SlideRule request over roughly 78 x 144 km would be very large. The aim was to prove the DEM, corrections and smoothing path first.

Result: completed in 1,123 s. Grid 2607 x 4806 px in EPSG:32749 (UTM 49S). Most of the time went to reading canopy height tiles (about 4-5 min each, no progress logged between tiles). 13.0% of cells excluded in total, 5.4% of them as spikes.

| Surface | Median (m) | Notes |
|---|---|---|
| DEM | 1.9 | |
| Smoothed DTM | 0.6 | min -12.0, max 21.5 |
| Correction | 0 | 95th percentile 13.6 |

k values were the uncalibrated placeholders (forest 0.8 and so on), so this run only shows the pipeline works. Residuals reach -19 m to +25 m. I did not investigate them. Likely cause is mask edges around water and built-up land.

An early attempt piped the output through `tail`, so the log showed nothing until the process ended. It looked hung and was stopped, then rerun with output to a file. It had not been hung.

### Run 2: windowed run, failed (network)

**Decision: use a 15 x 15 km window instead of the full tile**, so the ground-point fetch is a realistic size. The valid data is a diagonal strip, so I picked the centre from a coarse look at the data, 113.905 E, 3.094 S, half-width 0.0675 deg, saved as `runs/aoi_window.gpkg`. A check showed 100% valid DEM cells in the window (heights -2.4 to 10.6 m).

The first attempt at 8 m lost network access (DNS failures for WorldCover, canopy height and SlideRule). The pipeline kept going by design: no land cover, no canopy height, no ground points, `k_default` everywhere. The outputs were therefore meaningless, and I deleted them.

Note for later: with `ground.fail_on_error: false` (the default), a network failure still ends in a normal "done" with a warning-only trail. Check the log for "No land cover available" and "no ground points available".

### Run 3: windowed run with ground truthing

Command: `python demnas_dtm.py --dem _data_sample/DEMNAS_sebangau.tif --aoi runs/aoi_window.gpkg --out runs/window_calib --res 8`
All other settings are the defaults: ESA WorldCover and Meta/WRI canopy height from the cloud, ICESat-2 ATL08 through SlideRule (2019-2025), datum mode `pyproj` (EGM2008), median 300 m then gaussian 150 m smoothing. Completed in 290 s.

**Ground points.** ATL08 returned 7,810 segments, 6,689 were loaded and 1,514 were usable after filtering. Of these 1,073 went to calibration and 441 to validation, split in 2 km spatial blocks.

**Calibration** (`calibration.json`):

| Class | n | k | Status |
|---|---|---|---|
| 10 tree cover | 434 | 0.45 (se 0.019) | fitted, 186 vegetated points |
| 20 shrubland | 236 | 0.50 | prior kept, 18 vegetated points |
| 30 grassland | 403 | 0.20 | prior kept, 3 vegetated points |

Global bias is -3.77 m, from low-canopy points.

**Validation** (441 held-out points):

| Surface | Bias (m) | RMSE (m) | NMAD (m) |
|---|---|---|---|
| Raw DEM | -1.92 | 3.19 | 3.26 |
| Prior k | -3.49 | 4.25 | 1.58 |
| Calibrated | +0.95 | 2.31 | 1.73 |
| Smoothed | +0.95 | 1.97 | 1.69 |

By class (bias in m):

| Class | Raw DEM | Calibrated | Smoothed |
|---|---|---|---|
| 10 tree cover | +0.04 | +2.15 | +2.09 |
| 20 shrubland | -4.13 | -0.39 | -0.34 |
| 30 grassland | -4.13 | -0.40 | -0.36 |

## Findings from run 3 (first reading)

1. **The pipeline works end to end** on the sample: mosaic, reprojection, WorldCover and canopy height fetch, SlideRule fetch, datum conversion, calibration, validation and outputs. The README says the SlideRule and PROJ paths had never been tested against the live services. This run exercised both without errors.
2. **A large DEM - ground offset in the open classes.** Where canopy is near zero (shrubland, grassland) the DEM sits about 4.1 m below the ICESat-2 ground, with a tight spread (NMAD about 0.7 m).
3. **The calibration absorbed that offset into one global bias** (-3.77 m, so +3.77 m on the DTM) and applied it to every class. In forest the raw DEM was already close to ground (+0.04 m), so the calibrated DTM ended up about 2.1 m too high there.
4. **Two of the three classes had too few vegetated points** (18 and 3) to fit k, so they kept the priors.
5. `dtm_corrected.tif` is the unsmoothed vegetation-corrected surface. `dtm_smooth.tif` is the smoothed surface for dome-scale work. Neither should be used as a final product until the offset question below is settled.

## Diagnostics on the cached ICESat-2 points (offline)

These checks reuse `runs/window_calib/ground_points.gpkg` and need no network. They revise the reading above.

| Check | Result | What it rules in or out |
|---|---|---|
| Geoid undulation applied by `pyproj` | N = 43.0 to 43.7 m (median 43.3 m) | The geoid grid is applied. Skipping it (`mode: none`) would be 43 m off, so the 4 m offset is not a missing geoid conversion. |
| Offset by acquisition year (2019-2025, open points) | -4.07, -3.99, -3.51, -3.75, -3.99, -4.47, -3.58 m, no trend | Not subsidence or a drift in time. |
| Offset by DEM height quartile (open points) | -4.68, -4.32, -3.67, -1.58 m from lowest to highest | Not a constant datum shift. The offset correlates 0.86 with DEM height. |
| Open-class ground heights | median ground 5.9 m; in forest 3.9 m. DEM medians are 1.9 m and 4.2 m. | ICESat-2 says the open land is 2 m higher than the forest, the DEM says the reverse. Superseded: see the GEDI section, which finds the same heights from a second sensor. |
| Open points: ground vs DEM | corr -0.32 (ground = -0.25 DEM + 6.2) | ICESat-2 ground in open classes does not track the DEM. |
| Canopy height in "tree cover" points | median 0 m, 75th percentile 6.4 m, 95th 10.6 m; 53% below 2 m | This window is degraded or burnt peat forest, not tall forest. |
| Forest points with canopy >= 2 m (n = 315) | DEM - ground = -0.15 + 0.045 x CHM | DEMNAS is close to ground here (k about 0.05). |
| Forest points with canopy < 2 m | median DEM - ground = -2.5 m | The same class gives -2.5 m at low canopy and -0.15 m at higher canopy. |
| Land-cover edge filter | 5,166 of 6,689 points (77%) dropped | The 50 m edge buffer removes most of the data. |

**Revised reading.** The offset is not a clean constant datum shift. It differs by class (-4 m in open classes, -2.5 m in forest at low canopy, -0.15 m in forest with canopy), it varies with DEM height, and it has no temporal trend. The calibration model assumes one constant bias plus k x canopy height, and that assumption does not hold here. The cause is not resolved. Candidates: a datum difference shared by both lidars, WorldCover class errors, spatial variation in the DEMNAS source data, or a real DEM error. The GEDI section below rules out an ICESat-2-only problem.

## Code changes made after run 3

Both changes are in `ground_truth.py` and `demnas_dtm.py`. Defaults are unchanged, so existing runs reproduce exactly (the `base` experiment below matches run 3 to the second decimal).

- **Joint per-class fit** (`ground.fit.joint_intercept: true`). Fits `DEM - ground = a[class] + k[class] x CHM` with a robust (Huber) line on all vegetated points of a class. Classes without enough vegetated points keep the prior k and the global bias.
- **Datum diagnostics** (`ground.diagnostics`). Every run now writes `datum_diagnostics.json`, and `run_report.json` carries it. It holds the median geoid undulation, the median DEM - ground, and the low-canopy offset per class. It warns when the median offset exceeds 1 m (the old threshold was 20 m, which missed this case) and when low-canopy offsets differ by more than 1 m between classes.
- **Exclusion summary.** The log now lists how many points each exclusion reason removed.
- **SlideRule tiling** (`ground.tile_deg`, default 0.5). Large AOIs are split into tiles, because SlideRule rejects a request that matches more than 300 ATL03 granules. See the Bengkalis notes below.

## Experiments

All experiments reuse the cached ICESat-2 points and the land cover and canopy rasters from run 3 (`corrections.mode: local`), at 8 m on the same window. Configs and logs are in `runs/exp_*.yaml` and `runs/exp_*.log`.

| Run | Edge buffer | Fit | Validation n | Smoothed bias (m) | Smoothed RMSE (m) |
|---|---|---|---|---|---|
| base | 50 m | global bias | 441 | +0.95 | 1.97 |
| joint | 50 m | joint intercept | 441 | -0.09 | 1.24 |
| edge10 | 10 m | joint intercept | 1006 | -0.16 | 1.47 |
| edge0 | none | joint intercept | 1752 | -1.14 | 2.12 |

**Comparability.** `base` and `joint` use the same 441 validation points, so their numbers compare directly. The `edge` runs have different validation sets, so their RMSE cannot be compared with those two.

- **Joint fit:** tree cover k falls from 0.45 to 0.04 with intercept -0.25 m, and the tree cover validation bias goes from +2.1 to +0.2 m. Shrubland and grassland are unchanged (-0.4 m) because they still use the global bias and prior k.
- **k stays near zero in every joint run:** 0.04 to 0.06 for tree cover, and 0 to 0.03 for shrubland and grassland once enough points are available. In this window the canopy height product does not explain the DEM - ground difference. The prior k of 0.8 is far from what the data show.
- **Smaller edge buffers keep more points** but add noisier points near class boundaries, and the offset between classes persists. The edge-free run has a -1.1 m bias.
- **Still unresolved:** the median DEM - ground stays near -3.4 to -3.9 m in all runs, and the warning fires in all of them.

## Second ground source: GEDI L2A

GEDI L2A (lowest-mode elevation, quality flag 1, sensitivity >= 0.95) was fetched through SlideRule for the same window together with ICESat-2 (`runs/exp_gedi.yaml`, joint-intercept fit, 50 m edge buffer, same canopy and land cover rasters). It returned 10,104 footprints, against 6,689 ICESat-2 segments. After filtering, 2,560 GEDI and 1,514 ICESat-2 points were usable, 4,074 in total (24% of 16,793).

**The two sensors agree.** Median DEM - ground by class and canopy, usable points only:

| Source | Class | Canopy | n | Ground H (m) | DEM - ground (m) | NMAD (m) |
|---|---|---|---|---|---|---|
| GEDI | shrubland | < 2 m | 626 | 6.12 | -4.31 | 1.15 |
| ICESat-2 | shrubland | < 2 m | 329 | 6.18 | -4.30 | 0.82 |
| GEDI | grassland | < 2 m | 387 | 5.59 | -4.06 | 0.86 |
| ICESat-2 | grassland | < 2 m | 490 | 5.85 | -4.26 | 0.83 |
| GEDI | tree cover | >= 2 m | 924 | 4.22 | +0.09 | 1.75 |
| ICESat-2 | tree cover | >= 2 m | 315 | 3.78 | +0.49 | 1.02 |
| GEDI | tree cover | < 2 m | 555 | 5.34 | -1.47 | 2.62 |
| ICESat-2 | tree cover | < 2 m | 353 | 5.79 | -2.54 | 1.95 |

In the 247 cells of 100 m that contain both sources, the median GEDI - ICESat-2 ground height is +0.25 m (NMAD 0.86 m). The two lidars see the same ground height to within about a quarter of a metre, and both put it about 4.1 to 4.3 m above DEMNAS in open land.

**What this changes.**
- The earlier suspicion that the open-class ICESat-2 heights were wrong (see the diagnostics table) is now much less likely. Two independent instruments, with different footprints, wavelengths and processing, give the same heights.
- It does not rule out a shared error. Both sources were converted to orthometric height with the same geoid (EGM2008 through PROJ), so a datum difference between DEMNAS and EGM2008 would appear identically in both. The independent LiDAR and GNSS data are what can separate a datum error from a DEM error.
- The pattern that open land has higher lidar ground than forest (about 5.3 to 6.2 m against 3.8 to 4.2 m) also holds in both sensors. The DEM shows the reverse. This is a second thing to explain: either DEMNAS is lower than the ground in open areas, or lidar ground in forest is lower than the DEM's.

**Calibration with both sources** (joint intercept): tree cover k = 0.06, shrubland k = 0.20 (now fitted, 58 and more vegetated points), grassland keeps the prior. Validation on 1,373 held-out points: smoothed bias -0.10 m, RMSE 2.22 m, NMAD 1.32 m (raw DEM: bias -1.91 m, RMSE 3.57 m). The RMSE is higher than the ICESat-2-only joint run (1.24 m) because the validation set is different and larger, with many more tree cover points (769), where the error is largest (smoothed RMSE 2.5 m). Do not compare the two numbers directly.

The median DEM - ground is still -2.9 m, and the datum warning still fires.

## Additional sites: Mendahara and Bengkalis

Two more DEMNAS samples were processed on 2026-10-08 with the same pipeline: `DEMNAS_mendahara.tif` (Jambi, 8,554 x 8,142 px) and `DEMNAS_bengkalis.tif` (Riau, 16,668 x 19,005 px, 1.3 GB). Both are EPSG:4326 at about 8 m with nodata -9999, and about 42-44% of the cells are valid (the rest is sea).

**Method choices.**
- **Memory.** Free RAM was about 1.9 GB, and the pipeline holds several copies of the mosaic. Each tile was first averaged 4x to about 30 m (`runs/prep/DEMNAS_<site>_x4.tif`, nodata-aware average) and then run at 30 m. Sebangau's 30 m run used the native 8 m tile, so the three sites differ slightly in how the DEM was reduced.
- **AOI.** A land-only polygon was built from the valid DEM cells (`runs/aoi_<site>.gpkg`) so the lidar requests skip open sea.
- **Settings.** `ground.fit.joint_intercept: true`, ICESat-2 ATL08 plus GEDI requested, all other settings default. Configs: `runs/mendahara.yaml`, `runs/bengkalis.yaml`, `runs/bengkalis_gt.yaml`.

**What went wrong first, and the fix.**
- **Mendahara GEDI.** The GEDI request hung for about 90 minutes and then failed with a connection error. The pipeline continued with ICESat-2 only. Mendahara therefore has no GEDI.
- **Bengkalis first run.** ICESat-2 returned 0 segments and GEDI returned HTTP 502. The pipeline logged this at INFO level and finished with the unfitted prior k, so `runs/bengkalis_30m/` is uncalibrated. Do not use its smoothed DEM.
- **Bengkalis cause.** On retry SlideRule reported "number of CMR hits <301> exceeded maximum allowed <300> for ATL03": a request over a large AOI matches too many granules and is rejected whole.
- **Fix.** `ground.tile_deg` (default 0.5 degrees) now splits large AOIs into tiles, requests each separately, logs and skips a failed tile, and warns that the result is incomplete. The Bengkalis AOI split into 8 non-empty tiles (of up to 9), none failed. This reran from the land cover and canopy rasters of the first run, so the 30 minute canopy download was not repeated. The calibrated Bengkalis result is `runs/bengkalis_30m_gt/`.

**Results.** Validation points are held out in 2 km spatial blocks (30%). Smoothed DEMs are `dtm_smooth.tif` in each output folder.

| Site | Ground points (usable / loaded) | Sources | Validation n | Raw DEM bias / RMSE (m) | Calibrated bias / RMSE (m) | Smoothed bias / RMSE / NMAD (m) |
|---|---|---|---|---|---|---|
| Sebangau window (15 km) | 1,514 / 6,689 (ICESat-2) | ICESat-2 | 441 | -1.92 / 3.19 | -0.10 / 1.49 | -0.09 / 1.24 / 1.12 |
| Mendahara (full tile) | 20,403 / 68,979 | ICESat-2 | 5,869 | +0.50 / 2.64 | +0.70 / 2.74 | +0.64 / 2.32 / 1.40 |
| Bengkalis (full tile) | 47,530 / 313,544 | ICESat-2 | 13,803 | +2.57 / 4.14 | +0.72 / 3.24 | +0.64 / 2.78 / 1.85 |

The Sebangau row is the joint-intercept ICESat-2 run on the 15 km window. The sites differ in size and in the number of points, so the rows are not a ranking of the sites.

**Datum diagnostics** (median DEM - ground, usable points; geoid undulation N):

| Site | N (m) | Median all (m) | Tree cover low-canopy (m) | Other classes, low canopy (m) |
|---|---|---|---|---|
| Sebangau | 43.3 | -3.4 | -2.5 | shrubland -4.3, grassland -4.3 |
| Mendahara | 10.0 | -0.03 | +0.09 | shrubland -1.88, grassland -0.77, cropland -0.08 |
| Bengkalis | 3.3 | +2.16 | +2.24 | shrubland -0.19, grassland +0.09, cropland -0.34, mangrove +1.06 |

**Findings.**
1. **The offset is site-specific.** The same conversion (PROJ, EGM2008) gives a DEM that is 3-4 m below ground at Sebangau, about right at Mendahara, and 2 m above ground at Bengkalis (where tree cover is dense and the DEM likely sees canopy). A single global datum error would give the same offset everywhere. This points to the DEM itself, or to local conditions, as a cause, not to the geoid conversion alone. It supports the idea that DEMNAS is a mosaic whose behaviour depends on the source data. It does not prove it.
2. **Fitted k is far below the prior.** Tree cover k is 0.10 (Mendahara), 0.21 (Bengkalis) and about 0.05 (Sebangau). The prior of 0.8 is not supported by any site. Using the prior would have made Mendahara much worse (RMSE 5.9 m against 2.6 m raw) and Bengkalis worse too (5.4 m against 4.1 m).
3. **Calibration helps where the DEM sits above ground** (Bengkalis RMSE 4.14 m to 3.24 m, bias +2.57 m to +0.72 m) and does not help where it is already near ground (Mendahara).
4. **Smoothing helps everywhere** that was tested, by 0.4 to 0.5 m of RMSE after calibration (Mendahara 2.74 to 2.32 m, Bengkalis 3.24 to 2.78 m, Sebangau 1.49 to 1.24 m).
5. **None of the sites meets the 0.25 m target** set in the re-peat methodology. The best smoothed RMSE is 1.24 m.
6. **Bengkalis problem classes.** The smoothed DEM has a -5.2 m bias in cropland (88 points) and -2.1 m in shrubland (52 points). Both classes have few points and I did not investigate them. They may come from masks and the 30 m smoothing near the coast or from the class k and intercept fits. Treat Bengkalis cropland and shrubland as unreliable.
7. **Heavy exclusion.** At Bengkalis 171,200 of 313,544 points fell in excluded land cover classes (mostly water and sea), and 75,119 more were near a land-cover edge. Only 15% were usable.

**Limits.** These runs are at 30 m, from DEMs averaged down in the case of Mendahara and Bengkalis. ICESat-2 only. No independent ground reference. Calibration and validation come from the same sites, split by 2 km blocks, which is not an independent test. The CHM and WorldCover dates differ from DEMNAS. Mendahara and Bengkalis include mangroves and coastal peat, where tide and the flat terrain mean 1-2 m errors are large relative to the relief.

## Related literature (Julzarika and others)

Searched on 2026-10-08. Entries marked with a dagger were seen only as a search summary or a title, not read in full. Check the full text before citing them.

- Julzarika, A. and Harintaka (2019). Free global DEM: converting DSM to DTM and its applications. *Int. Arch. Photogramm. Remote Sens. Spatial Inf. Sci.* XLII-4/W16, 319-325. doi 10.5194/isprs-archives-XLII-4-W16-319-2019. Abstract read. DSM from X-SAR, SRTM and TanDEM-X is integrated, referenced to EGM2008 and converted to DTM using canopy tilt angle, vegetation height and a radius around the canopy. Tested on Rote Island, not on peat.
- Julzarika, A., Aditya, T., Subaryono and Harintaka (2020). Comparison of the latest DTM with DEM Pleiades in monitoring the dynamic peatland. *ISRITI 2020*. doi 10.1109/ISRITI51436.2020.9315410. Abstract read. Palangkaraya-Pulang Pisau peatland, the nearest study area to Sebangau. The DTM is from ALOS PALSAR/PALSAR-2 InSAR and Sentinel DInSAR, referenced to EGM2008. Mean height differences: Pleiades vs DTM 0.923 m, Pleiades vs field GNSS 0.557 m, DTM vs field GNSS 0.705 m.
- Julzarika, A. and Harintaka (2019). Indonesian DEMNAS: DSM or DTM? *2019 IEEE AGERS*, 31-36. doi 10.1109/AGERS48446.2019.9034351. **Now read in full** (`docs/Indonesian_DEMNAS_DSM_or_DTM.pdf`). DEMNAS is a fusion of IFSAR, TerraSAR-X, ALOS PALSAR and mass points; it is "dominated by DSM" in the South Kalimantan sample and "neither DSM nor DTM" in the Central Java one. Small sample, profile comparison only.
- Susetyo, D.B. (2023). Vertical accuracy assessment of DEMNAS, SRTM-1 and ASTER GDEM. *Geodesy and Cartography* 49(4). **Read in full** (`docs/susetyo et al.pdf`). Bogor, 60 GPS points: DEMNAS RMSE 4.968 m, LE90 8.172 m. The 8.17 m figure quoted earlier in this section is the LE90, not an RMSE.
- Susetyo, Lumban-Gaol and Sofian (2018). Prototype of national DEM in Indonesia. *ISPRS Archives* XLII-4. **Read in full.** Describes how the radar DSMs and stereo mass points are merged; RMSE 2.237 m on 142 GCPs in Aceh–North Sumatra.
- Julzarika's earlier height-model integration work (ALOS PALSAR, X-SAR, SRTM C, ICESat/GLAS) (dagger) reports vertical accuracies of about 1.1 to 2.0 m. Listed from a search summary only.
- A summary also said TerraSAR-X X-band stereo DSMs underestimate forest height by about 27% of canopy height (dagger). Not verified.

Full notes, accuracy table and consequences are in [`demnas-literature.md`](demnas-literature.md).

**Why this matters here.** DEMNAS is a radar DSM blended toward stereo mass points, with the sensor mix and mass-point density varying by sheet. That fits our finding that k is near zero and the offset varies. The published accuracies (RMSE 2.2 to 5.0 m, all measured at open-ground control points) are in the same range as our smoothed results (1.2 to 2.8 m). I have not tested whether the residual maps to source sheets.

## Relative error from the cached ground points (2026-10-12)

The water-sharing model needs height *differences* over 0.5 to 2 km, not absolute heights. `script/relative_error.py` takes the usable ICESat-2 (and GEDI) points of a run, removes the site-wide median error, and reports the RMS and NMAD of the error difference between point pairs by distance. Surface: smoothed DTM, using the runs `exp_joint` (Sebangau window, ICESat-2), `mendahara_30m` and `bengkalis_30m_gt`.

| Lag (m) | Sebangau RMS / NMAD (m) | Mendahara RMS / NMAD (m) | Bengkalis RMS / NMAD (m) |
|---|---|---|---|
| 0–150 | 0.37 / 0.24 | 0.58 / 0.32 | 1.01 / 0.46 |
| 300–600 | 0.74 / 0.70 | 1.19 / 0.70 | 1.64 / 1.03 |
| 1000–2000 | 1.16 / 1.06 | 1.88 / 1.12 | 2.55 / 1.68 |
| 4000–8000 | 1.73 / 1.73 | 2.94 / 2.02 | 3.40 / 2.38 |

For comparison, the raw DEM differences at 1 to 2 km are 1.61, 2.56 and 3.32 m RMS, so smoothing helps but not enough.

**Reading.**
- Over 1 to 2 km the height difference between two points is wrong by about 1.1 to 2.6 m RMS (NMAD 1.1 to 1.7 m), against a 0.3 m head drop between blocks. A DTM from DEMNAS alone cannot place blocks by 0.3 m steps at these sites.
- The difference keeps growing out to 8 km with no plateau, so the error is not short-range noise. It looks like trend and class-dependent offsets, not something a larger smoothing window removes.
- The shortest lag bounds the ICESat-2 point noise at roughly 0.3 to 0.7 m, well below the 1 km numbers, so most of the 1 km error is not point noise. That bound is weak: the nearest pairs are mostly on one track, where errors are correlated.

**Caveats.**
- The ground heights are not truth. [Sun et al. 2026](https://www.sciencedirect.com/science/article/pii/S0034425726003858) report ICESat-2 ATL08 footprint RMSE of 3.64 m before refinement and 1.32 m after, and GEDI 4.14 m and 2.78 m, against airborne lidar in Brunei peat. Our figures mix DEM and lidar-ground error and cannot be separated without an airborne reference.
- Part of the difference between points is land-cover-dependent offset (different bias per class), which a class-aware calibration partly removes. Mendahara and Bengkalis include coastal and mangrove classes.
- Treat these as provisional until the airborne LiDAR is compared.

## Copernicus GLO-30 against DEMNAS (2026-10-15)

Question: would a TanDEM-X based surface (WorldDEM, FABDEM) serve better than DEMNAS? GLO-30 is the open 30 m edited version of the same TanDEM-X data as WorldDEM (EGM2008 heights), so it is the cheapest proxy. `script/compare_base_dem.py` samples it at the usable ICESat-2/GEDI points of a run, with no calibration, and compares it with the raw DEMNAS values at the same points. Smoothed = median about 300 m then gaussian about 150 m, as in the DEMNAS chain. Pair columns are RMS / NMAD of the error difference between points (m).

| Site | Surface | 0–150 m | 300–600 m | 1–2 km | 4–8 km | Median DEM − ground, canopy < 2 m / ≥ 2 m (m) |
|---|---|---|---|---|---|---|
| Sebangau window | DEMNAS raw | 0.89 / 0.70 | 1.31 / 1.12 | 1.61 / 1.34 | 2.79 / 2.36 | −3.93 / +0.39 |
| | **GLO-30 raw** | 0.49 / 0.35 | 0.75 / 0.48 | **0.91 / 0.67** | 1.11 / 0.86 | **+0.55 / +1.46** |
| | GLO-30 smoothed | 0.35 / 0.17 | 0.54 / 0.37 | 0.67 / 0.60 | 0.92 / 0.81 | |
| | DEMNAS calibrated + smoothed | 0.37 / 0.24 | 0.74 / 0.70 | 1.16 / 1.06 | 1.73 / 1.73 | |
| Mendahara | DEMNAS raw | 1.60 / 1.04 | 2.09 / 1.41 | 2.56 / 1.75 | 3.57 / 2.59 | −0.04 / −0.02 |
| | GLO-30 raw | 2.30 / 1.56 | 3.08 / 2.37 | 4.12 / 3.20 | 4.74 / 4.13 | +2.50 / +4.53 |
| | DEMNAS calibrated + smoothed | 0.56 / 0.32 | 1.14 / 0.70 | 1.80 / 1.10 | 2.97 / 2.03 | |
| Bengkalis | DEMNAS raw | 2.20 / 1.38 | 2.90 / 1.92 | 3.47 / 2.51 | 4.20 / 3.29 | +1.66 / +2.45 |
| | GLO-30 raw | 3.27 / 1.94 | 4.63 / 3.05 | 5.83 / 4.25 | 7.33 / 5.92 | +4.89 / +6.08 |
| | DEMNAS calibrated + smoothed | 0.93 / 0.48 | 1.75 / 1.06 | 2.62 / 1.71 | 3.54 / 2.41 | |

**Findings.**
1. **At Sebangau, the DEMNAS offset is a DEMNAS property, not a shared geoid error.** GLO-30 and the ICESat-2/GEDI heights both use EGM2008 and agree to about +0.5 m over open peat, where DEMNAS is 4 m below ground. This answers open question 1 in `AGENTS.md` to a good degree: the satellite lidar ground heights are not the problem. The +0.5 m in open land is also about what 10 to 14 years of peat subsidence (TanDEM-X was acquired in 2011 to 2015) would give. Airborne LiDAR is still needed for absolute truth.
2. **GLO-30 behaves like a surface model where vegetation is tall.** At Mendahara and Bengkalis (plantation, forest, mangrove) it sits 2.5 to 6 m above the ground and is clearly worse than DEMNAS. A fitted canopy-height correction (Meta/WRI canopy height, per-class intercepts) leaves the tree-cover intercept at +3 to +6 m and the 1 to 2 km relative error at 2.8 to 4.4 m smoothed, still worse than calibrated DEMNAS (1.8 and 2.6 m). The canopy height product does not explain the bias there.
3. **The Sebangau window is mostly degraded and open peat.** About 53% of its "tree cover" points have canopy below 2 m, and it burned in 2015 and 2019. The GLO-30 result there should not be read as valid for intact forest. It is, however, the kind of peat where rewetting decisions matter.
4. **Even the best case is above the block step.** GLO-30 smoothed gives 0.67 m RMS over 1 to 2 km at Sebangau. That is better than DEMNAS but still above 0.3 m, and includes ICESat-2 noise.
5. **WorldDEM is the same physics as GLO-30** (X-band, same acquisitions) at 12 m instead of 30 m. After smoothing at 300 m the extra resolution adds little. FABDEM (a machine-learning forest correction of GLO-30) is tested in the next section.

### FABDEM v1.2 (2026-10-15)

Same method and points as above, FABDEM v1.2 tiles from the Hugging Face mirror (`links-ads/fabdem`; the 10 degree block folders are named like `S10E110-N00E120`). The script now samples both surfaces (`script/compare_base_dem.py`). Pair columns are RMS / NMAD (m) at 1–2 km; offsets are the median DEM − ground (m) for canopy below 2 m / at or above 2 m.

| Site | DEMNAS calibrated + smoothed | GLO-30 smoothed | FABDEM raw | FABDEM smoothed | FABDEM offset (< 2 m / ≥ 2 m) | GLO-30 offset |
|---|---|---|---|---|---|---|
| Sebangau window | 1.16 / 1.06 | 0.67 / 0.60 | **0.67 / 0.62** | **0.65 / 0.62** | +0.14 / +0.19 | +0.55 / +1.46 |
| Mendahara | **1.80 / 1.10** | 3.03 / 2.08 | 2.99 / 1.55 | 2.48 / 1.39 | +1.32 / +1.41 | +2.50 / +4.53 |
| Bengkalis | **2.62 / 1.71** | 4.42 / 3.00 | 5.09 / 2.73 | 4.26 / 2.39 | +2.03 / +1.38 | +4.89 / +6.08 |

**Findings.**
1. **FABDEM removes the canopy dependence.** Its offset is nearly the same under open and tall vegetation at all three sites (for example +0.14 and +0.19 m at Sebangau), where GLO-30 differed by 1 to 2 m between the classes. What is left is a site-level offset of +0.1 to +2 m, which does not affect relative heights and can be fitted from ICESat-2/GEDI. Part of it may be peat subsidence since the TanDEM-X acquisitions.
2. **At Sebangau, uncalibrated FABDEM is the best surface tested:** 0.65 to 0.67 m RMS over 1 to 2 km, against 1.16 m for calibrated and smoothed DEMNAS, and with no fitting. The 4 m DEMNAS offset there is again absent.
3. **At Mendahara and Bengkalis, calibrated DEMNAS is still better** (1.80 and 2.62 m against 2.48 and 4.26 m smoothed FABDEM). The gap is mostly in the tails: FABDEM's NMAD is closer (1.39 against 1.10 m at Mendahara). These sites have plantation, coastal and mangrove land cover where the ML correction is less reliable. Per-class errors were not examined.
4. **None reaches 0.3 m.** The best result, 0.65 m at Sebangau, still includes ICESat-2 noise but is above the block step.
5. **Licence.** The University of Bristol distribution is CC BY-NC-SA 4.0. The Hugging Face mirror states the Non-Commercial Government Licence v2.0. Both are non-commercial; clarify whether the KLH deliverable counts as such before building the pipeline on it.

**Next.** Fetch ICESat-2/GEDI ground points over the whole Kahayan–Sebangau KHG (tiles of 0.5 degrees), and compare DEMNAS, GLO-30 and FABDEM by land cover over the full KHG, including the park forest, before choosing a base surface for it. FABDEM is the leading candidate for the degraded and burnt peat that matters most there.

## Whole Kahayan–Sebangau KHG (2026-10-15)

The Sebangau window result above was too favourable to FABDEM and GLO-30 to generalise, so the pipeline was run over the whole KHG (polygon from the KHG layer, DEMNAS tile `DEMNAS_sebangau.tif`, 30 m, ICESat-2 ATL08 only, joint intercepts; config `runs/ks_full.yaml`, output `runs/ks_full_30m`, 279 s). SlideRule returned 134,293 ground segments (about 6 tiles; some granule and beam reads failed with H5Coro errors, so coverage is slightly incomplete). 22,422 were usable. Of the rest, 88,419 were near a land-cover edge and 22,394 fell where DEMNAS has no data: **the DEMNAS tile supplied covers only part of the KHG** (a diagonal strip), while GLO-30 and FABDEM are complete.

Relative error over 1–2 km (RMS / NMAD, m), per-class median offsets removed, DEMNAS calibrated and smoothed by the pipeline, GLO-30 and FABDEM smoothed (median about 300 m, gaussian about 150 m):

| Land-cover group (n) | DEMNAS calibrated + smoothed | GLO-30 smoothed | FABDEM smoothed |
|---|---|---|---|
| All classes (22,422) | 2.14 / 1.36 | 2.58 / 1.47 | 2.19 / 1.24 |
| Non-forest: shrub, grass, crop, wetland (8,754) | 1.02 / 0.91 | **0.89 / 0.70** | 0.91 / 0.73 |
| Tree cover (11,893) | **2.20 / 1.48** | 2.69 / 1.64 | 2.64 / 1.54 |
| Mangrove (1,775) | 3.79 / 3.20 | 4.04 / 3.73 | **2.39 / 1.77** |

Median surface − ground (m) before any offset removal, raw surfaces: tree cover DEMNAS +0.75, GLO-30 +4.88, FABDEM +2.34; shrubland −3.47, +0.89, +0.45; grassland −1.57, +0.80, +0.82; mangrove +5.73, +9.68, +1.93.

**Findings.**
1. **No decisive winner KHG-wide.** Once DEMNAS is calibrated per class and smoothed, it is level with FABDEM (2.14 against 2.19 m RMS, NMAD 1.36 against 1.24 m). FABDEM gets there with class offsets only, and GLO-30 is worse. The earlier large gap in the 15 km window (0.65 against 1.16 m) came from that window being mostly degraded open peat.
2. **Open and degraded peat favours TanDEM-X surfaces, modestly:** 0.9 against 1.0 m RMS and 0.7 against 0.9 m NMAD. Class offsets still differ a lot (DEMNAS −3.5 m in shrubland and +0.75 m in tree cover), so DEMNAS needs calibration; FABDEM and GLO-30 are within 1 m in open classes without it.
3. **Tall forest stays poor for every surface** (2.2 to 2.7 m RMS). FABDEM leaves +2.3 m of canopy bias in tree cover; GLO-30 +4.9 m. **Mangrove and coastal peat favours FABDEM** (+1.9 m against +5.7 m for DEMNAS).
4. **No surface reaches the 0.3 m block step anywhere**; the best group (open peat) is about 0.9 m, which includes ICESat-2 noise (point noise of the order 0.3 to 0.7 m).
5. **Practical difference is coverage and effort,** not accuracy: FABDEM and GLO-30 are wall-to-wall with no tile gaps and need only class offsets; DEMNAS needs tiles, calibration and smoothing. FABDEM is non-commercial licensed.
6. **Sub-KHG delineation is also affected (inference, not tested).** Regional dome slopes of a fraction of a metre per kilometre are comparable to 1 to 2 m of relative error over 1 to 2 km, so flow routing from any of these surfaces is uncertain at the scale of sub-KHG units. Delineation should lean on the mapped rivers and primary canals and use the DEM only for orientation, then be compared with the 16 sub-KHG of the 2021 study.

## Limits of this evidence

- One 15 x 15 km window and one DEMNAS tile. Two satellite lidar sources (ICESat-2 ATL08 and GEDI L2A) that share the same geoid conversion, and no GNSS or airborne LiDAR points yet.
- A datum error common to both satellite sources cannot be separated from a DEM error without an independent reference (airborne LiDAR or GNSS).
- The canopy height product (Meta/WRI) and WorldCover date from different years than DEMNAS. This window burned in 2015 and 2019.
- The 0.25 m target in the re-peat methodology is not met by any run (best smoothed RMSE 1.24 m, on 441 points).
- The experiments tune and evaluate on the same window and the same ground points. The spatial split makes the comparison fair between runs, but it is not an independent test.

## Open items

- ~~Obtain Julzarika's "Indonesian DEMNAS: DSM or DTM?"~~ Done 2026-10-12; see `demnas-literature.md`. Still open: per-sheet DEMNAS source metadata (BIG's DSM coverage index in digital form, acquisition years). Ask D. Susetyo or BIG directly.
- Plot DEM - ground along the ICESat-2 tracks against the BIG source-coverage map, to see whether offsets step at sensor boundaries; if so, fit k and offset per source area.
- Replace the prior `k_by_class` of 0.8 with a value the data support (0.05 to 0.2 for tree cover at the three sites), or make `--ground none` warn that the prior is unsupported.
- Reword the 0.25 m RMSE target: published DEMNAS accuracy is 2.2 to 5.0 m RMSE at open-ground points, so the target needs LiDAR or GNSS. Report relative (detrended) error alongside the absolute error.
- Add an independent ground reference: GNSS spot heights on canal banks and at loggers, or LiDAR, to decide whether the offset is a datum error or a DEM error.
- Run the airborne LiDAR comparison when the data arrive: it is the independent test of the datum question. Use it to check the shared EGM2008 conversion and the open-versus-forest height pattern.
- Test whether the DEM - ground residual maps to DEMNAS source tiles or acquisition dates.
- Report the relative (detrended) error alongside the absolute error, since the hydrology needs relative heights.
- Benchmark FABDEM against the same held-out points.
- Fail loudly (or add a flag) when SlideRule returns 0 points or errors: a failed fetch currently ends as a normal run with the unfitted prior k. The Bengkalis first run shows the cost.
- Add a timeout to GEDI requests: one hung for about 90 minutes at Mendahara.
- Rerun Mendahara with GEDI once SlideRule is stable, and check Bengkalis cropland and shrubland (bias -5.2 m and -2.1 m after smoothing).
- Rerun Mendahara and Bengkalis from the native 8 m DEM, not the 4x averaged one, if memory allows.
- Consider failing loudly on network errors in download mode.
- Cache downloaded canopy windows; the fetch took 4-5 min per tile.

## Mendahara at the native 8 m (2026-10-09)

Rerun of Mendahara from the full-resolution DEM (not the 4x averaged one), on an 8,456 x 8,830 px grid at 8 m, with canopy height and land cover fetched at 8 m. The ICESat-2 points from the 30 m run were reused (`ground_points_raw.gpkg` copied), so GEDI was not requested. Config: `runs/mendahara_8m.yaml`; output: `runs/mendahara_8m/` (637 MB). It completed in about 12 minutes on a machine with little free memory (1.2 GB free of 15 GB at the start).

| Run | Grid | Usable / loaded points | Validation n | Raw DEM RMSE (m) | Smoothed bias / RMSE / NMAD (m) |
|---|---|---|---|---|---|
| mendahara_30m | 30 m (4x averaged DEM) | 20,403 / 68,979 | 5,869 | 2.64 | +0.64 / 2.32 / 1.40 |
| mendahara_8m | 8 m native | 23,426 / 68,979 | 6,660 | 2.83 | +0.72 / 2.32 / 1.54 |

The validation sets differ because more points land on valid cells at 8 m, so the numbers are not strictly comparable. The smoothed RMSE is the same (2.32 m) at both grids. Fitted tree cover k is 0.09 (0.10 at 30 m). The finer grid does not improve the accuracy of `dtm_smooth.tif`. That surface is smoothed over 300 m and 150 m scales by design, so its effective resolution is set by the smoothing, not by the pixel size. The 8 m grid matters for `dtm_corrected.tif`, which keeps cell-level detail.

## Airborne lidar at Pulau Padang (Bengkalis KHG) (2026-10-12)

First comparison against airborne lidar. Script: `script/lidar_compare.py`; output: `runs/padang_lidar/lidar_compare.json` and `lidar_on_grid.tif`; log `runs/padang_lidar.log`. Surfaces compared are from `runs/bengkalis_30m_gt/` (ICESat-2 calibrated, 30 m). The lidar was held out and not used in any fit.

**Lidar.** `DTM_2mFloat.tif`, 2 m, EPSG:32648, float32, nodata -32767, 15,950 x 28,500 px. The GeoTIFF carries no vertical CRS. The delivery PDFs in `REPEAT-LH/dokumen/` say the flight was in **November 2016** and that GPS validation gave a DTM RMSE of 0.35 m (Executive Summary Laporan Pulau Padang, 2018); they do not state the vertical datum. **The datum is unconfirmed.** The 2 m pixels were binned into the 30 m run cells (cells need at least 80% lidar coverage and a within-cell lidar SD of at most 1.5 m; water class 80 and the run's excluded cells are masked). 1.08 million cells (973 km²) remain.

### Datum: a constant offset of about 2 m, not a geoid effect

At the 6,543 usable ICESat-2 points on the lidar footprint:

| Check | Result |
|---|---|
| EGM2008 N, pipeline vs independent pyproj (EPSG:4979 to 4326+3855), 8 points | identical to 0.01 m. N spans 1.1 to 2.9 m (median 1.86) |
| ICESat-2 orthometric H minus lidar | median **+1.96 m**, NMAD 0.72 m |
| Same, by canopy height 0-2 / 2-10 / 10-20 / 20+ m | +1.96 / +1.90 / +2.00 / +2.01 m (NMAD 0.4-0.8) |
| Slope of (H - lidar) against N, open land only | -0.48 (r = -0.05), so the offset does not track the geoid |
| By ICESat-2 year, 2019 to 2025 | 1.76 to 2.11 m, no trend |

The satellite ground heights and the lidar agree in shape to under a metre and differ by a near-constant 2 m. That rules out the shared EGM2008 step as the cause of the offset at this site (the independent N matches) and rules out a canopy-dependent satellite error. It does not say which of the two is on the wrong datum. Candidates: a local mean-sea-level or benchmark datum in the lidar delivery, or a bias in the ICESat-2 heights. A 3 to 9 year epoch gap (2016 vs 2019-2025) cannot produce 2 m, and the by-year medians show no subsidence trend. All absolute figures below are therefore reported raw and with the median removed. Relative figures are unaffected by a constant offset.

### Absolute error (30 m cells, raw, lidar datum unconfirmed)

| Surface minus lidar | Median (m) | NMAD (m) | RMSE (m) | NMAD after median removed (m) |
|---|---|---|---|---|
| `dem_utm` (DEMNAS) | +4.36 | 2.99 | 5.32 | 2.99 |
| `dtm_corrected` | +1.90 | 2.41 | 3.35 | 2.41 |
| `dtm_smooth` | +1.88 | 2.00 | 3.04 | 2.00 |

DEMNAS sits above the lidar ground by 3.1 to 3.7 m over open and short vegetation and by 5.5 to 7.8 m under 10 to 20+ m canopy, so it behaves as a surface model here with canopy partly in it. The ICESat-2 comparison on the same sample gives the same pattern (DEM minus H: +2.4 m in open land to +5.9 m under tall canopy). The -4 m open-land anomaly seen at Sebangau is **not** present at this site: DEMNAS is above both lidar and ICESat-2.

### Relative error (the number the twin needs), median removed

| Surface | RMSE after quadratic trend removed (m) | RMSE after 2 km moving mean removed (m) | RMS error of height difference at 0.5 / 1 / 2 km (m) |
|---|---|---|---|
| `dem_utm` | 2.48 | 1.89 | 2.29 / 2.61 / 2.94 |
| `dtm_corrected` | 2.26 | 1.86 | 2.24 / 2.55 / 2.84 |
| `dtm_smooth` | 1.80 | 1.25 | 1.20 / 1.67 / 2.08 |

NMAD of the same height-difference error for `dtm_smooth` is 0.96 / 1.43 / 1.88 m. Slope error (RMS height-difference error over baseline) is 2.4 m/km at 0.5 km, 1.7 m/km at 1 km and 1.0 m/km at 2 km. Semivariogram of `dtm_smooth` minus lidar: exponential fit, practical range about 7.4 km, partial sill 3.8 m² (SD about 2 m), nugget about 0. The correlated error has a range of several km, so it behaves as a regional tilt-and-bow, not as pixel noise.

For scale, the lidar surface itself differs by 0.85 m (RMS) over 0.5 km, 1.3 m over 1 km and 1.95 m over 2 km on this island (NMAD 0.34 / 0.60 / 1.07 m). At 1 to 2 km the smoothed DTM's height-difference error is the same size as the real height difference. **A 0.3 m head drop between blocks cannot be resolved on the smoothed DEMNAS surface**, and the first-pass ICESat-2 estimate (1.1 to 2.6 m RMS at 1 to 2 km) holds up against lidar (1.7 and 2.1 m).

### What this does and does not settle

- **Q1 (datum or DEM error).** Partly. The lidar and ICESat-2 agree in shape and differ by a constant 2 m, so ICESat-2 ground is a good relative reference at this site, and the DEMNAS error here is canopy and sheet offset, not a datum problem. The absolute offset between lidar and EGM2008 needs the lidar vendor's datum statement.
- **Q2 (open versus forest pattern).** Not reproduced at this site: lidar and ICESat-2 agree in all canopy classes to within 0.1 m of the offset.
- **Q3 (relative error).** Answered for this island: not good enough for a 0.3 m head drop.
- **Q4, Q5.** Not tested yet (no source-sheet map, no alternative DEMs run).
- Single site, single DEMNAS area. The lidar is 2016 and the DEMNAS and satellite epochs differ; on drained peat some of the residual may be subsidence, but the by-year medians do not show it.
- The unmasked ICESat-2 minus lidar RMSE is 4.25 m against an NMAD of 0.72 m, so a small share of points have large differences (not yet examined: canals, edges, ICESat-2 outliers).

## Lidar benchmark of the KLHK modelled DTMs and DEMNAS, five KHG (2026-10-25)

Script: `script/lidar_benchmark.py`, sites in `script/lidar_benchmark.yaml`, output `runs/lidar_benchmark.csv` and `.log`. Every valid lidar cell inside the KHG boundary is compared at native resolution with the nearest cell of each surface (no resampling, no calibration, no datum conversion). Statistics of surface − lidar (m); NMAD is around the median, so a constant datum offset does not affect it.

| KHG (lidar) | Surface | Cells | Median | NMAD | p05..p95 | Within 0.25 m of median |
|---|---|---|---|---|---|---|
| Pulau Padang (2 m, 2016) | KLHK modelled `DTM_Pulau_Padang` | 278 M | +2.68 | **1.20** | 1.02..4.82 | 17.9% |
| | DEMNAS (`DEMNAS_bengkalis`) | 278 M | +4.40 | 3.41 | −0.16..10.38 | 5.7% |
| Mendahara–Batanghari (`Jambi25m`) | KLHK modelled | 3.2 M | +0.71 | **1.11** | −1.83..2.11 | 19.8% |
| | DEMNAS (`DEMNAS_mendahara`) | 3.2 M | +0.73 | 2.12 | −1.91..6.30 | 10.0% |
| Air Hitam Laut–Buntu Kecil (`Muba25`) | KLHK modelled `WDTM_…` | 2.9 M | +4.96 | 3.53 | 0.28..9.09 | 5.8% |
| | Deltares Berbak-Muba lidar DTM | 2.8 M | +0.005 | 0.044 | −0.21..0.14 | 94.6% |
| | DEMNAS Sumatra JP2 | 2.9 M | +5.78 | **2.91** | 0.78..10.49 | 7.2% |
| Saleh–Sugihan (20 m, 2020; lidar on 62% of the KHG) | KLHK modelled | 2.9 M | +0.57 | **0.65** | −0.51..1.87 | 30.9% |
| | DEMNAS Sumatra JP2 | 2.9 M | +1.23 | 2.61 | −2.02..6.85 | 10.7% |
| Sugihan–Lumpur (`OKI25`) | KLHK modelled | 10.2 M | +1.28 | **0.71** | −0.07..2.46 | 27.9% |
| | DEMNAS Sumatra JP2 | 10.2 M | +2.14 | 3.17 | −2.14..14.14 | 9.1% |

**Findings.**
1. **The KLHK modelled DTMs are not lidar-derived** where lidar exists (NMAD 0.65 to 3.5 m against it), but at four of five KHG they are 2 to 4 times closer to the lidar than DEMNAS, with much shorter upper tails (canopy removed). At Pulau Padang, NMAD 1.20 m at native resolution against 2.00 m for this repo's `dtm_smooth` (30 m cells, median removed; section above).
2. **Air Hitam Laut is the exception:** the modelled file there is worse than DEMNAS. The BRGM contours of that KHG were traced from another version of this DTM (re-peat `reports/investigations/brgm_contour_source_khg_summary.csv`).
3. **`Muba25` and the Deltares Berbak-Muba DTM are the same surface to 4 cm NMAD**; they are not two independent lidar sources.
4. The modelled DTMs sit +0.6 to +2.7 m above the lidar (median). Padang includes the unexplained ~2 m lidar datum offset.
5. Not yet measured: relative error (height difference over 0.5 to 2 km), which is the number the twin needs. These are point-wise statistics only.
