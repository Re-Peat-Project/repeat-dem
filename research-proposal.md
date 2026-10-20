# Physics-Informed Open DTM for Peatland Water Balance (Neraca Air) — Initial Research Proposal Draft

Oct 19, 2026 · @Dany Laksono

## Background and rationale

The RE-PEAT neraca air (water balance) module currently depends on airborne LiDAR DTM, which does not cover every KHG and is costly to repeat. This proposal tests whether open DEMs, corrected with peat-specific physics and InSAR subsidence, can support LiDAR or partly replace it.

Peat terrain is a hard case for open DEMs. Domes rise only a few metres over several kilometres, so the decimetre-level accuracy that the water balance needs is below the error of global products. Most open products are radar or optical surface models that see the forest canopy, not the peat surface.

Peat terrain also has an advantage that generic DEM correction ignores: its shape is governed by groundwater physics. Rain-fed domes tend toward a stable, uniformly curved form set by rainfall and hydraulic conductivity (Ingram, 1982; Cobb et al., 2017). The surface also moves over time through subsidence and seasonal oscillation, which InSAR can measure. Using these two facts as constraints is the core idea of this proposal.

The water balance uses the DTM in three places, and all three are sensitive at decimetre scale:

- Peat storage volume, computed as DTM minus peat depth.
- Flow direction and sub-KHG boundaries (D8 and Strahler ordering).
- The land–canal head difference (dA) that drives drainage and rewetting estimates.

## Prior work in our projects

Our earlier projects already mixed LiDAR with an open-access DEM, but never measured what that mix costs in accuracy.

| Project | Terrain data | How it was used | Gap |
| --- | --- | --- | --- |
| KHG Kahayan–Sebangau final report (BRGM) | LiDAR DTM (primary) + WorldDEM DTM | WorldDEM filled areas without LiDAR coverage; D8 flow direction, flow accumulation, Strahler ordering (7 orders); outlets at 7th-order rivers and canals gave 16 sub-KHGs | Boundaries from the two datasets differ; the difference was not quantified; only LiDAR flow directions were checked in the field |
| Pulau Padang (UNDP–BRG–UGM) | LiDAR DTM only | Fill sinks, flow direction, flow accumulation, sub-KHG delineation; peat volume (DTM minus peat depth); canal digitising; zoning map | No open-DEM comparison |

The Kahayan–Sebangau report already lists WorldDEM, DEMNAS and SRTM as alternatives to LiDAR, and notes that higher resolution shows the peat dome better. WorldDEM is a TanDEM-X radar product, so over forested peat it records a level closer to the canopy than to the ground. Gap-filling it into LiDAR without bias correction risks broken flow paths at the seam.

## Research questions and objectives

The central question is whether a physics-informed, epoch-aligned open DTM can reproduce LiDAR-based water-balance outputs closely enough for RE-PEAT planning.

**Research questions**

1. How far do the best open DEMs deviate from LiDAR over Indonesian peat, before and after correction?
2. Does separating ombrogenous and topogenous peat, and applying different physical constraints to each, reduce that error?
3. How much of the open-DEM error is explained by acquisition epoch, and can InSAR subsidence rates correct it?
4. How do the remaining DTM errors propagate into peat volume, sub-KHG boundaries, dA, simulated water-table depth and canal-block ranking?

**Objectives**

- Benchmark candidate open DEMs against LiDAR in Kahayan–Sebangau.
- Build a correction pipeline: datum harmonisation, ombrogenous/topogenous classification, canopy-bias correction with spaceborne lidar, physics regularisation and InSAR epoch alignment.
- Evaluate the corrected DTM by its water-balance outputs, not only by elevation error.
- Define where open data can replace LiDAR and where LiDAR is still required.

**Working hypotheses**

- H1: The dome-curvature constraint reduces error in ombrogenous dome interiors more than statistical correction alone.
- H2: Epoch alignment with InSAR removes a systematic, drainage-dependent bias near canals.
- H3: Errors that remain matter most within about 600 m of canals, where canal blocks act (Urzainki et al., 2023).

