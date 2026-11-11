# ML correction of open DEMs: literature and possible avenues (parked)

Recorded 2026-11-10 as a possible line of work for repeat-dem; nothing here has been tested. The paper summaries below come
from a literature search shared in the project chat (starting from Ouyang et al. 2025, FREEL). Their reported numbers are
the papers' own and have not been checked against the papers; read the methods sections before citing any of them.

## Why it is on the list

Processed DeltaDTM is off by 0.45-0.70 m at 1 km on peat at the four LiDAR sites, against the 0.30 m criterion, and no simple
fix passed (forest-type offsets, canal masks, dome fits; `benchmark/*.yaml` run records, README). An ML model trained on
(open DEM minus LiDAR DTM) residuals and predicting them where there is no LiDAR is the approach of FABDEM and FREEL.

## Papers

### ML or ensemble correction of a global DEM against ICESat-2

- **Ouyang et al. (2025)**, FREEL, Remote Sensing 17(8):1337, https://www.mdpi.com/2072-4292/17/8/1337. Corrects SRTM over Hunan
  with RTK and ICESat-2 ATL08 points as reference; an adaptive-weighting variant of Deep Forest on derived terrain and
  vegetation features.
- **Zhou et al. (2023)**, "SRTM DEM Correction Using Ensemble Machine Learning Algorithm", Remote Sensing 15(16):3946,
  https://mdpi.com/2072-4292/15/16/3946. Same institution (Central South University of Forestry and Technology); stacking
  ensemble; about 46 % accuracy gain over SRTM reported.
- **Wei et al. (2025)**, "ASTER GDEM Correction Based on Stacked Ensemble Learning and ICESat-2/ATL08", Remote Sensing 17:1839,
  https://mdpi-res.com/d_attachment/remotesensing/remotesensing-17-01839/article_deploy/remotesensing-17-01839.pdf. Qilian
  Mountains; base learners LightGBM, XGBoost, AdaBoost, BPNN, CatBoost; useful literature review in the introduction.
- **Ling, Chan & Yan (2026)**, "A Dual-Task Optimization Approach for DEM Correction with Spaceborne LiDAR Data", ISPRS Archives
  XLIX-B3, https://isprs-archives.copernicus.org/articles/XLIX-B3-2026/177/2026/. One feature backbone, a regression branch
  (correction value) and a classification branch (up or down); beat Random Forest, XGBoost and a plain DNN on SRTM, RMSE
  about 27.6 % lower.
- **Li et al. (2024)**, "LightGBM hybrid model based DEM correction for forested areas", PLOS ONE 19(10),
  https://econpapers.repec.org/RePEc:plo:pone00:0309025. ICESat-2 as truth; Copernicus DEM, canopy height, forest cover, slope,
  roughness and relief as predictors; CNN-LightGBM against LightGBM, CNN-SVR and SVR. Targets forested land.
- **Narin et al. (2024)**, "Improving global DEMs using space-borne GEDI and ICESat-2 LiDAR altimetry data", Int. J. Digital
  Earth 17(1), doi:10.1080/17538947.2024.2316113. ANN, XGBoost and CNN in five test areas; airborne LiDAR and GNSS as control.
- **"Correcting SAR-derived DEMs with ICESat-2 using deep learning"**, SPIE Proc. 13049 (2024), doi:10.1117/12.3013897. A CNN
  corrects Copernicus DEM pixel by pixel from sparse ICESat-2 points with Sentinel-1 and Sentinel-2 inputs; ground RMSE 8.65 m
  to 2.62 m reported.

### Released ML-corrected DEMs and a non-ML baseline

- **Hawker et al. (2022)**, FABDEM, Environ. Res. Lett. 17:024016, https://iopscience.iop.org/article/10.1088/1748-9326/ac4d4f.
  Random forest predicting Copernicus DEM minus LiDAR DTM in forest; mean absolute error in forest 5.15 m to 2.88 m.
- **ANADEM (2024)**, Remote Sensing 16(13):2321, https://mdpi.com/2072-4292/16/13/2321. Vegetation bias removed from GLO-30 for
  South America with ML trained on GEDI.
