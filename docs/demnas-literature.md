# DEMNAS: what the literature says, and what it means for this tool

Date: 2026-10-12. Three papers were read in full (the PDFs of the first and third are in this folder). Other sources were seen only as search excerpts and are marked with a dagger (†); check them before citing.

## How DEMNAS is built

| Fact | Source |
|---|---|
| Inputs are radar DSMs: IFSAR (5 m), TerraSAR-X (5 m), ALOS PALSAR (11.25 m); Radarsat is also named in BIG's coverage map. Stereo-plotted mass points are assimilated into them with GMT `surface`, tension 0.32. | Julzarika & Harintaka 2019; Susetyo 2023; Susetyo et al. 2018 |
| Output grid is 0.27 arc-second (about 8 m), vertical datum EGM2008. | same |
| Which sensor covers which area is mapped in BIG's "Indeks cakupan DSM Indonesia" (status 2017). Susetyo et al. 2018 Fig. 1 and Susetyo 2023 Fig. 2 reproduce it. | Susetyo et al. 2018; Susetyo 2023 |
| In the 2018 prototype (Aceh–North Sumatra), the DSM is corrected toward mass points: where the mass point and DSM differ by less than a threshold, the mass point replaces or is blended into the DSM, with weights of 0.4–0.75 by height difference. Mass points are 20–50 m apart, denser on craggy terrain and sparser on flat ground. | Susetyo et al. 2018 |

Two readings follow from this, both inferences and neither tested here:
- DEMNAS is a radar DSM that has been pulled part of the way toward the ground where stereo mass points exist. How far depends on mass-point density, which is lowest on flat, forested terrain such as peat domes.
- The mix of sensors, and the mass-point density, change from sheet to sheet. The 2018 paper describes the prototype, and the final product may have been processed differently.

## Published accuracy

| Study | Area | Reference | Result |
|---|---|---|---|
| Susetyo et al. 2018 (BIG) | Aceh–N. Sumatra, prototype | 142 GCPs | RMSE 2.237 m, LE90 3.679 m |
| BIG portal, quoted by Julzarika & Harintaka 2019 and Susetyo 2023 | Sumatra | GCPs | RMSE 2.79 m, bias −0.13 m (DEMNAS); DTM 3.24 m, DSM 3.71 m |
| Susetyo 2023 (BRIN) | Bogor, 30–2000 m relief | 60 GPS pre-marks | RMSE 4.968 m, **LE90 8.172 m** |
| Sulistiana et al. 2019 † | Medan | not seen | 1.818 m (as quoted by Susetyo 2023) |
| UGM thesis † | not seen | not seen | 6.124 m (DEMNAS), 8.175 m (TerraSAR-X), 8.735 m (SRTM) |
| Julzarika & Harintaka 2019 | S. Kalimantan (LiDAR), C. Java (IFSAR) | profile comparison, about 20 points | no RMSE; "dominated by DSM" in Kalimantan, "neither DSM nor DTM" in Java |

**The 8.17 m figure is LE90, not RMSE.** LE90 = 1.645 × RMSE, so Susetyo 2023 gives an RMSE of 4.97 m. The 8.17 m quoted in `test-run-sebangau.md` before this review is that LE90 value. Use 4.97 m (RMSE) or 8.17 m (LE90) and say which.

Points to keep in mind when comparing with our results:
1. **Every reference is on open, accessible ground.** GCPs and aerial-photo pre-marks sit in cleared spots. They say little about forest, which is where our ICESat-2 and GEDI points sit. Published figures are therefore a best case for peat forest.
2. **Our smoothed RMSE (1.2 to 2.8 m) is in the same range as the published 2.2 to 2.8 m.** The pipeline reaches roughly the stated accuracy of the product. It does not beat it. Published values show no sub-metre accuracy for DEMNAS anywhere.
3. **The 0.25 m RMSE target in the re-peat methodology is not attainable from DEMNAS.** It needs LiDAR or a dense GNSS-controlled survey. See "Consequences" below.
4. **Susetyo 2023 found DEMNAS errors uniform across elevation**, unlike SRTM and ASTER, whose errors grow with height. That fits a product whose error comes from the source mosaic and mass-point density rather than from terrain.
5. Julzarika & Harintaka's DSM-versus-DTM call rests on eyeballed profiles over a small sample, and their LiDAR DSM reaches a 73 m canopy over oil palm, which the authors themselves call not rational. Read it as "DEMNAS is not uniform", not as a measured DSM fraction.

## Why this matches what we saw

| Our finding (`test-run-sebangau.md`) | Consistent with |
|---|---|
| Fitted tree-cover k of 0.04–0.21 at all three sites, against a prior of 0.8 | DEMNAS has been partly pulled to ground by mass points, so little canopy remains to subtract |
| Offset differs by site (−3.4, about 0, +2.2 m) and by class | Different source sensors and mass-point density per sheet |
| Open land 4 m below the lidar ground at Sebangau | Not explained by any of the papers. A DSM should not sit below ground. Candidates: mass-point (stereo) height error, interpolation across sparse mass points, or a shared datum offset. Open. |
| Errors that do not follow height | Susetyo 2023, point 4 above |

## Consequences for the tool and the methodology

- **Reword "DEMNAS is a surface model in forest".** The accurate statement is: DEMNAS is a radar DSM blended with stereo mass points, so the canopy content is unknown and varies by area.
- **Treat k from the literature as no prior at all.** The default `k_by_class` of 0.8 is a placeholder that no tested site supports. At the three sites, using it made Mendahara and Bengkalis worse than the raw DEM. Run with `--ground none` only if you accept that it still applies the prior.
- **Calibrate per source region, not only per land-cover class.** First test whether DEM − ground has steps at sheet or sensor boundaries along the ICESat-2 tracks. If it does, fit the offset and k per source area, using BIG's coverage index to define the areas.
- **Absolute accuracy is a floor of about 2 to 3 m.** Report relative (detrended) error and slope error as well, since the hydrology depends on height differences over a few hundred metres to kilometres, not on absolute height.
- **Heights that need centimetre to decimetre accuracy** (canal water levels, block crests, logger heads) should come from GNSS or levelling, not from this DEM.

## Other work by the same authors

- Susetyo, D.B., Lumban-Gaol, Y.A. and Sofian, I. (2018). Prototype of national digital elevation model in Indonesia. *ISPRS Archives* XLII-4, 609–613. doi 10.5194/isprs-archives-XLII-4-609-2018. Read in full (open access). It is the only paper found that describes how the DSM and mass points were merged.
- Susetyo, D.B. (2023). Vertical accuracy assessment of various open-source DEM data: DEMNAS, SRTM-1, and ASTER GDEM. *Geodesy and Cartography* 49(4), 209–215. doi 10.3846/gac.2023.18168. Read in full. The affiliation printed on the paper is BRIN, while the data and funding are BIG's.
- No Susetyo paper on peat or forest terrain was found in two searches. Worth asking him directly for the per-sheet source metadata and mass-point density.

## Not yet obtained

- BIG's per-sheet source metadata or the DSM coverage index in digital form.
- DEMNAS validation over forest or peat (none seen).
- The UGM thesis and Sulistiana et al. 2019 † (full text).
- Julzarika's other height-model integration papers † (accuracies of 1.1 to 2.0 m were reported in a summary only).
