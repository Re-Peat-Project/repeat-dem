(() => {
  /* Scene geometry, builders, animation and controls. Content lives in explain-data.js. */
  const NS = 'http://www.w3.org/2000/svg';
  const $ = id => document.getElementById(id);
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const A = window.anime;
  const { GROUPS, P, kindText } = window.EXPLAIN_DATA;
  const ICON = n => `assets/${n}.svg`;
  
  /* ---------- geometry ---------- */
  function rngFactory(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  const rng = rngFactory(11);
  const xs = []; for (let x = 120; x <= 1060; x += 10) xs.push(x);
  const ell = x => { if (x < 230) return 395; const u = (x - 645) / 415; return 395 - 155 * Math.sqrt(Math.max(0, 1 - u * u)); };
  const sub = x => x < 230 ? 0 : 30 * Math.exp(-(1060 - x) / 150);
  const yOld = x => ell(x);
  const yNow = x => ell(x) + sub(x);
  const yBase = x => x < 230 ? 415 + (x - 120) / 110 * 45 : 462 + 6 * Math.sin(x / 70);
  const yWt = x => Math.min(yBase(x) - 4, yNow(x) + (x < 230 ? 3 : 8 + 19 * Math.exp(-(1060 - x) / 110)));
  const f1 = v => v.toFixed(1);
  const line = f => xs.map((x, i) => (i ? 'L' : 'M') + x + ' ' + f1(f(x))).join(' ');
  const fill = f => line(f) + ' ' + xs.slice().reverse().map(x => 'L' + x + ' ' + f1(yBase(x))).join(' ') + ' Z';
  
  const D = { now: line(yNow), old: line(yOld), fillNow: fill(yNow), fillOld: fill(yOld) };
  $('surface').setAttribute('d', D.now);
  $('peatFill').setAttribute('d', D.fillNow);
  $('ghost').setAttribute('d', D.old);
  $('wt').setAttribute('d', line(yWt));
  $('baseLine').setAttribute('d', line(yBase));
  $('substrate').setAttribute('d', 'M0 400 L120 400 ' + xs.map(x => 'L' + x + ' ' + f1(yBase(x))).join(' ') + ' L1110 466 L1200 466 L1200 640 L0 640 Z');
  
  // DSM: what X-band radar or stereo would record
  const dsmY = x => {
    if (x < 120) return 398;
    if (x > 1060 && x < 1110) return 452;
    if (x >= 1110) return 407;
    let c;
    if (x < 230) c = 46; else if (x < 880) c = 76; else if (x < 930) c = 76 - (x - 880) / 50 * 58; else c = 18;
    return yNow(x) - c + 4 * Math.sin(x / 21);
  };
  const dsmXs = []; for (let x = 0; x <= 1200; x += 10) dsmXs.push(x);
  $('dsm').setAttribute('d', dsmXs.map((x, i) => (i ? 'L' : 'M') + x + ' ' + f1(dsmY(x))).join(' '));
  
  // 30 m pixel staircase on the left flank
  let pd = '';
  for (let x = 290; x < 470; x += 30) { const y = f1(yNow(x + 15)); pd += (x === 290 ? 'M' : 'L') + x + ' ' + y + ' L' + (x + 30) + ' ' + y + ' '; }
  $('pix').setAttribute('d', pd);
  
  /* ---------- builders ---------- */
  const el = (tag, attrs, parent) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (parent) parent.appendChild(n); return n; };
  
  // ruler ticks
  for (let y = 190; y <= 370; y += 20) el('line', { x1: 28, x2: 40, y1: y, y2: y, stroke: '#1D2B26', 'stroke-width': 2 }, $('rulerTicks'));
  for (let y = 380; y <= 452; y += 12) el('line', { x1: 90, x2: 102, y1: y, y2: y, stroke: '#FFFFFF', 'stroke-width': 2 }, $('gaugeTicks'));
  
  // forest: stock tree icon, sized by canopy height
  const forest = $('forest');
  for (let x = 134; x <= 905; x += 24 + Math.round(rng() * 6)) {
    if (x > 862 && x < 898) continue; // canopy gap for the ICESat-2 beam
    const g0 = yNow(x);
    const h = x < 230 ? 34 + rng() * 14 : 58 + rng() * 32;
    el('image', { href: ICON('tree'), x: f1(x - h / 2), y: f1(g0 - h + 2), width: f1(h), height: f1(h) }, forest);
  }

  // plantation and burn scar near the canal
  const plant = $('plantation'), burn = $('burn');
  for (let x = 918; x <= 1050; x += 18) {
    const g0 = yNow(x);
    if (x > 956 && x < 1012) {
      el('path', { d: `M${x - 3} ${g0} l1 -10 l3 4 l2 -7 l1 13z`, fill: '#1C1410' }, burn);
      continue;
    }
    el('image', { href: ICON('palm'), x: x - 17, y: f1(g0 - 32), width: 34, height: 34 }, plant);
  }
  el('path', { d: `M956 ${f1(yNow(956))} Q985 ${f1(yNow(985) + 6)} 1014 ${f1(yNow(1014))}`, fill: 'none', stroke: '#1C1410', 'stroke-width': 7, 'stroke-linecap': 'round' }, burn);
  
  // fire
  const fy = yNow(985);
  const flame = el('g', { id: 'flame', transform: `translate(985 ${f1(fy)})` }, $('fire'));
  el('image', { href: ICON('fire'), x: -20, y: -40, width: 40, height: 40 }, flame);

  // radar waves: X-band stops at canopy, L-band reaches ground
  function waves(parent, x0, y0, x1, y1, n, color, sz) {
    const ang = Math.atan2(y1 - y0, x1 - x0) * 180 / Math.PI;
    const len = Math.hypot(x1 - x0, y1 - y0);
    const g = el('g', { transform: `translate(${x0} ${y0}) rotate(${f1(ang)})` }, parent);
    el('line', { x1: 0, y1: 0, x2: f1(len), y2: 0, stroke: color, 'stroke-width': 1.5, 'stroke-dasharray': '3 6', opacity: .7 }, g);
    const arcs = [];
    for (let i = 0; i < n; i++) arcs.push(el('path', { d: `M0 ${-sz} Q${sz * 0.8} 0 0 ${sz}`, fill: 'none', stroke: color, 'stroke-width': 3.5, 'stroke-linecap': 'round', 'data-len': f1(len) }, g));
    return arcs;
  }
  const xArcs = waves($('xwaves'), 222, 64, 330, yNow(330) - 82, 3, '#2F5D8A', 10);
  el('path', { d: `M330 ${f1(yNow(330) - 84)} l-8 -16 M330 ${f1(yNow(330) - 84)} l10 -14 M330 ${f1(yNow(330) - 84)} l16 -2`, stroke: '#2F5D8A', 'stroke-width': 3, 'stroke-linecap': 'round' }, $('xwaves'));
  const lArcs = waves($('lwaves'), 1098, 82, 1000, yNow(1000) - 2, 3, '#3C6E4A', 16);
  
  // lidar fan
  for (let i = -4; i <= 4; i++) el('line', { x1: 472, y1: 128, x2: 472 + i * 18, y2: f1(yNow(472 + i * 18)), stroke: '#E8532F', 'stroke-width': 1.2 }, $('lidarFan'));
  
  // rain drops
  const drops = [];
  for (let i = 0; i < 16; i++) drops.push(el('line', { x1: 604 + i * 8, x2: 600 + i * 8, y1: 126 + (i % 3) * 10, y2: 138 + (i % 3) * 10, stroke: '#1FA0C8', 'stroke-width': 2.5, 'stroke-linecap': 'round' }, $('rain')));
  
  // ICESat-2 photons
  const photons = [];
  for (let i = 0; i < 4; i++) photons.push(el('circle', { cx: 852, cy: 54, r: 3.5, fill: '#3BD16F' }, $('photons')));
  
  // peat texture: fibric on top, sapric below
  for (let i = 0; i < 170; i++) {
    const x = 240 + rng() * 800;
    const t = rng();
    const y = yNow(x) + 10 + t * (yBase(x) - yNow(x) - 18);
    if (t < 0.4) el('path', { d: `M${f1(x)} ${f1(y)} q4 -3 9 -1`, stroke: '#A97A52', 'stroke-width': 1.6, fill: 'none', 'stroke-linecap': 'round' }, $('texture'));
    else el('circle', { cx: f1(x), cy: f1(y), r: 1.4, fill: '#2C1B10' }, $('texture'));
  }
  
  // thickness arrows
  [420, 645, 880].forEach(x => el('line', { x1: x, x2: x, y1: f1(yNow(x) + 4), y2: f1(yBase(x) - 4), stroke: '#F2B705', 'stroke-width': 3, 'marker-start': 'url(#arY)', 'marker-end': 'url(#arY)' }, $('thick')));
  
  // groundwater flow chevrons
  const flows = [];
  [[340, -1], [440, -1], [820, 1], [930, 1]].forEach(([x, dir]) => {
    const y = (yWt(x) + yBase(x)) / 2;
    const g = el('g', { transform: `translate(${x} ${f1(y)})` }, $('flow'));
    const inner = el('g', {}, g);
    el('path', { d: `M${-dir * 14} -10 L${dir * 4} 0 L${-dir * 14} 10 M${-dir * 2} -10 L${dir * 16} 0 L${-dir * 2} 10`, fill: 'none', stroke: '#1FA0C8', 'stroke-width': 3.5, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, inner);
    flows.push({ n: inner, dir });
  });
  
  // evapotranspiration squiggles
  const ets = [];
  [292, 330, 368].forEach(x => {
    const y = yNow(x) - 96;
    ets.push(el('path', { d: `M${x} ${f1(y)} q6 -8 0 -16 q-6 -8 0 -16 q6 -8 0 -16`, fill: 'none', stroke: '#FFFFFF', 'stroke-width': 3, 'stroke-linecap': 'round', 'marker-end': 'url(#arW)' }, $('et')));
  });
  
  // distance to canal bracket
  el('path', { d: 'M760 492 v14 M760 499 H1060 M1060 492 v14', fill: 'none', stroke: '#FFFFFF', 'stroke-width': 3 }, $('dist'));
  
  // CO2 bubbles
  const bubbles = [];
  [934, 952, 1022, 1040, 1048].forEach((x, i) => bubbles.push(el('circle', { cx: x, cy: f1(yNow(x) - 6), r: 4 + (i % 2) * 2, fill: 'none', stroke: '#FFFFFF', 'stroke-width': 2 }, $('co2'))));
  
  // consolidation arrows
  [1028, 1050].forEach(x => el('line', { x1: x, x2: x, y1: f1(yNow(x) - 34), y2: f1(yNow(x) - 8), stroke: '#FFFFFF', 'stroke-width': 3, 'marker-end': 'url(#arW)' }, $('consol')));
  
  // shrinkage cracks
  [924, 940].forEach(x => el('path', { d: `M${x} ${f1(yNow(x))} l3 8 l-4 6 l3 8`, fill: 'none', stroke: '#1C1410', 'stroke-width': 2.5, 'stroke-linejoin': 'round' }, $('cracks')));
  
  // seasonal oscillation
  const oscG = el('g', {}, $('osc'));
  el('line', { x1: 720, x2: 720, y1: f1(yNow(720) - 30), y2: f1(yNow(720) + 30), stroke: '#FFFFFF', 'stroke-width': 4, 'marker-start': 'url(#arW)', 'marker-end': 'url(#arW)' }, oscG);
  
  // water-table logger
  const lx = 760, ly = yNow(lx);
  const lg = $('logger');
  el('rect', { x: lx - 6, y: f1(ly - 20), width: 12, height: 86, rx: 3, fill: 'rgba(255,255,255,.25)', stroke: '#FFFFFF', 'stroke-width': 2 }, lg);
  el('rect', { x: lx - 4, y: f1(yWt(lx)), width: 8, height: f1(ly + 64 - yWt(lx)), fill: '#1FA0C8' }, lg);
  el('rect', { x: lx - 13, y: f1(ly - 38), width: 26, height: 18, rx: 3, fill: '#F1EFE6', stroke: '#1D2B26', 'stroke-width': 2 }, lg);
  el('line', { x1: lx + 8, x2: lx + 8, y1: f1(ly - 38), y2: f1(ly - 54), stroke: '#1D2B26', 'stroke-width': 2 }, lg);
  const ledL = el('circle', { cx: lx - 4, cy: f1(ly - 29), r: 3, fill: '#3BD16F' }, lg);
  
  // subsidence pole with GNSS antenna, anchored in substrate
  const pg = $('pole'), px = 1036;
  el('line', { x1: px, x2: px, y1: 480, y2: 326, stroke: '#FFFFFF', 'stroke-width': 5 }, pg);
  for (let y = 336; y < 470; y += 10) el('line', { x1: px - 4, x2: px + 4, y1: y, y2: y, stroke: '#C2338A', 'stroke-width': 2 }, pg);
  el('path', { d: `M${px - 12} 326 h24 l-4 -8 h-16z`, fill: '#F1EFE6', stroke: '#1D2B26', 'stroke-width': 2 }, pg);
  const ledP = el('circle', { cx: px, cy: 314, r: 3.5, fill: '#F2B705' }, pg);
  
  // InSAR fringes
  const ix = 1000, iy = yNow(1000);
  const fr = ['#E8532F', '#F2B705', '#3BD16F', '#1FA0C8', '#7A4FD0'];
  const fringes = fr.map((c, i) => el('ellipse', { cx: ix, cy: f1(iy), rx: 18 + i * 16, ry: 5 + i * 4, fill: 'none', stroke: c, 'stroke-width': 3, opacity: .85 }, $('insar')));
  
  /* ---------- labels ---------- */
  const labelsG = $('labels');
  function tag(text, x, y, groups, opts = {}) {
    const g = el('g', { class: 'lbl tag', 'data-lg': groups }, labelsG);
    const t = el('text', { x: x, y: y, class: 'svg-text', 'text-anchor': opts.anchor || 'start' }, g);
    t.textContent = text;
    requestAnimationFrame(() => {
      const b = t.getBBox();
      const r = el('rect', { x: f1(b.x - 7), y: f1(b.y - 3), width: f1(b.width + 14), height: f1(b.height + 6), rx: 7 }, null);
      g.insertBefore(r, t);
      if (opts.to) {
        const [tx, ty] = opts.to;
        const cx = Math.max(b.x - 7, Math.min(tx, b.x + b.width + 7));
        const cy = ty > b.y + b.height ? b.y + b.height + 3 : (ty < b.y ? b.y - 3 : b.y + b.height / 2);
        const sx = (ty >= b.y && ty <= b.y + b.height) ? (tx < b.x ? b.x - 7 : b.x + b.width + 7) : cx;
        const ld = el('line', { x1: f1(sx), y1: f1(cy), x2: tx, y2: ty, stroke: '#FFFFFF', 'stroke-width': 2 }, null);
        const dot = el('circle', { cx: tx, cy: ty, r: 3.5, fill: '#FFFFFF', stroke: '#1D2B26', 'stroke-width': 1.5 }, null);
        g.insertBefore(ld, r); g.appendChild(dot);
      }
    });
    return g;
  }
  // always-on orientation labels
  tag('River', 14, 488, 'core');
  tag('Drainage canal', 1188, 506, 'core', { anchor: 'end' });
  tag('Peat dome', 610, 420, 'core', { anchor: 'middle' });
  tag('Mineral substrate', 600, 590, 'core', { anchor: 'middle' });
  // A
  tag('X-band radar bounces off the canopy', 248, 30, 'A');
  tag('L-band reaches nearer the ground', 1186, 120, 'A', { anchor: 'end' });
  tag('DSM rides on the tree tops', 560, 176, 'A');
  tag('Older DEM epoch sat higher', 830, 236, 'A', { to: [960, 294] });
  tag('Two datums, two zeros', 48, 280, 'A');
  tag('30 m pixels flatten the flank', 300, 352, 'A');
  tag('Radar sees water level, not the bank', 1186, 560, 'A', { anchor: 'end', to: [1085, 462] });
  // B
  tag('Peat thickness', 660, 352, 'B');
  tag('Peat base (mineral substrate)', 380, 500, 'B', { anchor: 'middle' });
  tag('Topogenous: fed by river water', 18, 360, 'B');
  tag('Ombrogenous: rain-fed dome', 645, 150, 'B', { anchor: 'middle' });
  tag('Fibric on top, sapric below', 820, 380, 'B');
  tag('Stiffness: how far peat squeezes', 548, 300, 'B');
  // C
  tag('Rain builds the dome', 728, 152, 'C');
  tag('Evapotranspiration', 254, 128, 'C');
  tag('Groundwater flows out to the edges', 600, 444, 'C', { anchor: 'middle' });
  tag('Water-table logger', 780, 200, 'C');
  tag('Distance to canal', 910, 528, 'C', { anchor: 'middle' });
  tag('Canal block', 1186, 400, 'C', { anchor: 'end' });
  tag('River stage', 110, 362, 'C');
  tag('Seasonal flooding', 150, 420, 'C');
  // D
  tag('Oxidation releases CO₂', 1186, 250, 'D', { anchor: 'end', to: [1046, 340] });
  tag('Compaction after drainage', 1188, 556, 'D', { anchor: 'end', to: [1050, 396] });
  tag('Seasonal rise and fall', 740, 196, 'D');
  tag('Fire burns peat away', 900, 456, 'D', { anchor: 'middle', to: [985, 322] });
  tag('Shrinkage cracks', 780, 330, 'D', { anchor: 'middle', to: [930, 306] });
  tag('Drained plantation', 1186, 212, 'D', { anchor: 'end', to: [1030, 330] });
  tag('Older surface', 880, 160, 'D', { to: [930, 282] });
  // E
  tag('Airborne LiDAR', 530, 92, 'E');
  tag('ICESat-2 / GEDI photons', 878, 30, 'E');
  tag('InSAR measures sinking', 1186, 140, 'E', { anchor: 'end', to: [1060, 336] });
  tag('GNSS and subsidence pole', 1188, 556, 'E', { anchor: 'end', to: [1036, 470] });
  tag('SIPALAGA logger', 780, 200, 'E');
  
  /* ---------- animation helpers ---------- */
  let running = [];
  const play = cfg => { if (!A || reduce) return null; const a = A(cfg); running.push(a); return a; };
  function stopAll() {
    running.forEach(a => a.pause());
    running = [];
    if (A) A.remove('#surface, #peatFill, #plantation, #osc g, #planeBody, #flame, .hotpulse');
    $('surface').setAttribute('d', D.now);
    $('peatFill').setAttribute('d', D.fillNow);
    $('plantation').removeAttribute('transform');
    $('planeBody').removeAttribute('transform');
    document.querySelectorAll('[data-anim]').forEach(n => { n.style.transform = ''; n.style.opacity = ''; });
  }
  const mark = nodes => nodes.forEach(n => n.setAttribute('data-anim', ''));
  
  const MODES = {
    A() {
      const dsm = $('dsm');
      play({ targets: dsm, strokeDashoffset: [A ? A.setDashoffset : 0, 0], duration: 1800, easing: 'easeInOutSine', complete: () => dsm.setAttribute('stroke-dasharray', '10 7') });
      [xArcs, lArcs].forEach(arcs => arcs.forEach((a, i) => {
        mark([a]);
        play({ targets: a, translateX: [0, +a.getAttribute('data-len')], opacity: [{ value: 1, duration: 200 }, { value: 0, duration: 400, delay: 1000 }], duration: 1600, delay: i * 520, loop: true, easing: 'linear' });
      }));
    },
    B() {
      play({ targets: '#thick line', strokeDashoffset: [A ? A.setDashoffset : 0, 0], duration: 1200, delay: A ? A.stagger(250) : 0, easing: 'easeOutQuad' });
      const sp = $('spring').querySelector('path'); mark([sp]);
      sp.style.transformOrigin = '520px 350px';
      play({ targets: sp, scaleY: [1, 0.78], duration: 900, direction: 'alternate', loop: true, easing: 'easeInOutSine' });
    },
    C() {
      mark(drops);
      drops.forEach((d, i) => play({ targets: d, translateY: [0, 90], opacity: [1, 0], duration: 1100, delay: i * 70, loop: true, easing: 'easeInQuad' }));
      mark(ets);
      ets.forEach((e, i) => play({ targets: e, translateY: [8, -10], opacity: [0, 1, 0], duration: 2200, delay: i * 400, loop: true, easing: 'linear' }));
      flows.forEach((f, i) => { mark([f.n]); play({ targets: f.n, translateX: [0, f.dir * 18], opacity: [1, 0.2], duration: 1300, delay: i * 200, loop: true, easing: 'easeInSine' }); });
      mark([ledL]);
      play({ targets: ledL, opacity: [1, 0.15], duration: 600, direction: 'alternate', loop: true, easing: 'linear' });
    },
    D() {
      $('surface').setAttribute('d', D.old);
      $('peatFill').setAttribute('d', D.fillOld);
      $('plantation').setAttribute('transform', 'translate(0 -18)');
      const t = { v: -18 };
      play({ targets: '#surface', d: [{ value: D.now }], duration: 3200, delay: 400, easing: 'easeInOutQuad' });
      play({ targets: '#peatFill', d: [{ value: D.fillNow }], duration: 3200, delay: 400, easing: 'easeInOutQuad' });
      play({ targets: t, v: 0, duration: 3200, delay: 400, easing: 'easeInOutQuad', update: () => $('plantation').setAttribute('transform', `translate(0 ${f1(t.v)})`) });
      mark(bubbles);
      bubbles.forEach((b, i) => play({ targets: b, translateY: [0, -46], opacity: [0, 1, 0], duration: 2400, delay: 600 + i * 380, loop: true, easing: 'easeOutSine' }));
      const fi = $('flame').firstChild; mark([fi]);
      fi.style.transformOrigin = '0px 0px';
      play({ targets: fi, scaleY: [1, 1.25], scaleX: [1, 0.9], duration: 360, direction: 'alternate', loop: true, easing: 'easeInOutSine' });
      const og = $('osc').firstChild; mark([og]);
      play({ targets: og, translateY: [-6, 6], duration: 1600, direction: 'alternate', loop: true, easing: 'easeInOutSine' });
    },
    E() {
      play({ targets: '#planeBody', translateX: [-160, 200], duration: 6000, loop: true, easing: 'linear' });
      mark(photons);
      photons.forEach((p, i) => play({ targets: p, translateX: [0, 26], translateY: [0, 218], opacity: [1, 0.3], duration: 1400, delay: i * 350, loop: true, easing: 'linear' }));
      mark(fringes);
      play({ targets: fringes, opacity: [0.15, 0.95], duration: 900, delay: A ? A.stagger(180) : 0, direction: 'alternate', loop: true, easing: 'easeInOutSine' });
      mark([ledP, ledL]);
      play({ targets: [ledP, ledL], opacity: [1, 0.15], duration: 700, direction: 'alternate', loop: true, easing: 'linear' });
    },
    all() {
      if (!A) return;
      play({ targets: '#surface', strokeDashoffset: [A.setDashoffset, 0], duration: 2200, easing: 'easeInOutSine', complete: () => $('surface').removeAttribute('stroke-dasharray') });
    }
  };
  
  /* ---------- state ---------- */
  let mode = 'all', current = null;
  
  function applyDim(g) {
    document.querySelectorAll('#art [data-g]').forEach(n => {
      const gs = n.getAttribute('data-g').split(',');
      n.classList.toggle('is-dim', g !== 'all' && !gs.includes(g));
    });
    document.querySelectorAll('#labels .lbl').forEach(n => {
      const lg = n.getAttribute('data-lg');
      n.classList.toggle('on', lg === 'core' ? g === 'all' : lg === g);
    });
  }
  
  function clearHot() {
    document.querySelectorAll('#art .hot').forEach(n => { n.classList.remove('hot'); n.classList.remove('hotpulse'); n.style.opacity = ''; });
  }
  
  function setMode(g, keepTour) {
    if (!keepTour) stopTour();
    mode = g; current = null;
    stopAll(); clearHot();
    applyDim(g);
    document.querySelectorAll('.g-btn').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.g === g)));
    const G = GROUPS.find(x => x.id === g);
    $('gTitle').textContent = g === 'all' ? 'Overview' : `${G.letter}. ${G.name}`;
    $('gSum').textContent = G.sum;
    const list = $('plist'); list.innerHTML = '';
    const items = g === 'all' ? [] : P.filter(p => p.g === g);
    items.forEach(p => {
      const li = document.createElement('li');
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'p-btn'; b.setAttribute('aria-pressed', 'false');
      b.innerHTML = `<span>${p.name}</span><small>${p.kind}</small>`;
      b.addEventListener('click', () => { stopTour(); selectParam(p, b); });
      li.appendChild(b); list.appendChild(li);
    });
    if (g === 'all') {
      const counts = ['A', 'B', 'C', 'D', 'E'].map(k => `${k}: ${P.filter(p => p.g === k).length}`);
      $('detail').innerHTML = `<h3>Thirty items in five groups</h3><p class="kind">Twenty-five parameters plus five observation types</p><dl><dt>How to read it</dt><dd>Yellow is the true peat surface. Magenta is what most open DEMs actually record. Blue is the water table that shapes the dome.</dd><dt>Items per group</dt><dd>${counts.join(', ')}</dd></dl>`;
    } else {
      $('detail').innerHTML = '<p class="empty">Select a parameter to highlight it in the picture and see its data source and reference.</p>';
    }
    MODES[g] && MODES[g]();
  }
  
  function selectParam(p, btn) {
    clearHot(); current = p;
    document.querySelectorAll('.p-btn').forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
    p.hot.forEach(id => {
      const n = $(id); if (!n) return;
      n.classList.remove('is-dim'); n.classList.add('hot', 'hotpulse');
      play({ targets: n, opacity: [1, 0.55], duration: 700, direction: 'alternate', loop: 3, easing: 'easeInOutSine', complete: () => { n.style.opacity = ''; } });
    });
    $('detail').innerHTML = `<h3>${p.name}</h3><p class="kind">${kindText[p.kind]}</p><dl><dt>Relationship to elevation</dt><dd>${p.rel}</dd><dt>Data and source</dt><dd>${p.data}</dd><dt>Reference</dt><dd>${p.ref}</dd></dl>`;
  }
  
  /* ---------- controls ---------- */
  const gWrap = $('groups');
  GROUPS.forEach(G => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'g-btn'; b.dataset.g = G.id; b.setAttribute('aria-pressed', 'false');
    b.innerHTML = G.id === 'all' ? `<b aria-hidden="true">✦</b>${G.name}` : `<b aria-hidden="true">${G.letter}</b>${G.name}`;
    b.addEventListener('click', () => setMode(G.id));
    gWrap.appendChild(b);
  });
  
  let tourTimer = null;
  const order = ['A', 'B', 'C', 'D', 'E'];
  function stopTour() {
    if (tourTimer) { clearInterval(tourTimer); tourTimer = null; }
    $('tour').setAttribute('aria-pressed', 'false'); $('tour').textContent = 'Play tour';
  }
  $('tour').addEventListener('click', () => {
    if (tourTimer) { stopTour(); return; }
    let i = 0;
    setMode(order[i], true);
    $('tour').setAttribute('aria-pressed', 'true'); $('tour').textContent = 'Stop tour';
    tourTimer = setInterval(() => { i = (i + 1) % order.length; setMode(order[i], true); }, 8000);
  });
  
  // start
  requestAnimationFrame(() => setMode('all'));
})();