## Candidate open DEMs and spaceborne lidar

Five products go to the benchmark first: FathomDEM, FABDEM, GEDTM30, DeltaDTM and DEMNAS. The rest serve as baselines or supporting data.

| Product | Type | Resolution | Role in this study | Licence / access | Reference |
| --- | --- | --- | --- | --- | --- |
| FathomDEM | Bare-earth DTM (ML-corrected Copernicus) | 30 m | Benchmark candidate; best in a 2025 LiDAR comparison | Restrictive; check terms before KLH deliverables | Uhe et al., 2025 |
| FABDEM | Bare-earth DTM (forest and buildings removed) | 30 m | Benchmark candidate | Non-commercial (CC BY-NC-SA) | Hawker et al., 2022 |
| GEDTM30 | Ensemble DTM trained on ICESat-2/GEDI, with per-pixel uncertainty | 30 m | Benchmark candidate; uncertainty layer for error propagation | Open | Ho et al., 2025 |
| DeltaDTM | Coastal DTM, land below about 10 m | 30 m | Benchmark candidate for lowland and coastal peat | Open (CC BY) | Pronk et al., 2024 |
| DEMNAS (BIG) | National, DSM-like fusion | about 8 m | Benchmark candidate; highest open resolution | Free via BIG geoportal | BIG |
| MERIT DEM | Bare-earth (forest bias removed) | about 90 m | Coarse baseline | Open for research | Yamazaki et al., 2017 |
| Copernicus GLO-30 / GLO-90 | DSM (X-band) | 30 / 90 m | Base layer for most corrected DTMs | Open | ESA, 2021 |
| TanDEM-X 90 m / EDEM | DSM (X-band) | 90 m | Same source as WorldDEM; links to prior work | Free for science | Rizzoli et al., 2017 |
| ALOS AW3D30 | DSM (optical stereo) | 30 m | Baseline; cloud gaps likely | Open | Tadono et al., 2014 |
| SRTM v3 / NASADEM | DSM (C-band, year 2000) | 30 m | Old-epoch baseline for subsidence test | Open | Farr et al., 2007; Crippen et al., 2016 |
| ASTER GDEM v3 | DSM (optical stereo) | 30 m | Baseline only; noisy on flat ground | Open | Abrams et al., 2020 |
| ICESat-2 ATL08 | Spaceborne lidar ground points | Track points | Ground control for residual correction | Open | Neuenschwander & Pitts, 2019 |
| GEDI L2A | Spaceborne lidar ground and canopy | Footprints about 25 m | Ground control; canopy height | Open | Dubayah et al., 2020 |
| MERIT Hydro / HydroSHEDS | Hydro-conditioned derivatives | about 90 m | Cross-check of flow direction only | Open | Yamazaki et al., 2019; Lehner et al., 2008 |

ICESat-2 has already been used to model peat domes in Indonesia, including Sebangau, with RMSE about 0.83 m against airborne LiDAR (Berninger & Siegert, 2020).

## Parameters affecting peat DTM elevation

Twenty-five parameters act on peat DTM elevation, either directly (D) or through another parameter (I). Group E lists the observations that constrain and validate the model.

