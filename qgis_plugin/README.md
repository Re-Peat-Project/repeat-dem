# DEMNAS to DTM: QGIS Processing plugin

A QGIS port of `demnas_dtm.py`, split into stages you run from the Processing toolbox (group **DEMNAS to DTM**). It does not touch the command-line tool in the repo root and needs no rasterio or geopandas: rasters go through GDAL, vectors through the QGIS API and OGR.

| # | Algorithm | In | Saved to the output folder |
|---|---|---|---|
| 0 | **Download DEMNAS from BIG** (optional) | polygon or extent + your Ina-Geoportal link | `demnas_clipped.tif`, `tiles/` |
| 1 | **Prepare inputs** | DEMNAS tiles, AOI, optional canal/settlement layers | `dem_utm.tif`, `landcover.tif`, `canopy_height.tif`, `aoi_mask.tif`, `vector_mask.tif`, `prepare_report.json` |
| 5 | **Fetch ICESat-2 / GEDI points** (optional) | AOI | `ground_points_raw.gpkg` |
| 2 | **Calibrate against ground points** | points layer + rasters from 1 | `ground_points.gpkg` (with `exclude_reason`, `split`), `calibration.json`, `datum_diagnostics.json` |
| 3 | **Correct and smooth** | rasters from 1, optional `calibration.json` | `dtm_smooth.tif`, `dtm_corrected.tif`, `dtm_prior_k.tif`, `dtm_residual.tif`, `correction_m.tif`, `k_factor.tif`, `excluded_mask.tif`, `run_report.json` |
| 4 | **Validate surfaces** | `ground_points.gpkg` + any rasters | `validation.csv`, `ground_points_errors.gpkg` |

Typical order: 0 (only if you do not have the tiles yet), 1, then (5 or your own points), 2, 3, 4. You can skip 2 and 5 (placeholder k is then used, and the report says so), or stop after 1 and 3.

## Output folders and masks

Results are written to the **output folder**. Its default is `<project folder or home>/demnas_dtm/<algorithm>_<date-time>`, a new folder for every run, so trying other parameters never overwrites files that are open in QGIS. If you press Run again in the same dialog (same folder, results already loaded), the run goes to `<folder>_<HHMMSS>` instead and says so in the log. The main results are added to the project when the algorithm finishes, including the AOI and vector masks; their layer names carry the run folder, e.g. `DTM smoothed [correct_smooth_20261012-181530]`.

Algorithms 2 and 3 use `vector_mask.tif` and `aoi_mask.tif` found **next to the DEM file** when you leave those inputs empty (the normal chain after algorithm 1), and say so in the log. Without them canal cuts pull the surface down and gaps are filled beyond the AOI edge; algorithm 3 warns when either is missing.

## Install

1. `python build_zip.py` (in this folder) makes `demnas_dtm_qgis.zip`. The zip is not committed; share it with colleagues.
2. QGIS: *Plugins > Manage and Install Plugins > Install from ZIP*. The tools appear in the Processing toolbox as **DEMNAS to DTM**.

Or copy the `demnas_dtm_qgis` folder into the `python/plugins` folder of your QGIS profile (*Settings > User Profiles > Open Active Profile Folder*) and enable it.

**Python packages.** QGIS ships numpy, pyproj, PyYAML and GDAL. **scipy and pandas are not always included**: the OSGeo4W install of QGIS 4.2.3 tested here has neither. Install them once, either in the OSGeo4W Shell (`python -m pip install scipy pandas`) or with the OSGeo4W installer (Advanced Install, packages `python3-scipy` and `python3-pandas`), then restart QGIS.

| Algorithm | Needs besides what QGIS ships |
|---|---|
| 0 Download DEMNAS | nothing |
| 1 Prepare inputs | nothing |
| 3 Correct and smooth | scipy |
| 4 Validate | pandas |
| 2 Calibrate | scipy, pandas |
| 5 Fetch points | scipy, pandas, geopandas, shapely, sliderule |

Each algorithm checks first and names what is missing; the plugin itself always loads. Without sliderule, skip algorithm 5 and give algorithm 2 your own points (CSV, survey layer, an earlier export).

## Downloading DEMNAS (algorithm 0)

Same logic as `script/qgis_demnas_clip_download_helper.py` (which stays as it was), inside the plugin. You paste one fresh download link from the Ina-Geoportal (log in at tanahair.indonesia.go.id, open the DEMNAS download map, click any tile, copy the URL it opens); its token lasts about an hour and is reused for every tile. The tiles that touch the area are found from BIG's tile index, downloaded to `<output>/tiles` (or a folder you choose, which is reused on the next run), mosaicked, given EPSG:4326 (the tiles ship without a CRS) and clipped. The area is widened by 500 m by default so algorithm 1's own margin is not empty; set the buffer to 0 for the exact area. Feed `demnas_clipped.tif` to algorithm 1 as the DEM and leave the target CRS empty (algorithm 1 reprojects to UTM). The link is a credential: it is kept in QGIS's Processing history.

## Options