- **Pronk et al. (2024)**, DeltaDTM, Scientific Data 11:273, https://www.nature.com/articles/s41597-024-03091-9.pdf. Not ML:
  co-registration, filtering of non-terrain cells and interpolation with ICESat-2 and GEDI. The baseline any ML model here
  has to beat (it is the chain's interim terrain).
- **Meadows, Reinke & Jones (2025/26)**, "Explaining ML models trained to predict Copernicus DEM errors in different land
  cover environments", https://bnhcrc.com.au/resources/publications/journal-article/explaining-machine-learning-models-trained-predict.
  One model per land cover, explained with SHAP; important variables differ a lot between land covers, so they argue for
  an ensemble of land-cover models over one general model.

### Tropical peatland (Indonesia)

- **Vernimmen et al. (2019)**, Remote Sensing 11(10):1152, doi:10.3390/rs11101152,
  https://research.vu.nl/en/publications/creating-a-lowland-and-peatland-landscape-digital-terrain-model-d/. DTM for Central
  Kalimantan and East Sumatra from LiDAR strips covering 10-35 % of the land plus manual interpolation; within 0.5 m of
  full-coverage LiDAR for 87.7-96.4 % of the land.
- **Vernimmen, Hooijer & Pronk (2020)**, GLL_DTM_v1,
  https://repository.tudelft.nl/record/uuid:16fa640c-32c6-48ed-8d5c-dc9ebbe27fb8. About 5 km global lowland DTM from ICESat-2;
  RMSE 0.54 m against 1.54-2.49 m for SRTM90, MERIT, CoastalDEM and TanDEM-X.
- **Berninger & Siegert (2020)**, "The Potential of ICESat-2 to Identify Carbon-Rich Peatlands in Indonesia", Remote Sensing
  12:4175, https://mdpi.com/2072-4292/12/24/4175. ICESat-2 RMSE 0.83 m against an airborne DTM; peat-dome surfaces by ordinary
  kriging of ICESat-2 footprints.
- **Meadows, Jones & Reinke (2024)**, Int. J. Digital Earth, doi:10.1080/17538947.2024.2308734,
  https://www.tandfonline.com/doi/full/10.1080/17538947.2024.2308734. Five 30 m DEMs against 65 airborne LiDAR surveys; FABDEM
  ranked first throughout. Useful for choosing the starting DEM.

### Algorithm foundations (from the assistant's own knowledge in that search, not verified)

- Zhou, Z.-H. & Feng, J. (2017), "Deep Forest: Towards an Alternative to Deep Neural Networks", IJCAI 2017; extended in
  National Science Review 6(1):74-86 (2019). Base of FREEL.
- Wolpert, D.H. (1992), "Stacked generalization", Neural Networks 5(2):241-259. Used by Zhou 2023 and Wei 2025.

## Possible avenues for repeat-dem

1. **Residual model on the LiDAR blocks.** Target: LiDAR DTM minus processed DeltaDTM (and minus DEMNAS), aggregated to the scale
   the chain needs (1-2 km relief and canal levels, not single cells). Predictors: the open DEMs, ICESat-2 ATL08 ground points,
   canopy height and forest type (ForTy, TMF), land cover, distance to canals, burn history (fires lower the surface), licence
   class (subsidence inside concessions, about 4-5 cm/yr from ICESat-2 at Sugihan and Pulau Padang). Gradient boosting first
   (LightGBM or XGBoost), stacking only if it helps on held-out sites.
2. **One model per land cover** (forest, shrub, burnt or open, plantation), as Meadows et al. suggest, against one general model.
3. **Start-DEM comparison.** Add FABDEM (and GEDTM30) to the benchmark next to DeltaDTM, DEMNAS and GLO-30 before training on any
   of them.
4. **Dome-scale target.** Train on the large-scale surface (smoothed residuals, or dome-fit parameters per unit) instead of
   per-cell error; the cell-level noise of DeltaDTM (0.4-0.7 m) is larger than the dome gradients (0.4-0.5 m/km).

## Cautions written now, before any result

- The papers report residual errors of 2-3 m; on peat domes the relief is a few metres, so their gains say little about
  whether 0.30 m at 1 km is reachable.
- Validation leave-one-KHG-out (or by spatial blocks far larger than the LiDAR blocks), never random cells: neighbouring cells
  share errors, and random splits overstate skill. Report the 1 km and 2 km error and the delineation IoU of the benchmark,
  not only cell RMSE.
- The LiDAR covers 41 KHG at 90 % or more, nearly all in Sumatra and Kalimantan; Papua has none, so a model trained there is
  extrapolating. Report where predictions fall outside the training range.
- LiDAR dates differ (2016-2020 at the dated sites) and peat subsides; the dating test failed (`benchmark/dated_lidar.yaml`),
  so do not shift the LiDAR, and do not use the ICESat-2 points both as a predictor and to date the reference.
- KLHK LiDAR and results derived from it need clearance from KLH and the World Bank before publication.
