# RE-PEAT — DEM Preprocessing Notes (handover for local agent)

Context: RE-PEAT rewetting workflow (KLH / World Bank). The LiDAR DTM is the primary elevation input. The neraca air (water balance) module prioritises sub-KHG. LiDAR is rare, expensive and outdated in many KHG, so this note sets out how to prepare, correct, benchmark and fill elevation data from open sources.

Rule for this project: every algorithm used must be cited (see References).

---

## 1. Accuracy target (why this is hard)

- Peat domes are very flat. Surface gradients are on the order of ~1 m per km (Musthofa et al. 2022).
- Peat hydrological modelling needs vertical accuracy of about 0.1 m, and at least within 0.25 m (Euroconsult Mott MacDonald & Deltares 2009, EMRP Technical Review 4).
- Airborne LiDAR delivers this: East Sumatra LiDAR reported 0.050 m total vertical accuracy (Vernimmen et al. 2019).
- No open or global DEM reaches this. Treat open DEMs as coarse fallbacks for areas without LiDAR, not as replacements.
- Drained peat subsides fast (Hooijer et al. 2012): 142 cm in the first 5 years after drainage (75 cm in year one), then a steady ~5 cm/yr at ~0.7 m water-table depth. Any DEM from 2010–2015 is metres-scale stale on drained domes.

---

## 2. Candidate elevation datasets

| Dataset | Type | Grid | Vintage | Licence | Reported accuracy | Notes |
|---|---|---|---|---|---|---|
| LiDAR DTM (project) | DTM | ~1 m | varies | project | ~0.05 m (E. Sumatra) | Gold standard; patchy coverage and outdated |
| WorldDEM / WorldDEM Neo (Airbus) | DSM + DTM (L1 auto, L2 manual) | 12 m / 5 m | 2010–2014 / 2017–2021 | Commercial | Neo DTM: abs. < 1.4 m LE90; rel. < 2 m (slope ≤ 20%) | Vendor global spec, not tropical-peat specific. Check KLH redistribution terms |
| DEMNAS (BIG) | Mosaic (IFSAR 5 m, TerraSAR-X 5 m, ALOS PALSAR 11.25 m + stereo mass points) | 0.27″ (~8 m) | mixed | Free | 6.124 m (UGM study) to 8.172 m (GPS study, Susetyo 2023); errors uniform across elevation | Radar inputs, so expect canopy bias in peat swamp forest. Check seamlines. Datum EGM2008 |
| FABDEM | RF-corrected Copernicus GLO-30 | ~30 m | 2011–2015 | Research / non-commercial | Forest MAE 5.15 → 2.88 m vs COPDEM; ranked 1st of 5 global DEMs on 65 LiDAR sites (Meadows et al. 2024) | Derived from TanDEM-X, so a free, coarser, bare-earth cousin of WorldDEM |
| FathomDEM | Hybrid ViT/CNN (U-Net) correction of COPDEM | ~30 m | COPDEM epoch | CC BY-NC-SA 4.0 | Beats FABDEM in flood modelling; approaches LiDAR | Non-commercial licence is a concern for KLH deliverables |
| GEDTM30 (OpenGeoHub) | Global-to-local RF trained on ICESat-2 ATL08 + GEDI (~30 B points) | ~30 m | file epoch 2006–2015 | Open | −27.3% RMSE vs COPDEM where tree cover > 50% | Ships with a per-pixel uncertainty (SD) layer |
| DeltaDTM (Deltares / TU Delft) | COPDEM corrected with ICESat-2 + GEDI (classification + filtering + interpolation) | ~30 m | COPDEM epoch + ICESat-2 | CC BY 4.0 | MAE 0.45 m (v1); 0.43 m (v1.1) | Coastal: only land < 10 m +MSL, which covers most E. Sumatra peat. **Preferred open candidate** |

Priority for areas without LiDAR: **DeltaDTM → GEDTM30 → FabDEM/FathomDEM → DEMNAS** (re-rank after the local benchmark in §4).

---

## 3. Spaceborne LiDAR as free, current "ground truth"

