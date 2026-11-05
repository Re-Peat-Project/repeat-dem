# Drone photogrammetry survey of a KHG: notes (planned, not flown)

Status 2026-11-05: the project plans a drone flight over one selected KHG to produce a detailed DSM. Photogrammetry only (camera); drone LiDAR was ruled out on cost. Ground extraction is to be improved later (e.g. cloth simulation filter). These notes record the discussion so the survey can be designed against the DEM requirements.

## What the survey can answer

- **Canal-bank land profiles for repeat-pump stage 5.** Block placement samples the land 6 and 10 m either side of a canal and needs about 0.2 m accuracy over roughly 1 km (repeat-pump's warning rule: `dA < 2 x vertical RMSE`, with `dA` = 0.40 m). A 30 m DTM puts both offsets in the canal's own cell; a 10-20 cm drone surface resolves banks.
- **A dated reference** with a known flight date and datum, to test DeltaDTM and the KLHK modelled DTM, and the age of the KLHK LiDAR on drained land.
- **A subsidence baseline:** a repeat flight of the same corridor gives subsidence independent of ICESat-2.
- **Canal water levels:** flown in the dry season, the water surface in canals gives canal depth below the land, which the neraca model now assumes (0.80 / 0.32 / 0.24 m, D24).

## Limits of photogrammetry on peat

- Cameras see the top of the vegetation. Ground points exist only where the ground is visible.
- Cloth simulation (CSF) on the photogrammetric point cloud:
  - works on bare, burnt and freshly cleared land, canal banks, roads, and young or open oil palm;
  - partly works where ground points are sparse (older oil palm, scattered shrubs): the cloth spans and interpolates gaps;
  - fails under closed forest and acacia (no ground points: the cloth settles on the canopy) and on dense fern or scrub mats on degraded peat (1-2 m high, read as ground, biased high by about the size of a dome's relief over 1 km, and invisible in the data).
- On flat, uniform terrain, photogrammetric surfaces can bend slightly into a dome or bowl. This is the same kind of long-range error that limits DeltaDTM.

## Design points

1. **Fly to see ground:** high overlap, low altitude, oblique images in addition to nadir, RTK/PPK on the drone, dry season, after clearing or burning where there is a choice.
2. **GNSS control along the whole corridor**, not only at the ends, tied to a stated vertical datum; cross-check against ICESat-2 tracks and any KLHK LiDAR overlap.
3. **Measure vegetation bias:** RTK GNSS ground checkpoints in each cover class, pushed through ferns to the peat surface, with vegetation height recorded. This gives a measured offset per class and its error. Hold some checkpoints out for testing only.
4. **Compare ground filters on the point cloud, not on a raster:** CSF against SMRF and PMF (PDAL, CloudCompare). On flat terrain CSF needs high rigidness; record cloth resolution and the classification threshold. Earlier, a morphological filter took DEMNAS from 1.66 to 1.24 m 1 km error (`runs/checks/demnas_ground_filter.md`), so the filter choice matters.
5. **Mask where it cannot work:** where ground-point density is too low, mark the drone DTM invalid and fall back to DeltaDTM (or a class offset), flagged.
6. **Coverage:** a whole KHG (tens to hundreds of thousand ha) is months of flying. Fly corridors along the canals where blocks are planned, wide enough for both banks and some land beyond, plus one or two river-to-centre transects across a dome.
7. **Write the decision rules before the flight**, e.g. drone DTM error at held-out GNSS points per cover class (bank heights need about 0.2 m), and whether block counts from the drone corridors differ from those from DeltaDTM.

Candidate site (not decided): Sugihan-Lumpur (KLHK LiDAR of unknown date, pipeline set up, ICESat-2 subsidence trend measured). Before the flight: draft corridors from the canal, licence and block layers, and estimate the cover-class mix from ForTy and WorldCover.

## Canal detection from the drone survey (discussed 2026-11-05, not tested)

Raw DEMNAS cannot show canals (`repeat-dem/runs/checks/canal_visibility.md`: about 1 m pits everywhere; at 8 m even the LiDAR keeps only primary canals). A drone survey should work for canal detection where DEMNAS fails, for different reasons per cover:
- Open land: the trough and the banks resolve at 10-20 cm; noise is centimetres on textured ground, not the metre-scale pits of DEMNAS.
- Water: photogrammetry fails on open water (no texture, reflections), leaving holes or smeared surfaces. For detection that is a signal: a long narrow hole or flat patch is a canal. For canal water levels it is a limit: take the level from the bank edge or the GNSS points, not from the surface over water.
- Tree cover: a canal shows as a gap in the canopy surface, several metres deep, but so does a road corridor; the orthomosaic (water colour, texture) separates them.
- Weak case: narrow tertiary canals under overhanging fern or shrub, which hides them in both the surface and the image.
Use the orthomosaic and the surface together (a U-Net on both, or the trough filter plus a water mask). Test on the first flight with the same transect check as DEMNAS, and with field-checked canals per class and cover type, since mapped lines miss canals by more than 10 m in places.
