/* Content for the explainer: parameter groups, parameters and their sources. */
window.EXPLAIN_DATA = (() => {
  const GROUPS = [
    { id: 'all', letter: '·', name: 'Overview', sum: 'Every elevation on a peat DTM mixes four things: what the sensor sees, how much peat there is, how wet it is, and when it was measured. Pick a group to see each part.' },
    { id: 'A', letter: 'A', name: 'Sensor', sum: 'Before any physics, open DEMs record the canopy, on a given date, on a given datum, at a given pixel size.' },
    { id: 'B', letter: 'B', name: 'Peat body', sum: 'The surface is the peat base plus the peat thickness. Peat type decides which physics shapes it.' },
    { id: 'C', letter: 'C', name: 'Hydrology', sum: 'Rain-fed domes are shaped by groundwater: rainfall builds them, conductivity and drainage flatten them.' },
    { id: 'D', letter: 'D', name: 'Dynamics', sum: 'Drained peat sinks. It oxidises, compacts, shrinks, burns, and rises and falls with the seasons.' },
    { id: 'E', letter: 'E', name: 'Observations', sum: 'What we can measure to correct the open DTM and to check it independently.' }
  ];
  const P = [
    ['A', 'Canopy height', 'direct', 'A DSM sits above the ground by part of the canopy height.', 'GEDI L2A, ICESat-2 ATL08, canopy-height maps', 'Dubayah et al., 2020; Hawker et al., 2022', ['forest', 'dsm']],
    ['A', 'Radar wavelength', 'direct', 'X- and C-band scatter near the canopy top; L-band penetrates deeper.', 'Product metadata (TanDEM-X and Copernicus are X-band)', 'Rizzoli et al., 2017', ['xwaves', 'lwaves']],
    ['A', 'Acquisition epoch', 'direct', 'Older DEMs sit higher on subsiding peat.', 'DEM metadata, LiDAR survey date', 'Hoyt et al., 2020', ['ghost']],
    ['A', 'Vertical datum / geoid', 'direct', 'A constant or regional offset, possibly decimetres.', 'EGM2008, InaGeoid (BIG), GNSS benchmarks', 'Pavlis et al., 2012', ['ruler']],
    ['A', 'Resolution and interpolation', 'direct', 'Smooths canal banks and dome edges.', 'DEM specification, LiDAR point density', 'Vernimmen et al., 2019', ['pix']],
    ['A', 'Water surfaces and canals', 'direct', 'Radar returns the water level, not the bank or bed.', 'Canal network, JRC Global Surface Water', 'Pekel et al., 2016', ['river', 'canalWater']],
    ['B', 'Peat thickness', 'direct', 'Surface = peat base + thickness.', 'Field borings, national peat map (BBSDLP)', 'Vernimmen et al., 2020', ['thick']],
    ['B', 'Mineral substrate elevation', 'direct', 'The lower boundary; roughly flat under ombrogenous domes.', 'Borings, interpolation', 'Vernimmen et al., 2020', ['baseLine']],
    ['B', 'Peat type (ombrogenous / topogenous)', 'indirect', 'Selects the physics: dome curvature, or river and flood control.', 'Peat thickness, dome fit, flood frequency, vegetation', 'Ingram, 1982; Cobb et al., 2017', ['floodpools', 'surface']],
    ['B', 'Bulk density and maturity', 'indirect', 'Sets compression, oxidation, hydraulic conductivity and specific yield.', 'Field samples, literature', 'Hooijer et al., 2012; Mahdiyasa et al., 2024', ['texture']],
    ['B', 'Peat stiffness', 'indirect', 'Controls how far the surface deforms under load and water-table change.', 'Lab tests, literature', 'Mahdiyasa et al., 2023', ['spring']],
    ['C', 'Net rainfall (P − ET) and regime', 'indirect', 'More stable net rainfall allows a higher, more curved stable dome.', 'CHIRPS, GPM IMERG, MODIS MOD16', 'Cobb et al., 2017; Funk et al., 2015; Mu et al., 2011', ['cloud', 'et']],
    ['C', 'Hydraulic conductivity K', 'indirect', 'Higher K gives a flatter dome.', 'Slug or pumping tests, literature', 'Ingram, 1982; Urzainki et al., 2023', ['flow']],
    ['C', 'Specific yield Sy', 'indirect', 'Controls how fast the water table responds, and so the surface oscillation.', 'Field, literature', 'Urzainki et al., 2020', ['wt']],
    ['C', 'Water-table depth', 'indirect', 'A deeper water table speeds subsidence.', 'SIPALAGA (BRGM), loggers', 'Hooijer et al., 2012', ['wt', 'logger']],
    ['C', 'Distance to canal or river', 'indirect', 'Drainage and subsidence are strongest near canals.', 'Canal and river network', 'Umarhadi et al., 2022', ['dist']],
    ['C', 'Canal water level and blocks', 'indirect', 'Boundary condition for the water table; blocks slow subsidence.', 'Canal surveys, block inventory', 'Urzainki et al., 2020', ['block', 'canalWater']],
    ['C', 'River stage, tides, sea level', 'indirect', 'The drainage base and lower limit of the surface in topogenous and coastal areas.', 'Gauges, tide models, DeltaDTM', 'Hooijer et al., 2012; Pronk et al., 2024', ['gauge']],
    ['C', 'Inundation frequency', 'indirect', 'Marks topogenous peat and the drainability limit.', 'Sentinel-1 flood maps, JRC GSW', 'Pekel et al., 2016', ['floodpools']],
    ['D', 'Oxidation', 'direct', 'Irreversible lowering; faster with a deeper water table.', 'InSAR, subsidence poles', 'Hooijer et al., 2012', ['co2']],
    ['D', 'Consolidation', 'direct', 'Fast lowering in the first years after drainage.', 'InSAR time series, poles', 'Hooijer et al., 2012', ['consol']],
    ['D', 'Shrinkage', 'direct', 'Lowering in the dry season.', 'InSAR seasonal signal', 'Wösten et al., 1997', ['cracks']],
    ['D', 'Seasonal oscillation', 'direct', 'A reversible rise and fall with the water table.', 'InSAR (APSIS), loggers', 'Price & Schlotzhauer, 1999; Alshammari et al., 2018', ['osc']],
    ['D', 'Fire and burn depth', 'direct', 'Sudden lowering of decimetres.', 'Burn-scar maps, multi-epoch LiDAR', 'Ballhorn et al., 2009', ['fire', 'burn']],
    ['D', 'Land cover and drainage age', 'indirect', 'Subsidence slows after about 9 years of drainage.', 'Landsat time series, MapBiomas Indonesia, KLHK land cover', 'Umarhadi et al., 2022', ['plantation']],
    ['E', 'Airborne LiDAR DTM', 'reference', 'The reference surface, with tiles held out for validation.', 'BRGM, KHG reports', 'Vernimmen et al., 2019', ['plane']],
    ['E', 'ICESat-2 / GEDI ground points', 'constraint', 'Ground points used to correct open-DEM residuals by kriging or Random Forest.', 'NASA Earthdata', 'Berninger & Siegert, 2020', ['icesat']],
    ['E', 'InSAR (ALOS-2, NISAR, Sentinel-1)', 'constraint', 'Subsidence trend and seasonal term to bring every DEM to one date.', 'JAXA, ASF DAAC, Copernicus', 'Hoyt et al., 2020; Berardino et al., 2002', ['insar', 'lsat']],
    ['E', 'GNSS benchmarks, subsidence poles', 'constraint', 'Absolute reference for InSAR and a datum check.', 'Field survey, BIG', 'Hooijer et al., 2012', ['pole']],
    ['E', 'SIPALAGA water-table data', 'constraint', 'Calibrates the groundwater model; independent validation.', 'BRGM / KLH', 'Urzainki et al., 2023', ['logger']]
  ].map(([g, name, kind, rel, data, ref, hot]) => ({ g, name, kind, rel, data, ref, hot }));
  
  const kindText = { direct: 'Direct effect on elevation', indirect: 'Indirect effect, through another parameter', reference: 'Reference data', constraint: 'Observation used as a constraint or check' };
  return { GROUPS, P, kindText };
})();
