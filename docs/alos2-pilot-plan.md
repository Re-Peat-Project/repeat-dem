# L-band subsidence pilot with ALOS-2 PALSAR-2 ScanSAR: plan (deferred)

Status 2026-11-04: deferred by the project owner, who wants L-band (not Sentinel-1 C-band) and will run the processing later. This note holds what is needed to start. Background and sources: `docs/nisar-subsidence.md`; the ICESat-2 result it should test: `runs/checks/icesat2_subsidence_trend.md`.

## Why

ICESat-2 2019-2025 shows drained land sinking (-5.2 cm/yr inside licences at Sugihan-Lumpur, -3.7 cm/yr at Mendahara-Batanghari, about 0 outside) on sparse 100 m track segments. An L-band InSAR rate map would give the same quantity wall to wall, over 2014-2025, which covers the unknown LiDAR dates. Tay et al. 2025 matched peat cameras to 0.36 cm/yr with ALOS-2 ScanSAR (see the NISAR note).

## Scenes (ASF, open, metadata queried 2026-11-04)

`script/alos2_scene_inventory.py --khg "<KHG>"` writes the scene lists `docs/alos2_scenes_<khg>.csv` (scenes covering at least 20% of the KHG).

- Sugihan-Lumpur: path 33, frame 3700, descending, ScanSAR WBD, HH+HV: 143 scenes, 2014-09-02 to 2025-03-18, covering 99% of the KHG; 8.69 TB in total, about 61 GB per scene. Per year: 3 (2014), 7, 9, 8, 18 (2018), 18, 16, 18, 16, 14, 12, 4 (2025).
- Mendahara-Batanghari: path 34 frame 3650 (135 scenes) and path 35 frame 3650 (131 scenes), descending WBD, each covering 100% of the KHG, 2014-2025, about 8 TB per path.
- ASF holds ALOS-2 ScanSAR only up to March 2025; ASF stated in March 2026 that newer acquisitions stay unavailable while the satellite is active (Earthdata forum thread, read as a search snippet). JAXA also lists the ScanSAR L1.1 archive on the AWS Registry of Open Data (`jaxa-alos-palsar2-scansar`), not yet checked.

## Blockers on this machine (checked 2026-11-04)

- Disk: C: has 17 GB free; a 30-scene pilot is about 1.8 TB of input before processing.
- No NASA Earthdata login: no `~/.netrc`, and the browser vault holds no saved login. Downloads from ASF need one; the owner creates `.netrc` (credentials are never typed by the agent).
- No Linux InSAR stack installed: ISCE2 alosStack runs on Linux; Docker and WSL are present. 16 cores, 16 GB RAM: tight for full-aperture ScanSAR.

## Options when the work resumes

1. Local: an external drive of at least 2 TB, Earthdata login, ISCE2 (alosStack) in Docker or WSL, MintPy.
2. Cloud: a VM in the same AWS region as the JAXA open-data bucket, so nothing is downloaded locally; costs compute and needs an AWS account.
3. Smaller first step: NISAR coherence and ionosphere check on the few GUNW/GSLC files over the sites (small, Earthdata login only).

## Processing chain (from the NISAR note)

ALOS-2 L1.1 → ISCE2 alosStack with range split-spectrum ionosphere correction → MintPy SBAS with closure-phase (phase-bias) correction → vertical rate assuming no horizontal motion → mean rate by licence, distance to canal and ForTy class → compare with the ICESat-2 trends and the ICESat-2-minus-LiDAR offsets. Pilot: about 30 scenes from 2018-2024 on path 33 frame 3700 (Sugihan-Lumpur), the years with 14-18 scenes a year. Write the success criteria into a config before the first rate exists (agreement with the ICESat-2 inside/outside-licence contrast within its interval), as for the other checks.
