# NISAR for peat subsidence at the two KHG test sites

Date: 2026-11-04. Source labels in the reference list: **[F]** full text or full page fetched and read; **[A]** abstract or landing page only; **[S]** search-engine snippet only (not opened, so check before citing). The ASF/CMR numbers come from metadata queries run on 2026-11-04 [35]. No data products were downloaded.

## Short answer

- NISAR L-band data over both sites are public and free, but the calibrated (PROVISIONAL) record starts on **17 June 2026**. As of today each site has 9–10 dates per track over about four months. No earlier (BETA) products exist over either bounding box [35].
- Four months is too short to give a rate. At 3–5 cm/yr, the trend adds up to 1–2 cm over the record, which is smaller than the dry-season shrinkage measured in drained peat (over 8 cm in 2019) [20]. This is our inference.
- NISAR cannot cover the time between the LiDAR flight and now. For 2014–2025 the usable open source is the **ALOS-2 PALSAR-2 ScanSAR** archive at ASF: 131–143 scenes on one descending path that fully covers each site [35]. This is the same sensor and mode that Tay et al. (2025) validated against peat cameras [19].
- Recommendation: start an ALOS-2 ScanSAR stack now. For NISAR, run only a coherence and ionosphere test now, and expect usable rates once about two dry–wet cycles have been recorded (2028).

## 1. Mission status

- Launched 30 July 2025 on GSLV-F16 from Sriharikota [1][2]. The reflector deployed on 15 August 2025 [3]. NASA dates the start of science operations to early January 2026 [1].
- Orbit: 747 km, 12-day exact repeat, nodal crossings at 6 AM ascending and 6 PM descending, left-looking. Resolution is 3–10 m depending on mode. L-band is acquired globally; S-band covers India and cal/val sites, and S-band data are distributed through ISRO's Bhoonidhi [1].
- Data releases [4]:
  - 25 sample products on 23 January 2026.
  - More than 100,000 BETA (pre-calibration) products on 27 February 2026, drawn from 17 October 2025 – 20 January 2026.
  - Global PROVISIONAL (calibrated, partly validated) products on 20 July 2026, covering acquisitions from 17 June 2026 onward.
  - A validated reprocessing of the full archive is planned to finish by the end of 2026.
- A permanent instrument gap runs from 2026-07-27 to 2026-08-10 [4]. PROVISIONAL production has been paused since 23 October 2026 for a software upgrade and is expected to resume after 9 November [5].
- Planning documents list 20 MHz dual-pol for "background land" [6][7], but the site metadata show **40+5 MHz, HH+HV, ascending and descending, every cycle** [35]. At 40 MHz the GSLC is posted at 5 × 5 m [8].

## 2. Products, access, and what exists over the sites

- **Products:** RSLC (L1); GSLC (L2, 5–40 m, phase-flattened, so two GSLCs cross-multiply directly into an interferogram) [8][9]; GUNW (L2: unwrapped phase at 80 m, wrapped phase and coherence at 20 m, plus an ionospheric phase screen and troposphere/solid-earth-tide layers that are *not* applied) [11]; GCOV (10/20/80 m); GOFF (80 m); RIFG/RUNW/ROFF; and SME2 soil moisture (200 m) [9]. All products are HDF5 [10].
- **GUNW pairs are only 12-day nearest-neighbour, co-pol, frequency A** [11]. Longer pairs have to be built from GSLC/RSLC. On-demand GUNW for custom pairs through HyP3 is still in development [15].
- **Access:** ASF DAAC / Earthdata Cloud. Search needs no login; downloads need an Earthdata Login (`.netrc`). Tools are Vertex, Earthdata Search, `asf_search` and `earthaccess` [12].
- **No ready-made displacement product for Indonesia.** OPERA DISP-NI covers North America only and starts with the validated record [13]. A forum reply gives February 2027 as the earliest production date [14]. OPERA DISP-S1 returned 0 granules over both bounding boxes [35].

ASF/CMR query results, 2026-11-04 [35]:

| | Mendahara–Batanghari (103.3–104.0 E, 1.35–0.7 S) | Sugihan–Lumpur (105.2–105.95 E, 3.45–2.55 S) |
|---|---|---|
| RSLC / GSLC / GCOV / SME2 (PROVISIONAL) | 28 each | 18 each |
| GUNW | 25 | 16 |
| L0B RRSD | 46 | 18 |
| GOFF, RIFG, RUNW, ROFF; any BETA | 0 | 0 |
| First / last acquisition | 2026-06-17 / 2026-10-19 | 2026-06-22 / 2026-10-20 |
| Track (frame, bbox coverage, dates) | 047 D (089, 100 %, 10); 112 A (001, 100 %, 9); 011 A (001, 9 %, 9) | 119 D (090, 100 %, 9); 010 A (176, 100 %, 9) |

Every track is missing cycle 027, which matches the instrument gap. One GUNW spans the gap: 2026-07-15 to 08-20, a 36-day pair. Across all of Sumatra (95–106 E, 6 S–6 N), the earliest PROVISIONAL GSLC is dated 2026-06-16, so no backfill exists here yet. ASF plans backfill only for "a limited set of NISAR frames" [4].

## 3. Suitability for tropical peat

- **L-band compared with C-band:** On Bengkalis (2018–2019), PALSAR-2 gave −2.65 cm/yr and Sentinel-1 gave −1.41 cm/yr. RMSE against a groundwater-derived reference was 1.38 cm/yr for PALSAR-2 and 1.99 cm/yr for Sentinel-1, and Sentinel-1 underestimated subsidence [16]. With PALSAR-2 SBAS, a coherence threshold of 0.4 still covered almost the whole island [17]. Hoyt et al. (2020) used ALOS PALSAR for 2007–2011 at 90 m over 2.7 Mha and found a mean of 2.2 cm/yr, with more than 90 % of the area subsiding [18].
- **Best validation so far:** Tay et al. (2025) used 92 ALOS-2 ScanSAR images (2018-10-12 to 2024-08-09) over Central Kalimantan and compared them with 8 peat cameras on oil palm, cropland, fern scrub and forest [19]. Results:
  - Long-term rates matched the cameras with an RMSE of 0.36 cm/yr.
  - Epoch-to-epoch RMSE was 1.70 cm. The forest site was weakest (r = 0.40).
  - Noise terms: ionospheric noise up to 6.7 m (mean 2.3 m) across the 350 km scene, removed by range split-spectrum; closure-phase bias that produced up to 30 cm of false subsidence over 5.5 years, mostly over scrub and forest; troposphere up to 15 cm. Global weather-model corrections did not help.
  - Processing: ISCE2 alosStack and MintPy.
- **Seasonal oscillation that the trend must be separated from:**
  - Peat cameras in Central Kalimantan recorded more than 8 cm of shrinkage in the 2019 dry season, then partial rebound and a net subsidence of up to 5 cm/yr. Forest sites moved least [20].
  - Cameras in South Sumatra showed amplitudes of 4.9 cm under oil palm and 4.8 cm under forest [21].
  - Sentinel-1 over Jambi and South Sumatra shows extra subsidence in 2019, a positive-IOD year [23]; Acacia plantations in Sumatra averaged 4.3 cm/yr [22].
- **Ionosphere:** ASF says PROVISIONAL products meet requirements "in lower-latitude areas where ionospheric variability is low". The 5 MHz frequency-B band used for split-spectrum still has larger calibration residuals [24]. The 6 PM descending pass falls near the post-sunset plasma-bubble period. An ESA study rates the chance of L-band scintillation at 06/18 h as small but not negligible, with the largest TEC gradients at equinoxes [25]. Ascending and descending results should be compared before they are trusted.
- **Length of record needed (inference):** with oscillations of 5–8 cm and trends of 3–5 cm/yr, a stable rate needs at least one full dry–wet cycle, and preferably two or three. Tay et al. used 5.5 years. NISAR reaches two years over these sites in mid-2028.
- **NISAR peat work:** no NISAR peat subsidence study was found. NISAR's ecosystem requirements are biomass, disturbance, inundation and crop area at 100 m [26]. They do not include subsidence.

## 4. The key limitation, and sources for 2014–2025

The public NISAR record over these sites starts in June 2026. NISAR can give a present-day rate per land class, which can be compared with the ICESat-2 trend, but it cannot date or correct the LiDAR. Options for the gap:

- **ALOS-2 PALSAR-2 ScanSAR L1.1:** free and open under JAXA usage conditions (attribution required) and archived at ASF as `ALOS2_L1_PSR2` [27].
  - Mendahara–Batanghari: 530 granules, 2014-08-15 to 2025-03-29. Descending paths 34 and 35 (frame 3650) each cover 100 % of the bounding box, with 135 and 131 scenes.
  - Sugihan–Lumpur: 717 granules. Path 33, frame 3700, descending, covers 100 % of the box with 143 scenes (2014-09-02 to 2025-03-18) [35].
  - JAXA states that ScanSAR data through July 2025 has been released [28]. Full-aperture L1.1 files are about 30 GB single-pol and 60 GB dual-pol [29].
- **ALOS-4 PALSAR-3:** standard products are available only through data providers or JAXA research agreements, not as open data [30].
- **Sentinel-1:** free, but at C-band it underestimates subsidence and decorrelates [16]. In Central Kalimantan, a coherence threshold of 0.25 still covered only two-thirds of the area [31]. Khakim et al. (2020) mapped KHG Sungai Sugihan–Sungai Saleh, next to our southern site, and found subsidence 6.4 times faster after the 2015 fires than before [32]. No open Sentinel-1 peat-subsidence product for Sumatra was found. EGMS was not checked.
- **Published maps:** Hoyt et al. (2020) state that their rates are on Zenodo at doi:10.5281/zenodo.3694667 [18]. On 2026-11-04 that DOI did not resolve (doi.org "DOI Not Found", Zenodo API 404), so contact the authors. Whether their frames include our sites is unconfirmed. The Tay et al. data release (doi:10.21979/N9/JGQE4O) covers Central Kalimantan only [33].

## 5. Recommendation

1. **NISAR is not usable yet for rates at these sites.** It is usable now for a feasibility test. Download the 10 GSLCs and 9 GUNWs for track 047 D (Mendahara–Batanghari) and the 9 GSLCs for track 119 D (Sugihan–Lumpur). Measure coherence at 12, 24, 36 and 48 days for each class: KLHK land cover, plantation licence areas (HGU/HTI), burned fern land and remaining forest. Check the magnitude of the ionospheric screen on the 6 PM descending passes. Estimated effort: 3–5 days.
2. **Main processing chain for 2014–2025:** ALOS-2 ScanSAR from ASF → ISCE2 alosStack (split-spectrum ionosphere correction) → MintPy SBAS with closure-phase correction → vertical rate, assuming no horizontal motion → mean rate by land class, licence and distance to canal → compare with ICESat-2 minus LiDAR. Start with a pilot on path 35/3650 or 33/3700 using about 30 scenes from 2018–2024. Budget several TB of storage per path. Estimated effort: 2–3 weeks for the pilot.
3. **Later NISAR processing chain:** GUNW stacks can go directly into MintPy `prep_nisar`, which reads the ionosphere, troposphere and solid-earth-tide layers [34]. The 12-day-only network is exposed to the closure-phase bias that Tay et al. found over scrub and forest [19], so build 24–48-day pairs from GSLC as well. Re-run after the validated reprocessing (end of 2026) and after the 2027 dry season.

## References