- **ICESat-2 ATL08** (v7, NSIDC, DOI 10.5067/ATLAS/ATL08.007) gives along-track terrain height in 100 m segments.
- **GEDI L2A** gives lowest-mode elevation. It is less accurate for terrain than ICESat-2 (DeltaDTM does not use GEDI for bias correction).
- **Tropical peat evidence:** in Brunei peat, spatially filtering ATL08 ground photons (night, strong beams) cut RMSE from 3.85 m to 0.77 m and MAD from 1.51 m to 0.64 m (Cobb et al. 2023).
- **Filtering to apply:**
  - Strong beams only; night acquisitions preferred.
  - Quality flags: terrain quality score, uncertainty, and cloud flags.
  - Slope filter (slope strongly affects error).
  - Spatial filter / outlier rejection per Cobb et al. 2023.
  - Per-land-cover thresholds as in DeltaDTM (Pronk et al. 2024).
- **Datum:** convert ellipsoid heights to EGM2008 before any comparison.

---

## 4. Pipeline

### Step 0 — Harmonise
- Reproject everything to one CRS (UTM zone of the KHG) and a common vertical datum (EGM2008; record any MSL offset).
- Resample to the analysis grid (bilinear for continuous elevation). Keep the native-resolution copies.
- Mask water bodies and canals for statistics. Keep them for the canal water-depth step.

### Step 1 — Benchmark every candidate DEM against LiDAR
- Run where the LiDAR DTM exists, stratified by land cover (forest, plantation, shrub/burnt, open) and slope.
- Metrics:
  - Mean error (bias), RMSE, MAE.
  - LE90.
  - **NMAD** as the robust statistic (Höhle & Höhle 2009).
- Follow the land-cover/slope breakdown of Meadows et al. 2024.
- Also compare DEMs and LiDAR against filtered ATL08 points (independent, more recent).
- Output: ranking table per land cover, per KHG.

### Step 2 — Update outdated LiDAR (preferred where LiDAR exists)
- Do not discard old LiDAR. Treat it as a baseline:
  `DTM_now = DTM_lidar − subsidence_rate × (t_now − t_lidar)`
- Get subsidence rates from InSAR (Hoyt et al. 2020 mapped SE Asian peat subsidence with ALOS PALSAR InSAR; apply the same idea with Sentinel-1 / ALOS-2) or from field rates (~5 cm/yr after the initial drainage phase; Hooijer et al. 2012). Use a time-varying rate where drainage is recent.
- Check the result against recent ATL08 tracks crossing the area.

### Step 3 — Correct / fill open DEM where no LiDAR exists
Run these in order of preference and compare them under spatial CV.

**3a. DeltaDTM-style classification + interpolation (try first)**
- Co-register the open DEM to ICESat-2 (vertical bias removal).
- Classify and remove non-terrain cells using per-land-cover thresholds derived from ATL08/GEDI.
- Interpolate the gaps.
- Pronk et al. reported this classification approach beat regression/ML corrections (best MAE 0.72 m) (Pronk et al. 2024).

**3b. Residual regression (FABDEM-style)**
- Target: `DEM − reference terrain`, where the reference is LiDAR where available, else filtered ATL08.
- Predictors:
  - Canopy height and cover.
  - Land cover.
  - Sentinel-1 backscatter.
  - Slope / roughness.
  - Optionally, Earth embeddings (§5).
- Model: random forest (Breiman 2001; Hawker et al. 2022). Variant: RF–GWR hybrid.

**3c. Regression-kriging of residuals**
- Krige the model residuals at ATL08 points (Hengl, Heuvelink & Stein 2004). Peat domes are smooth, so residuals should interpolate well.
- Precedent: interpolating a correction surface from filtered ICESat-2 terrain control points to correct SRTM in forest (Li et al. 2022).

**Avoid as a primary method: DEM super-resolution nets**
- Examples: U-Net residual models using 30 m DEM + Sentinel-2; prior-based ViT reconstruction.
- They need high-resolution DEM training labels (i.e. LiDAR again).
- They add plausible-looking detail but not vertical accuracy. On flat peat this detail is mostly hallucination.