| Group | Parameter | D/I | Relationship to elevation | Data and source | Reference |
| --- | --- | --- | --- | --- | --- |
| A. Sensor | Canopy height | D | DSM sits above ground by part of the canopy height | GEDI L2A, ICESat-2 ATL08, canopy-height maps | Dubayah et al., 2020; Hawker et al., 2022 |
| A. Sensor | Radar wavelength | D | X/C-band scatters near canopy top; L-band penetrates deeper | Product metadata | Rizzoli et al., 2017 |
| A. Sensor | Acquisition epoch | D | Older DEMs sit higher on subsiding peat | DEM metadata, LiDAR survey date | Hoyt et al., 2020 |
| A. Sensor | Vertical datum / geoid | D | Constant or regional offset, possibly decimetres | EGM2008, InaGeoid (BIG), GNSS benchmarks | Pavlis et al., 2012 |
| A. Sensor | Resolution and interpolation | D | Smooths canal banks and dome edges | DEM specification, LiDAR point density | Vernimmen et al., 2019 |
| A. Sensor | Water surfaces and canals | D | Radar returns water level, not bank or bed | Canal network, JRC Global Surface Water | Pekel et al., 2016 |
| B. Peat body | Peat thickness | D | Surface = peat base + thickness | Field borings, national peat map (BBSDLP) | Vernimmen et al., 2020 |
| B. Peat body | Mineral substrate elevation | D | Lower boundary; roughly flat under ombrogenous domes | Borings, interpolation | Vernimmen et al., 2020 |
| B. Peat body | Peat type (ombrogenous / topogenous) | I | Selects the physics: dome curvature or river and flood control | Peat thickness, dome fit, flood frequency, vegetation | Ingram, 1982; Cobb et al., 2017 |
| B. Peat body | Bulk density and maturity | I | Sets compression, oxidation, K and Sy | Field samples, literature | Hooijer et al., 2012; Mahdiyasa et al., 2024 |
| B. Peat body | Peat stiffness | I | Controls surface deformation under load and water-table change | Lab tests, literature | Mahdiyasa et al., 2023 |
| C. Hydrology | Net rainfall (P − ET) and regime | I | More stable net rainfall allows a higher, more curved stable dome | CHIRPS, GPM IMERG, MODIS MOD16 | Cobb et al., 2017; Funk et al., 2015; Mu et al., 2011 |
| C. Hydrology | Hydraulic conductivity K | I | Higher K gives a flatter dome | Slug or pumping tests, literature | Ingram, 1982; Urzainki et al., 2023 |
| C. Hydrology | Specific yield Sy | I | Controls water-table response and surface oscillation | Field, literature | Urzainki et al., 2020 |
| C. Hydrology | Water-table depth | I | Deeper water table speeds subsidence | SIPALAGA (BRGM), loggers | Hooijer et al., 2012 |
| C. Hydrology | Distance to canal or river | I | Drainage and subsidence are strongest near canals | Canal and river network | Umarhadi et al., 2022 |
| C. Hydrology | Canal water level and blocks | I | Boundary condition for water table; blocks slow subsidence | Canal surveys, block inventory | Urzainki et al., 2020 |
| C. Hydrology | River stage, tides, sea level | I | Drainage base; lower limit of the surface in topogenous and coastal areas | Gauges, tide models, DeltaDTM | Hooijer et al., 2012; Pronk et al., 2024 |
| C. Hydrology | Inundation frequency | I | Marks topogenous peat and the drainability limit | Sentinel-1 flood maps, JRC GSW | Pekel et al., 2016 |
| D. Dynamics | Oxidation | D | Irreversible lowering; faster with deeper water table | InSAR, subsidence poles | Hooijer et al., 2012 |
| D. Dynamics | Consolidation | D | Fast lowering in the first years after drainage | InSAR time series, poles | Hooijer et al., 2012 |
| D. Dynamics | Shrinkage | D | Lowering in the dry season | InSAR seasonal signal | Wösten et al., 1997 |
| D. Dynamics | Seasonal oscillation | D | Reversible rise and fall with water table | InSAR (APSIS), loggers | Price & Schlotzhauer, 1999; Alshammari et al., 2018 |
| D. Dynamics | Fire and burn depth | D | Sudden lowering of decimetres | Burn-scar maps, multi-epoch LiDAR | Ballhorn et al., 2009 |
| D. Dynamics | Land cover and drainage age | I | Subsidence slows after about 9 years of drainage | Landsat time series, MapBiomas Indonesia, KLHK land cover | Umarhadi et al., 2022 |
| E. Observation | Airborne LiDAR DTM | — | Reference and holdout validation | BRGM, KHG reports | Vernimmen et al., 2019 |
| E. Observation | ICESat-2 / GEDI ground points | — | Residual correction by kriging or Random Forest | NASA Earthdata | Berninger & Siegert, 2020 |
| E. Observation | InSAR (ALOS-2, NISAR, Sentinel-1) | — | Subsidence trend and seasonal term for epoch alignment | JAXA, ASF DAAC, Copernicus | Hoyt et al., 2020; Berardino et al., 2002 |
| E. Observation | GNSS benchmarks, subsidence poles | — | Absolute reference for InSAR; datum check | Field survey, BIG | Hooijer et al., 2012 |
| E. Observation | SIPALAGA water-table data | — | Calibration of the Boussinesq model; independent validation | BRGM / KLH | Urzainki et al., 2023 |