Basic parameters are shown; everything else is under **Advanced Parameters**. Every key of the command-line config is available:

- **Matrices** for k, bias and subsidence rates by land cover class. A class missing from the k table gets the "other classes" value.
- **Smoothing steps** as text, in order: `median:300; gaussian:150`, or `polynomial:4; gaussian:100`, or with keys `polynomial:degree=3,huber_m=1.0`.
- **Class lists** as comma text (`80, 50`).
- **Config YAML** (optional, same schema as the command-line tool, e.g. `config.example.yaml`) seeds the options. A widget you change overrides the file; **a widget left at its default value does not** (QGIS cannot tell "untouched" from "set to the default"). To force a default value over the YAML, change the YAML.
- The effective config is stored in `run_report.json` (algorithm 3) and `prepare_report.json` (algorithm 1).

## Differences from the command-line tool

- One buffer distance for all canal/settlement layers (the CLI allows one per layer).
- Ground points come from a QGIS point layer; the SlideRule cache is the output file of algorithm 5 itself.
- Algorithm 5 raises an error on zero points or a failed request (the CLI continues with the prior k). It splits large AOIs into tiles and checks for Cancel between them.
- Algorithm 3 additionally writes `dtm_prior_k.tif` so algorithm 4 can score the placeholder-k surface as well.
- Algorithm 4 samples any raster in its own CRS, so FABDEM, Copernicus GLO-30 or an airborne lidar DTM can be scored directly. The points' height field must be in the same vertical datum as the rasters.
- Whole grids are held in memory, as in the CLI. For a large AOI at 8 m, try 30 m first.

## What was checked, and where

`tests/compare_with_cli.py` runs algorithms 1 to 4 on a finished CLI run (`runs/exp_base`, 8 m, calibrated) and compares with that run's files. It passes identically on **QGIS 3.44.14** (conda-forge, Python 3.14) and on **QGIS 4.2.3** (OSGeo4W install, Python 3.12, scipy and pandas added):

| Stage | Result |
|---|---|
| 3 correct and smooth, fed the run's rasters and `calibration.json` | identical: max difference 0 m for `dtm_smooth`, `dtm_corrected`, `dtm_residual`, `correction_m`, `k_factor`, `excluded_mask` |
| 2 calibrate, fed the run's cached ICESat-2 points | identical split, exclusion reasons and ground heights; same k and bias per class |
| 4 validate | identical table (n, bias, RMSE, MAE, NMAD) for all four surfaces |
| 1 prepare inputs, local land cover and canopy rasters | same grid (2009 x 1998 px); land cover and canopy identical; DEM max difference 5e-7 m |

Algorithm 0 (`tests/download_with_fake_server.py`, passes on QGIS 3.44 and 4.2.3) runs against a local fake of BIG's tile index and download endpoints: worker-thread download of two CRS-less tiles, CRS assignment, clip (values identical to the source DEM), tile reuse with no new downloads, a clear error for an HTML page instead of a tile and for a bad link, and chaining into algorithm 1 (same DEM as the CLI's within 0.25 m at clip edges). **Not tested: BIG's real server with a real token.**

Also checked (QGIS 3.44): the defaults, quadkeys and WorldCover tiles are identical to the CLI's; the YAML/widget precedence; polynomial smoothing; a vector mask; re-running over open layers (clear error, nothing corrupted); on QGIS 4 without scipy/pandas, the provider loads, algorithm 1 runs and algorithms 2 to 4 name what to install; and on QGIS 4, algorithms 1 and 3 run the way the GUI runs them (worker thread via `QgsProcessingAlgRunnerTask`, layers taken from the project by id, results loaded back as valid layers, a second run into the same folder).

- **Algorithm 1, download mode** (small window, 8 m): land cover identical; canopy height identical except 40 of 4.0 million cells (0.001%, mean difference 4e-5 m, max 13 m), all in the two columns along the seam between two canopy-height tiles. The cause is the warp engine's edge handling there; not pursued.
- **Algorithm 5** (ICESat-2, same window): returned 5920 points. The CLI's own code run the same day returned 5585 (all of them also in the plugin's set), and a run four days earlier 6689. SlideRule's counts vary between requests, so this is not a plugin difference. Whether the time limit parameters are enforced by the service was not verified, and GEDI was not tried.

Not checked: the dialog windows themselves (matrix and field widgets were never opened on screen), the geoid-raster datum mode, GEDI, and download mode and algorithm 5 on QGIS 4.

## Maintenance

- `ground_truth.py` is shared with the command-line tool: the repo root file is the source. After changing it, run `python sync_ground_truth.py` (copies it into the plugin); `python sync_ground_truth.py --check` and `build_zip.py` fail when the copy is stale.
- Defaults in `core/config.py` mirror `demnas_dtm.DEFAULTS` (the ground defaults are read straight from `ground_truth.py`); keep the rest in step.
- Run the regression test with QGIS's Python (it needs the repo's `runs/exp_base` and `_data_sample/`): `python tests/compare_with_cli.py`.