### Step 4 — Validation (mandatory)
- Use **spatial block cross-validation**, not random splits (Roberts et al. 2017; Ploton et al. 2020). Embeddings and DEM errors are spatially autocorrelated, so random CV inflates scores.
- Hold out whole LiDAR blocks / sub-KHG. Report per land cover.
- Use the GEDTM30 SD layer or RF tree spread as an uncertainty map, and carry uncertainty into neraca air.

### Step 5 — Derived products for neraca air / rewetting
- **Canal water depth (CWD) from LiDAR** (Deltares method; Vernimmen et al. 2020, *Water*):
  - Water level = minimum of the 1 m DTM within each 100 m × 100 m cell.
  - Soil surface = median of that cell.
  - CWD = difference.
  - Validated within 0.25 m for 86% of 145 field points (R² 0.74).
  - Valid only at the LiDAR acquisition date.
- **Peat thickness baseline:** DTM − flat peat bottom.
  - Peat bottom was ~0.61 m +MSL in eastern Sumatra (mean of 2446 field points; Vernimmen et al. 2020, *Carbon Balance Manage.*).
  - Thickness correlates with LiDAR surface elevation, R² 0.83–0.88.
  - Use as a baseline against the RF/Cubist peat-depth models:
    - Musthofa et al. 2022: RF on DEM + SAR, RMSE 0.483 m, R² 0.786.
    - UGM thesis, KHG Mendahara–Batanghari: Cubist RMSE 70.88 cm, R² 0.82; elevation was the top covariate.
- **Drainability / flood risk framing** (Deltares 2015, Kampar report): subsidence brings land toward drainability limits. By 2014, 31% of Kampar plantation area already had regular flooding/drainage problems. Improved plantation water management reduces subsidence and carbon loss by 20% at most (Hooijer et al. 2012; restated in the Kampar report). Use this framing for sub-KHG prioritisation.
- **Cost-saving design for any new LiDAR:** strip LiDAR covering 10–35% of the land + interpolation gave within 0.5 m of full coverage for 87.7–96.4% of area (Vernimmen et al. 2019).

---

## 5. Earth embeddings (OlmoEarth / AlphaEarth / TESSERA): role and limits

**Use them as covariates, not as an elevation source.**

Pros:
- Cloud-robust multi-sensor input. OlmoEarth Studio exports COGs with selectable area, time span, model size, resolution, and S1 or S2 source (int8 bands).
- Good with few labels: land cover, drainage state, burn scars (these feed ET/runoff terms).
- AlphaEarth reached R² 0.58 for evapotranspiration, where other baselines were < 0.2 (Brown et al. 2025).
- OlmoEarth weights and code are open and fine-tunable. It was on par with or better than AEF in kNN comparisons (Herzog et al. 2025).

Cons:
- They encode the surface, not ground under canopy. They cannot deliver the decimetre-level relative heights peat hydrology needs.
- AlphaEarth is annual only; neraca air is monthly. OlmoEarth custom windows help, but quality depends on cloud cover and missing data.
- Low interpretability and limited spatial transferability (AEF agricultural benchmark, arXiv 2601.00857). This makes them harder to defend to KLH.
- Possible circularity: AEF assimilates elevation/LiDAR inputs. Check leakage before using embeddings to correct DEMs.

Decisive test: do embeddings meaningfully reduce the `DEM − LiDAR` residual in Step 3b under spatial CV? If not, use them only on the land-cover/ET side of neraca air.

---

## 6. Open items / decisions for the team