## Proposed method

The pipeline corrects an open DEM in six steps, splitting into two branches by peat type, and judges the result by its water-balance outputs.

&#91;embedded content: correction pipeline · 6 steps, 2 peat-type branches\]

The pipeline splits only at step 4, where ombrogenous and topogenous peat get different physical constraints, then rejoins for epoch alignment and evaluation.

1. **Vertical datum harmonisation.** Convert every DEM and the LiDAR to one datum (InaGeoid or ellipsoidal heights), checked against GNSS benchmarks. Open DEMs mostly use EGM2008 (Pavlis et al., 2012).
2. **Peat-type classification.** Classify ombrogenous and topogenous peat with Random Forest (Breiman, 2001). Predictors: peat thickness, goodness of fit to a dome surface, inundation frequency (Pekel et al., 2016) and vegetation. Validate with field borings.
3. **Canopy-bias and residual correction.** Model the difference between the open DEM and ICESat-2/GEDI ground points, then interpolate it by ordinary kriging or Random Forest regression (Berninger & Siegert, 2020). Canopy height from GEDI enters as a predictor.
4. **Physics regularisation, by peat type.**
   - Ombrogenous: fit a smooth surface per sub-KHG that balances misfit to the corrected data against deviation from constant curvature. Dome edges are fixed to canal and river water levels (Ingram, 1982; Cobb et al., 2017).
   - Topogenous: constrain the surface by river stage, tides and inundation frequency instead of a dome shape.
   - Near canals, where drained peat is out of equilibrium, the data term dominates and the curvature penalty is relaxed.