1. [F] NASA, NISAR Mission Overview. https://science.nasa.gov/mission/nisar/mission-overview/
2. [S] NASA, "NASA-ISRO Satellite Lifts Off…", 30 Jul 2025. https://www.nasa.gov/news-release/nasa-isro-satellite-lifts-off-to-track-earths-changing-surfaces/
3. [F] ISRO, NISAR Mission enters Science Phase. https://www.isro.gov.in/ISRO_EN/NISAR_Mission_Science_Phase.html
4. [F] ASF, Available NISAR Data. https://nisar-docs.asf.alaska.edu/availability-overview/
5. [F] NASA Earthdata, NISAR provisional production paused. https://www.earthdata.nasa.gov/data/alerts-outages/nisar-provisional-data-product-production-paused
6. [F] Rosen & Lavalle, NISAR, PolInSAR 2023 slides. https://polinsar-biomass2023.esa.int/iframe-agenda/files/225-Lavalle_NISAR_RosenLavalle_PolInSAR2023.pdf
7. [F] Chapman, NISAR validation, CEOS 2024. https://calvalportal.ceos.org/html/portal/sarc/documents/documents/CEOS_2024_Bruce%20chapman.pdf
8. [F] ASF, GSLC product. https://nisar-docs.asf.alaska.edu/gslc/
9. [F] ASF, NISAR Data Products. https://nisar-docs.asf.alaska.edu/products-overview/
10. [S] NASA Earthdata, NISAR L-Band Data Now Publicly Available. https://www.earthdata.nasa.gov/data/alerts-outages/nisar-l-band-data-now-publicly-available
11. [F] ASF, GUNW product. https://nisar-docs.asf.alaska.edu/gunw/
12. [F] ASF, Accessing NISAR Data. https://nisar-docs.asf.alaska.edu/access-overview/
13. [F] JPL, OPERA Products. https://www.jpl.nasa.gov/go/opera/products/
14. [S] Earthdata Forum, DISP-NI availability. https://forum.earthdata.nasa.gov/viewtopic.php?t=8134
15. [F] ASF, Tools and Services. https://nisar-docs.asf.alaska.edu/tools-services-overview/
16. [S] Umarhadi et al. 2021, Land Degrad. Dev. 32, 4779–4794. https://doi.org/10.1002/ldr.4061
17. [S] Umarhadi et al. 2022, Sci. Total Environ. 816, 151561. https://doi.org/10.1016/j.scitotenv.2021.151561
18. [A] Hoyt et al. 2020, Nat. Geosci. 13, 435–440. https://doi.org/10.1038/s41561-020-0575-4
19. [F] Tay et al. 2025, Commun. Earth Environ. 6. https://doi.org/10.1038/s43247-025-02926-6
20. [F] Evans et al. 2021, Front. Environ. Sci. 9, 630752. https://doi.org/10.3389/fenvs.2021.630752
21. [S] Peat cameras, South Sumatra & Central Kalimantan, IOP Conf. Ser. EES 1025, 012011. https://iopscience.iop.org/article/10.1088/1755-1315/1025/1/012011/pdf
22. [S] Evans et al. 2019, Geoderma 338, 410–421. https://doi.org/10.1016/j.geoderma.2018.12.028
23. [S] Izumi et al. 2022, Remote Sens. 14, 5825. https://www.mdpi.com/2072-4292/14/22/5825
24. [F] ASF, Provisional product known issues. https://nisar-docs.asf.alaska.edu/provisional-known-issues/
25. [S] ESA, low-latitude ionosphere study (Biomass), executive summary. https://nebula.esa.int/sites/default/files/neb_tec_study/1264/public/C4000117285ExS.pdf
26. [S] NASA, NISAR Mission Requirements. https://science.nasa.gov/mission/nisar/mission-requirements2/
27. [F] CMR collection record ALOS2_L1_PSR2 (licence, FreeAndOpenData). https://cmr.earthdata.nasa.gov/search/collections.umm_json?short_name=ALOS2_L1_PSR2
28. [F] JAXA, ALOS-2 PALSAR-2 ScanSAR products. https://www.eorc.jaxa.jp/ALOS/en/dataset/palsar2_l22_e.htm
29. [F] JAXA, ALOS series Open and Free Data. https://www.eorc.jaxa.jp/ALOS/en/dataset/alos_open_and_free_e.htm
30. [F] JAXA, ALOS-4 Getting Started with Data. https://www.eorc.jaxa.jp/ALOS/en/alos-4/a4_data_e.htm
31. [S] Umarhadi & Siegert 2026, Environ. Res. Commun. https://iopscience.iop.org/article/10.1088/2515-7620/ae43ab
32. [S] Khakim et al. 2020, Int. J. Appl. Earth Obs. Geoinf. 84, 101953. https://doi.org/10.1016/j.jag.2019.101953
33. [F] Tay et al. 2025 data, DR-NTU. https://doi.org/10.21979/N9/JGQE4O
34. [S] MintPy PR #1487, NISAR loading and auxiliary stacks. https://github.com/insarlab/MintPy/pull/1487
35. Own metadata queries, 2026-11-04: ASF SearchAPI `https://api.daac.asf.alaska.edu/services/search/param?dataset=NISAR&bbox=<bbox>&processingLevel=<RSLC|GSLC|GUNW|GCOV|SME2|L0B>&output=json` and `platform=ALOS-2`; CMR `https://cmr.earthdata.nasa.gov/search/granules.json?short_name=<NISAR_*_PROVISIONAL_V1|NISAR_*_BETA_V1|OPERA_L3_DISP-S1_V1|ALOS2_L1_PSR2>&bounding_box=<bbox>`. Raw JSON is in `%LOCALAPPDATA%/hermes/cache/scratch/nisar/`.