- [ ] Confirm the licence acceptability of FABDEM / FathomDEM (non-commercial) for KLH deliverables; DeltaDTM is CC BY 4.0.
- [ ] Get the LiDAR acquisition dates per KHG (needed for the subsidence update).
- [ ] Choose a subsidence-rate source: InSAR product vs field rates.
- [ ] Decide the analysis grid (e.g. 30 m for neraca air vs LiDAR-native for canal work).
- [ ] Decide whether WorldDEM Neo DTM L2 is worth purchasing for priority KHG.
- [ ] Check for newer Sumatra outputs from Data for Sustainability (Vernimmen & Hooijer's current organisation).

---

## References

All entries verified online on 2026-10-24 (publisher page, DOI record, or repository). DOIs are given wherever one exists.

**Algorithms and validation**
- Breiman, L. (2001). Random forests. *Machine Learning* 45(1):5–32. doi:10.1023/A:1010933404324.
- Hengl, T., Heuvelink, G.B.M., Stein, A. (2004). A generic framework for spatial prediction of soil variables based on regression-kriging. *Geoderma* 120(1–2):75–93. doi:10.1016/j.geoderma.2003.08.018.
- Höhle, J., Höhle, M. (2009). Accuracy assessment of digital elevation models by means of robust statistical methods. *ISPRS J. Photogramm. Remote Sens.* 64(4):398–406.
- Ploton, P., Mortier, F., Réjou-Méchain, M. et al. (2020). Spatial validation reveals poor predictive performance of large-scale ecological mapping models. *Nature Communications* 11:4540. doi:10.1038/s41467-020-18321-y.
- Quinlan, J.R. (1993). Combining instance-based and model-based learning. *Proc. 10th Int. Conf. on Machine Learning (ICML)*, pp. 236–243. doi:10.1016/B978-1-55860-307-3.50037-X. (Cubist = Quinlan's M5 rule model, "Learning with continuous classes" (1992), plus this instance-based correction, per the R `Cubist` package documentation.)
- Roberts, D.R., Bahn, V., Ciuti, S. et al. (2017). Cross-validation strategies for data with temporal, spatial, hierarchical, or phylogenetic structure. *Ecography* 40(8):913–929. doi:10.1111/ecog.02881.

**DEMs and DEM correction**
- Hawker, L., Uhe, P., Paulo, L., Sosa, J., Savage, J., Sampson, C., Neal, J. (2022). A 30 m global map of elevation with forests and buildings removed. *Environ. Res. Lett.* 17:024016. doi:10.1088/1748-9326/ac4d4f.
- Ho, Y.-F., Grohmann, C.H., Lindsay, J., Reuter, H.I., Parente, L., Witjes, M., Hengl, T. (2025). GEDTM30: global ensemble digital terrain model at 30 m and derived multiscale terrain variables. *PeerJ* (published 2025-07-24). doi:10.7717/peerj.19673. Data: Zenodo / OpenLandMap STAC.
- Li, Y., Fu, H., Zhu, J. et al. (2022). A method for SRTM DEM elevation error correction in forested areas using ICESat-2 data and vegetation classification data. *Remote Sensing* 14(14):3380. doi:10.3390/rs14143380. (Tested in Massachusetts: SRTM RMSE 9.8 m → 4.2 m.)
- Meadows, M., Jones, S., Reinke, K. (2024). Vertical accuracy assessment of freely available global DEMs (FABDEM, Copernicus DEM, NASADEM, AW3D30 and SRTM) in flood-prone environments. *Int. J. Digital Earth* 17(1). doi:10.1080/17538947.2024.2308734.
- Pronk, M., Hooijer, A., Eilander, D., Haag, A., de Jong, T., Vousdoukas, M., Vernimmen, R., Ledoux, H., Eleveld, M. (2024). DeltaDTM: A global coastal digital terrain model. *Scientific Data* 11:273. doi:10.1038/s41597-024-03091-9. Data (CC BY 4.0): doi:10.4121/21997565 (v1.1, MAE 0.43 m).
- Susetyo, D.B. (2023). Vertical accuracy assessment of various open-source DEM data: DEMNAS, SRTM-1, and ASTER GDEM. *Geodesy and Cartography* 49(4). doi:10.3846/gac.2023.18168.
- Uhe, P., Lucas, C., Hawker, L. et al. (2025). FathomDEM: An improved global terrain map using a hybrid vision transformer model. *Environ. Res. Lett.* 20(3):034002. doi:10.1088/1748-9326/ada972. Data (CC BY-NC-SA 4.0): Zenodo record 14511570.
- Airbus Defence and Space. WorldDEM Neo DTM — product description / fact sheet (vendor specification).
- Badan Informasi Geospasial (BIG). DEMNAS product page (sources, 0.27″ grid, EGM2008 datum).
- UGM thesis (etd 174783): vertical accuracy of DEMNAS vs TerraSAR-X and SRTM (6.124 m, 95 test points).

**Spaceborne LiDAR**
- Cobb, A.R., Dommain, R., Sukri, R.S., Metali, F., Bookhagen, B., Harvey, C.F., Tang, H. (2023). Improved terrain estimation from spaceborne lidar in tropical peatlands using spatial filtering. *Science of Remote Sensing* 7:100074. doi:10.1016/j.srs.2022.100074.
- NSIDC. ATLAS/ICESat-2 L3A Land and Vegetation Height (ATL08), Version 7. doi:10.5067/ATLAS/ATL08.007.

**Peat subsidence, hydrology and Deltares work in Sumatra**
- Deltares (2015, November). Assessment of impacts of plantation drainage on the Kampar Peninsula peatland, Riau. Report commissioned by Wetlands International.
- Euroconsult Mott MacDonald & Deltares (2009, January). Quickscan evaluation of use of laser-altimetry data to assess peat land topography, canopy structure and subsidence. EMRP Master Plan, Technical Review No. 4.
- Hooijer, A., Page, S., Jauhiainen, J., Lee, W.A., Lu, X.X., Idris, A., Anshari, G. (2012). Subsidence and carbon loss in drained tropical peatlands. *Biogeosciences* 9(3):1053–1071. doi:10.5194/bg-9-1053-2012.
- Hoyt, A.M., Chaussard, E., Seppalainen, S.S., Harvey, C.F. (2020). Widespread subsidence and carbon emissions across Southeast Asian peatlands. *Nature Geoscience*. doi:10.1038/s41561-020-0575-4.
- Vernimmen, R., Hooijer, A., Yuherdha, A.T., Visser, M., Pronk, M., Eilander, D., Akmalia, R., Fitranatanegara, N., Mulyadi, D., Andreas, H., Ouellette, J., Hadley, W. (2019). Creating a lowland and peatland landscape digital terrain model (DTM) from interpolated partial coverage LiDAR data for Central Kalimantan and East Sumatra, Indonesia. *Remote Sensing* 11:1152. doi:10.3390/rs11101152.
- Vernimmen, R., Hooijer, A., Akmalia, R., Fitranatanegara, N., Mulyadi, D., Yuherdha, A., Andreas, H., Page, S.E. (2020). Mapping deep peat carbon stock from a LiDAR based DTM and field measurements, with application to eastern Sumatra. *Carbon Balance Manage.* 15:4. doi:10.1186/s13021-020-00139-2.
- Vernimmen, R., Hooijer, A., Mulyadi, D., Setiawan, I., Pronk, M., Yuherdha, A.T. (2020). A new method for rapid measurement of canal water table depth using airborne LiDAR, with application to drained peatlands in Indonesia. *Water* 12(5):1486. doi:10.3390/w12051486.

**Peat thickness (local baselines)**
- Musthofa, F., Widyatmanti, W., Arjasakusuma, S., Umarhadi, D.A., Putri, D.A., Raharja, F.F., Arrasyid, M.K. (2022). Machine learning for mapping spatial distribution of thickness and carbon stock of tropical peatland based on remote sensing data: a case study in Lake Sentarum National Park, Indonesia. *Geographia Technica* 17(1):46–57. doi:10.21163/GT_2022.171.04.
- UGM thesis (etd 268786): peat thickness modelling with LiDAR DTM and multisource data (RF, Cubist, XGBoost), KHG Sungai Mendahara–Sungai Batanghari.

**Earth embeddings**
- Brown, C.F., Kazmierski, M.R., Pasquarella, V.J. et al. (2025). AlphaEarth Foundations: An embedding field model for accurate and efficient global mapping from sparse label data. arXiv:2507.22291.
- Herzog, H. et al. (2025). OlmoEarth: Stable Latent Image Modeling for Multimodal Earth Observation. arXiv:2511.13655. Code/weights: github.com/allenai/olmoearth_pretrain.
- Harvesting AlphaEarth: Benchmarking the Geospatial Foundation Model for Agricultural Downstream Tasks. arXiv:2601.00857 (source of the transferability/interpretability limits).