5. **Epoch alignment with InSAR.** Derive subsidence trend and seasonal terms by SBAS InSAR (Berardino et al., 2002) from L-band ALOS-2 (historical) and NISAR (from June 2026). Fill decorrelated areas with Random Forest on land-cover history, distance to peat edge and elevation (Umarhadi et al., 2022).
6. **Fitness-for-purpose evaluation.** Run the existing D8/Strahler chain (O'Callaghan & Mark, 1984; Jenson & Domingue, 1988; Strahler, 1957) and a Boussinesq water-table model (Urzainki et al., 2020, 2023) on both LiDAR and the corrected DTM, then compare the outputs.

The regularised surface in step 4 minimises:

```latex
J(z) = \sum_i w_i \left(z(x_i) - z_i^{obs}\right)^2 + \lambda \iint_{\Omega} \left(\nabla^2 z - \kappa\right)^2 \, dA
```

Here z is the surface, z\_i^obs the corrected observations with weights w\_i, κ the target curvature for the rainfall regime, and λ the strength of the physics constraint. λ is set high in dome interiors and low near canals.

The epoch correction in step 5 is applied per pixel:

```latex
z(t) = z(t_0) + v\,(t - t_0) + A \sin\!\left(\frac{2\pi t}{T} + \varphi\right)
```

Here t0 is the DEM acquisition date, v the InSAR subsidence rate, and A, T and φ the amplitude, period and phase of seasonal oscillation.

MPeat and MPeat2D (Mahdiyasa et al., 2023, 2024) are not run directly. They supply physical priors on dome shape and on how compression links water-table drop to surface lowering, which helps interpret the InSAR seasonal term.

## Validation and evaluation design

The corrected DTM passes only if its water-balance outputs match LiDAR within tolerances the team sets, not just if its elevation RMSE is low.

Three independent checks prevent circular validation. LiDAR tiles are held out spatially and never used in correction. SIPALAGA water-table records are compared with modelled water table. GNSS benchmarks and subsidence poles check absolute height and InSAR rates.

| Metric | Compared against | Why it matters |
| --- | --- | --- |
| Elevation RMSE, bias, NMAD by peat type and distance to canal | LiDAR holdout | Basic accuracy; shows where errors concentrate |
| Sub-KHG boundary agreement (area overlap) | LiDAR-derived sub-KHGs | Units used for planning and the water balance |
| Peat volume difference (%) | LiDAR minus peat depth | Carbon and storage estimates |
| dA (land–canal head) error | LiDAR plus canal water levels | Drives drainage and rewetting estimates |
| Simulated water-table depth difference | Boussinesq run on LiDAR; SIPALAGA | Main restoration outcome |
| Canal-block ranking agreement | Optimisation run on LiDAR | Whether block decisions would change |
| InSAR rate error | GNSS, subsidence poles | Validity of epoch alignment |

Results are reported separately for dome interiors and for the zone within about 600 m of canals. That zone is where canal blocks act and where open-DEM error is expected to matter most (Urzainki et al., 2023).

## Risks and limitations

The biggest risk is that open data cannot reach decimetre accuracy near canals, so the realistic outcome may be support for LiDAR rather than full replacement.

| Risk | Effect | Mitigation |
| --- | --- | --- |
| Drained peat is out of equilibrium | Dome-curvature constraint is wrong near canals | Relax λ near canals; let data dominate |
| Circular validation | Groundwater-shaped DTM looks good under a groundwater model | Spatial LiDAR holdouts, SIPALAGA and GNSS as independent checks |
| C-band decorrelation over forest | InSAR gaps exactly in forest | Use L-band (ALOS-2, NISAR); Random Forest gap-filling |
| Mixed vertical datums | Offsets larger than the signal | Harmonise datum first, verify on GNSS benchmarks |
| Restrictive DEM licences | FathomDEM and FABDEM may not be usable in KLH deliverables | Confirm terms early; keep GEDTM30 and DeltaDTM as open fallbacks |
| ML-based DTMs are black boxes | Bare-earth products can introduce artefacts | Benchmark against LiDAR; inspect residual maps |
| Sparse ICESat-2/GEDI over the site | Weak residual model | Combine both missions; report uncertainty with GEDTM30 layer |
| Sudden events (fire) | Linear InSAR trend misses abrupt lowering | Burn-scar masks; segment time series at fire dates |
| MPeat scope | Millennial, idealised model, not site-calibrated | Use only as physical prior, not as a predictor |

## Discussion so far and next steps

We have moved from reviewing how WorldDEM was used to a physics-informed, epoch-aligned open-DTM proposal. Next comes data assembly and a first benchmark in Kahayan–Sebangau.

**Context and decisions so far**

| Topic | Point reached |
| --- | --- |
| RE-PEAT workflow | LiDAR DTM is the main elevation input; neraca air is a separate module that prioritises sub-KHG needs; rewetting steps may be automated as Python or a QGIS Processing plugin |
| Prior use of WorldDEM | Used only to fill LiDAR gaps in Kahayan–Sebangau; accuracy difference never quantified |
| Open DEM inventory | Fourteen open products and spaceborne lidar sources listed; five shortlisted for benchmarking |
| Peat-specific approach | Use dome physics (Ingram, Cobb) as a constraint; Urzainki-type Boussinesq model as fitness-for-purpose test; MPeat as physical prior only |
| Ombrogenous / topogenous split | Adopted: different constraints per peat type |
| InSAR temporal correction | Adopted: L-band SBAS for trend plus seasonal term; NISAR now public |
| Parameter inventory | Twenty-five parameters mapped with data sources and references |

**Next steps**

- [ ] Confirm study area and LiDAR tiles to hold out in Kahayan–Sebangau
- [ ] Check licence terms for FathomDEM and FABDEM for use in KLH deliverables
- [ ] Download the five shortlisted DEMs plus Copernicus GLO-30 and clip to the KHG
- [ ] Harmonise vertical datums and verify on GNSS benchmarks
- [ ] Run a first raw benchmark (elevation error by peat type and distance to canal)
- [ ] Collect ICESat-2 ATL08 and GEDI L2A ground points over the site
- [ ] Request SIPALAGA water-table records, canal water levels and canal-block inventory from BRGM/KLH
- [ ] Assemble peat thickness borings and the national peat map for the peat-type classification
- [ ] Search ASF for ALOS-2 and NISAR coverage over the KHG; test an SBAS run
- [ ] Review Urzainki et al. model code and decide whether to reuse or reimplement the Boussinesq solver
- [ ] Draft the evaluation tolerances with the team (acceptable dA, volume and boundary error)
- [ ] Design the pipeline modules so they fit the planned QGIS Processing plugin

## Open questions for the team

- What vertical datum and survey year does the Kahayan–Sebangau LiDAR use?
- What error in dA, peat volume and sub-KHG boundary is acceptable for neraca air planning?
- Is the goal to replace LiDAR in uncovered KHGs, or to update LiDAR between surveys, or both?
- Can KLH deliverables use non-commercial-licence DEMs, or only fully open ones?
- Which peat thickness and hydraulic-property data can BRGM/KLH share?
- Should a second test site be added (for example Pulau Padang) to check transferability between Sumatra and Kalimantan?

## References

Entries with links were checked during drafting; volume and page details of the others are from memory and should be verified before submission.

**Project documents**

- Laporan Akhir KHG Sungai Kahayan–Sungai Sebangau (BRGM).
- Kajian Komprehensif Topografi, Hidrologi dan Water Management — Penyusunan Peta Arahan Tindakan RGP Pulau Padang (UNDP–BRG–UGM).

**Literature and data**

- Abrams, M., Crippen, R. & Fujisada, H. (2020). ASTER Global Digital Elevation Model (GDEM) and ASTER Global Water Body Dataset (ASTWBD). *Remote Sensing* 12(7), 1156.
- Alshammari, L., Large, D.J., Boyd, D.S., et al. (2018). Long-term peatland condition assessment via surface motion monitoring using the ISBAS DInSAR technique over the Flow Country, Scotland. *Remote Sensing* 10(7), 1103.
- ASF DAAC (2026). [NISAR L-band data now publicly available](https://asf.alaska.edu/notices/nisar-l-band-data-now-publicly-available/).
- Ballhorn, U., Siegert, F., Mason, M. & Limin, S. (2009). Derivation of burn scar depths and estimation of carbon emissions with LIDAR in Indonesian peatlands. *PNAS* 106(50), 21213–21218.
- Berardino, P., Fornaro, G., Lanari, R. & Sansosti, E. (2002). A new algorithm for surface deformation monitoring based on small baseline differential SAR interferograms. *IEEE Trans. Geosci. Remote Sens.* 40(11), 2375–2383.
- Berninger, A. & Siegert, F. (2020). [The potential of ICESat-2 to identify carbon-rich peatlands in Indonesia](https://mdpi-res.com/d_attachment/remotesensing/remotesensing-12-04175/article_deploy/remotesensing-12-04175.pdf). *Remote Sensing* 12(24), 4175.
- Breiman, L. (2001). Random forests. *Machine Learning* 45, 5–32.
- Cobb, A.R., Hoyt, A.M., Gandois, L., et al. (2017). [How temporal patterns in rainfall determine the geomorphology and carbon fluxes of tropical peatlands](https://pmc.ncbi.nlm.nih.gov/articles/PMC5495247). *PNAS* 114(26), E5187–E5196.
- Crippen, R., Buckley, S., Agram, P., et al. (2016). NASADEM global elevation model: methods and progress. *ISPRS Archives* XLI-B4, 125–128.
- Dubayah, R., Blair, J.B., Goetz, S., et al. (2020). The Global Ecosystem Dynamics Investigation: high-resolution laser ranging of the Earth's forests and topography. *Science of Remote Sensing* 1, 100002.
- ESA (2021). Copernicus DEM. doi:10.5270/ESA-c5d3d65.
- Farr, T.G., Rosen, P.A., Caro, E., et al. (2007). The Shuttle Radar Topography Mission. *Reviews of Geophysics* 45, RG2004.
- Funk, C., Peterson, P., Landsfeld, M., et al. (2015). The climate hazards infrared precipitation with stations — a new environmental record for monitoring extremes. *Scientific Data* 2, 150066.
- Hawker, L., Uhe, P., Paulo, L., et al. (2022). [A 30 m global map of elevation with forests and buildings removed](https://www.fathom.global/academic-papers/a-30-m-global-map-of-elevation-with-forests-and-buildings-removed/). *Environmental Research Letters* 17, 024016.
- Ho, Y.-F., Grohmann, C.H., Parente, L., Witjes, M. & Hengl, T. (2025). [GEDTM30: global ensemble digital terrain model at 30 m and derived multiscale terrain variables](https://peerj.com/articles/19673). *PeerJ* 13, e19673.
- Hooijer, A., Page, S., Jauhiainen, J., et al. (2012). Subsidence and carbon loss in drained tropical peatlands. *Biogeosciences* 9, 1053–1071.
- Hoyt, A.M., Chaussard, E., Seppalainen, S.S. & Harvey, C.F. (2020). [Widespread subsidence and carbon emissions across Southeast Asian peatlands](https://par.nsf.gov/servlets/purl/10174385). *Nature Geoscience* 13, 435–440.
- Ingram, H.A.P. (1982). Size and shape in raised mire ecosystems: a geophysical model. *Nature* 297, 300–303.
- Jenson, S.K. & Domingue, J.O. (1988). Extracting topographic structure from digital elevation data for geographic information system analysis. *Photogramm. Eng. Remote Sens.* 54(11), 1593–1600.
- Lehner, B., Verdin, K. & Jarvis, A. (2008). New global hydrography derived from spaceborne elevation data. *Eos* 89(10), 93–94.
- Mahdiyasa, A.W., Large, D.J., Muljadi, B.P., Icardi, M. & Triantafyllou, S. (2022). [MPeat — a fully coupled mechanical-ecohydrological model of peatland development](https://nottingham-repository.worktribe.com/output/6477833).
- Mahdiyasa, A.W., Large, D.J., Muljadi, B.P. & Icardi, M. (2023). [Modelling the influence of mechanical-ecohydrological feedback on the nonlinear dynamics of peatlands](https://nottingham-repository.worktribe.com/output/16797957/modelling-the-influence-of-mechanical-ecohydrological-feedback-on-the-nonlinear-dynamics-of-peatlands). *Ecological Modelling*, doi:10.1016/j.ecolmodel.2023.110299.
- Mahdiyasa, A.W., Large, D.J., Icardi, M. & Muljadi, B.P. (2024). [MPeat2D — a fully coupled mechanical–ecohydrological model of peatland development in two dimensions](https://esurf.copernicus.org/articles/12/929/2024/). *Earth Surface Dynamics* 12, 929.
- Mu, Q., Zhao, M. & Running, S.W. (2011). Improvements to a MODIS global terrestrial evapotranspiration algorithm. *Remote Sensing of Environment* 115, 1781–1800.
- Neuenschwander, A. & Pitts, K. (2019). The ATL08 land and vegetation product for the ICESat-2 mission. *Remote Sensing of Environment* 221, 247–259.
- O'Callaghan, J.F. & Mark, D.M. (1984). The extraction of drainage networks from digital elevation data. *Computer Vision, Graphics, and Image Processing* 28(3), 323–344.
- Pavlis, N.K., Holmes, S.A., Kenyon, S.C. & Factor, J.K. (2012). The development and evaluation of the Earth Gravitational Model 2008 (EGM2008). *J. Geophys. Res.* 117, B04406.
- Pekel, J.-F., Cottam, A., Gorelick, N. & Belward, A.S. (2016). High-resolution mapping of global surface water and its long-term changes. *Nature* 540, 418–422.
- Price, J.S. & Schlotzhauer, S.M. (1999). Importance of shrinkage and compression in determining water storage changes in peat: the case of a mined peatland. *Hydrological Processes* 13, 2591–2601.
- Pronk, M., Hooijer, A., Eilander, D., et al. (2024). DeltaDTM: a global coastal digital terrain model. *Scientific Data* 11, 273.
- Rizzoli, P., Martone, M., Gonzalez, C., et al. (2017). Generation and performance assessment of the global TanDEM-X digital elevation model. *ISPRS J. Photogramm. Remote Sens.* 132, 119–139.
- Strahler, A.N. (1957). Quantitative analysis of watershed geomorphology. *Trans. AGU* 38(6), 913–920.
- Tadono, T., Ishida, H., Oda, F., et al. (2014). Precise global DEM generation by ALOS PRISM. *ISPRS Annals* II-4, 71–76.
- Uhe, P., et al. (2025). [FathomDEM: an improved global terrain map using a hybrid vision transformer model](https://www.fathom.global/academic-papers/fathomdem-research-paper/). *Environmental Research Letters*.
- Umarhadi, D.A., Widyatmanti, W., Kumar, P., et al. (2022). [Tropical peat subsidence rates are related to decadal LULC changes: insights from InSAR analysis](https://pure.iiasa.ac.at/17643). *Science of the Total Environment*.
- Urzainki, I., Laurén, A., Palviainen, M., et al. (2020). [Canal blocking optimization in restoration of drained peatlands](https://bg.copernicus.org/articles/17/4769/2020/). *Biogeosciences* 17, 4769–4784.
- Urzainki, I., et al. (2023). [A process-based model for quantifying the effects of canal blocking on water table and CO2 emissions in tropical peatlands](https://jukuri.luke.fi/handle/11111/6151). *Biogeosciences* 20, 2099–2116.
- Vernimmen, R., Hooijer, A., Yuherdha, A.T., et al. (2019). Creating a lowland and peatland landscape digital terrain model (DTM) from interpolated partial coverage LiDAR data for Central Kalimantan and East Sumatra. *Remote Sensing* 11(10), 1152.
- Vernimmen, R., Hooijer, A., Akmalia, R., et al. (2020). [Mapping deep peat carbon stock from a LiDAR based DTM and field measurements, with application to eastern Sumatra](https://cbmjournal.biomedcentral.com/counter/pdf/10.1186/s13021-020-00139-2.pdf). *Carbon Balance and Management* 15, 4.
- Wösten, J.H.M., Ismail, A.B. & van Wijk, A.L.M. (1997). Peat subsidence and its practical implications: a case study in Malaysia. *Geoderma* 78, 25–36.
- Yamazaki, D., Ikeshima, D., Tawatari, R., et al. (2017). A high-accuracy map of global terrain elevations. *Geophys. Res. Lett.* 44, 5844–5853.
- Yamazaki, D., Ikeshima, D., Sosa, J., et al. (2019). MERIT Hydro: a high-resolution global hydrography map based on latest topography dataset. *Water Resources Research* 55, 5053–5073.
