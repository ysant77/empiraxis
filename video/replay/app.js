/* Empiraxis Mission Control — a replay of recorded artifacts. Nothing here calls a model or runs training. */
const D = window.DATA, TL = window.TL;
const CAPTURE = new URLSearchParams(location.search).has('capture');
if (CAPTURE) document.body.classList.add('capture');
const $ = id => document.getElementById(id);
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const ease = x => { x = clamp(x); return x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
const eout = x => 1 - Math.pow(1 - clamp(x), 3);
const lerp = (a, b, p) => a + (b - a) * p;
const S = {}; TL.scenes.forEach(s => S[s.id] = s);
const LS = id => TL.lines.filter(l => l.scene === id);
const vis = (id, t, fi = .6, fo = .6) => { const s = S[id]; return s ? clamp((t - s.start) / fi) * clamp((s.end - t) / fo) : 0; };
const at = (l, f) => l.start + l.dur * f;
const fmt = n => n.toLocaleString('en-US');

/* ---------------- map (MapLibre globe projection) ---------------- */
const DAY0 = Date.UTC(2015, 7, 25);
const dayIdx = s => Math.round((Date.parse(s + 'T00:00:00Z') - DAY0) / 864e5);
const firmsGeo = { type: 'FeatureCollection', features: D.firms.map(([x, y, d]) => ({ type: 'Feature', properties: { d: dayIdx(d) }, geometry: { type: 'Point', coordinates: [x, y] } })) };
const boxGeo = { type: 'FeatureCollection', features: D.boxes.map(b => { const e = b.extent; return { type: 'Feature', properties: { id: b.id },
  geometry: { type: 'Polygon', coordinates: [[[e.min_lon, e.min_lat], [e.max_lon, e.min_lat], [e.max_lon, e.max_lat], [e.min_lon, e.max_lat], [e.min_lon, e.min_lat]]] } }; }) };
const neaGeo = { type: 'FeatureCollection', features: Object.entries(D.nea).map(([k, c]) => ({ type: 'Feature', properties: { k }, geometry: { type: 'Point', coordinates: c } })) };
$('firms-n').textContent = fmt(D.firms_total);
const map = new maplibregl.Map({
  container: 'map', interactive: !CAPTURE, attributionControl: { compact: false }, fadeDuration: 0, preserveDrawingBuffer: true,
  style: { version: 8, projection: { type: 'globe' },
    sky: { 'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 6, .4, 9, 0] },
    sources: { bm: { type: 'raster', tileSize: 256, maxzoom: 8,
      tiles: ['https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg'],
      attribution: 'NASA Blue Marble (GIBS) · fire data NASA FIRMS · PM2.5 NEA' },
      firms: { type: 'geojson', data: firmsGeo }, boxes: { type: 'geojson', data: boxGeo }, nea: { type: 'geojson', data: neaGeo } },
    layers: [
      { id: 'bg', type: 'background', paint: { 'background-color': '#04070e' } },
      { id: 'bm', type: 'raster', source: 'bm', paint: { 'raster-saturation': -.35, 'raster-brightness-max': .72, 'raster-contrast': .1 } },
      { id: 'firms-glow', type: 'circle', source: 'firms', paint: { 'circle-color': '#ff7a1a', 'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 2, 6, 5], 'circle-blur': 1, 'circle-opacity': 0 } },
      { id: 'firms', type: 'circle', source: 'firms', paint: { 'circle-color': '#ffb15c', 'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, .6, 6, 1.6], 'circle-opacity': 0 } },
      { id: 'boxes', type: 'line', source: 'boxes', paint: { 'line-color': '#f5b942', 'line-width': 2, 'line-dasharray': [3, 2], 'line-opacity': 0 } },
      { id: 'nea-halo', type: 'circle', source: 'nea', paint: { 'circle-color': '#38e1d2', 'circle-radius': 14, 'circle-blur': .8, 'circle-opacity': 0 } },
      { id: 'nea', type: 'circle', source: 'nea', paint: { 'circle-color': '#38e1d2', 'circle-radius': 5, 'circle-stroke-color': '#04070e', 'circle-stroke-width': 1.5, 'circle-opacity': 0 } },
    ] },
  center: [75, 10], zoom: 1.15,
});
let mapReady = false; map.on('load', () => { mapReady = true; });

function camEarth(t) {
  const e = LS('earth'), c = S.close, K = [
    [0, [70, 8], 1.6, 0, 0], [4.2, [98, 2], 2.3, 0, 0], [at(e[0], .75), [106.4, -1.2], 4.3, 28, -8], [e[1].start + .4, [106, -.9], 4.55, 30, -8],
    [at(e[1], .62), [103.84, 1.34], 8.0, 42, 8], [S.problem.end + 2, [103.84, 1.34], 8.9, 52, 14],
    [c.start - .1, [103.84, 1.34], 7.6, 40, 8], [c.start + 4.6, [102, 3], 1.7, 0, 0], [S.credits.end, [96, 4], 1.35, 0, 0]];
  let i = 0; while (i < K.length - 1 && K[i + 1][0] <= t) i++;
  const a = K[i], b = K[Math.min(i + 1, K.length - 1)]; const p = b[0] > a[0] ? ease((t - a[0]) / (b[0] - a[0])) : 1;
  // fly-to style: interpolate zoom in log space through the path
  return { center: [lerp(a[1][0], b[1][0], p), lerp(a[1][1], b[1][1], p)], zoom: lerp(a[2], b[2], p), pitch: lerp(a[3], b[3], p), bearing: lerp(a[4], b[4], p) };
}
function placeLabel(id, lnglat, op, dx = 0, dy = 0) {
  const p = map.project(lnglat); const el = $(id); el.style.left = (p.x + dx) + 'px'; el.style.top = (p.y + dy) + 'px'; el.style.opacity = op;
}

/* ---------------- council: roles, wires, feed ---------------- */
const ROLES = [
  { key: 'product_manager', name: 'Product manager', tools: ['review_scope', 'forward_decision'], x: 0, y: 0 },
  { key: 'geospatial_engineer', name: 'Engineering lead', tools: ['choose_strategy', 'choose_method', 'review_results', 'recommend'], x: 430, y: 0 },
  { key: 'data_specialist', name: 'Data specialist', tools: ['prepare_data', 'submit_note'], x: 0, y: 280 },
  { key: 'ml_engineer', name: 'ML specialist', tools: ['train_models', 'submit_note'], x: 430, y: 280 }];
ROLES.forEach((r, i) => { const el = document.createElement('div'); el.className = 'role'; el.id = 'role' + i; el.style.left = r.x + 'px'; el.style.top = r.y + 'px';
  el.innerHTML = `<div class="rn">${r.name}</div><div class="rk">role of muse-glimmer-30B</div><div class="cnt" id="rc${i}">0 calls</div>
  <div class="tools">${r.tools.map(t => `<span class="tool" data-tool="${t}">${t}</span>`).join('')}</div><div class="stampx" id="rs${i}" style="opacity:0"></div><div class="last" id="rl${i}">waiting</div>`;
  el.title = 'Hover a tool to see its recorded use'; $('roles').appendChild(el); });
const STEPS = ['requested', 'scoped', 'profiled', 'planned', 'executing', 'evaluated', 'reviewed', 'forwarded'];
$('stepper').innerHTML = STEPS.map(s => `<div class="step" id="sp-${s}">${s.toUpperCase()}</div>`).join('');
// wires: role right/left edge -> gate; gate -> tools -> evaluator -> person
const GATE = [1380, 205], TOOLS = [1380, 330], EVAL = [1380, 460], HUMAN = [1380, 560];
const RCENTER = i => [500 + ROLES[i].x + 410, 185 + ROLES[i].y + 131];
const W = []; const svg = $('wires');
function wire(a, b, id) { const p = document.createElementNS('http://www.w3.org/2000/svg', 'path'); const mx = (a[0] + b[0]) / 2;
  p.setAttribute('d', `M${a[0]} ${a[1]} C${mx} ${a[1]} ${mx} ${b[1]} ${b[0]} ${b[1]}`); p.setAttribute('fill', 'none'); p.setAttribute('stroke', '#1f3a4a'); p.setAttribute('stroke-width', 2); p.id = id; svg.appendChild(p); W.push(p); return p; }
ROLES.forEach((r, i) => wire(RCENTER(i), GATE, 'w' + i));
const pk = document.createElementNS('http://www.w3.org/2000/svg', 'circle'); pk.setAttribute('r', 7); pk.setAttribute('fill', '#38e1d2'); pk.setAttribute('filter', 'drop-shadow(0 0 8px #38e1d2)'); pk.setAttribute('opacity', 0); svg.appendChild(pk);

// map each trace record to film time (anchors follow the narration)
const C = LS('council'), E = LS('evidence'), G = LS('gate')[0];
const TR = LS('train'), end = l => l.start + l.dur;
const ANCH = [[0, C[0].start - 1.0], [3, at(C[0], .85)], [4, C[1].start + .3], [10, at(C[1], .45)], [11, at(C[1], .55)], [12, at(C[1], .68)], [14, at(C[1], .88)],
  [15, C[2].start + .2], [16, at(C[2], .45)], [19, end(C[2])], [22, TR[0].start + .1], [24, at(TR[0], .15)], [30, at(TR[0], .25)], [31, at(TR[0], .3)],
  [32, at(TR[0], .75)], [33, at(TR[2], .4)], [37, end(TR[2]) + .3], [38, E[0].start + .2], [40, E[2].start - .4], [42, E[2].start + .5], [44, E[2].start + E[2].dur],
  [46, G.start - .3], [48, at(G, .3)], [51, at(G, .7)]];
const REC_T = D.trace.map(r => { const s = r.seq; let i = 0; while (i < ANCH.length - 1 && ANCH[i + 1][0] <= s) i++;
  const a = ANCH[i], b = ANCH[Math.min(i + 1, ANCH.length - 1)]; return b[0] === a[0] ? a[1] : lerp(a[1], b[1], (s - a[0]) / (b[0] - a[0])); });
const roleIdx = k => ROLES.findIndex(r => r.key === k);
const detail = r => { const d = r.data;
  if (r.event === 'proposal_reviewed') return `${d.tool} · ${d.valid ? '<span class="good">valid</span>' : '<span class="bad">refused: ' + (d.issues[0] || '') + '</span>'}`;
  if (r.event === 'model_turn') return `${d.role} → ${(d.tool_calls || []).map(c => c.name).join(', ')}`;
  if (r.event === 'harness_transition') return `${d.from} → ${d.to}`;
  if (r.event === 'tool_result') return `${d.name} · ${d.outcome}`;
  if (r.event === 'artifact_stored') return `${d.name} · ${String(d.sha256).slice(0, 10)}`;
  if (r.event === 'inference_verified') return `${d.model_id} reload · max |Δ| ${d.max_abs_difference} · ${fmt(d.rows)} rows`;
  if (r.event === 'tuning_verified') return `ridge α ${d.alpha} · reload |Δ| ${d.reload_max_abs_difference}`;
  if (r.event === 'family_comparison') return `trained: ${d.trained.join(' + ')}`;
  if (r.event === 'role_invocation') return `${d.role}${d.status ? ' · ' + d.status : ''}`;
  if (r.event === 'finish') return `${d.status} · ${d.reason}`;
  return d.task_id || ''; };
const ROWS = D.trace.map(r => { const el = document.createElement('div'); el.className = 'fr';
  el.innerHTML = `<span>#${r.seq}</span><span>${r.ts.slice(11, 19)}</span><span>${r.actor}</span><span class="ev">${r.event}</span><span>${detail(r)}</span><span class="h">${r.hash}</span>`;
  el.onmouseenter = () => showPop(`TRACE #${r.seq} · ${r.event}`, JSON.stringify(r.data, null, 1).slice(0, 600), `actor ${r.actor} · hash ${r.hash}…`, 1300, 420, 1);
  el.onmouseleave = () => showPop('', '', '', 0, 0, 0); return el; });

function showPop(title, body, foot, x, y, op) { const p = $('pop'); if (op && p.dataset.t !== title) { p.innerHTML = `<div class="pt">${title}</div><div class="pb">${body}</div><div class="pf">${foot}</div>`; p.dataset.t = title; }
  p.style.left = x + 'px'; p.style.top = y + 'px'; p.style.opacity = op; }
const recBy = seq => D.trace.find(r => r.seq === seq);
const proposalText = seq => { const p = recBy(seq).data.proposal || {}; return Object.entries(p).filter(([k]) => k !== 'reason' && k !== 'note').map(([k, v]) => `${k}: ${v}`).join('\n') +
  (p.reason ? `\nreason: “${p.reason.slice(0, 150)}…”` : '') + (p.note ? `\nnote: “${p.note.slice(0, 150)}…”` : ''); };
const POPS = [ // [seq, title, x, y, cursor target]
  [14, 'MODEL PROPOSAL · choose_strategy · trace #14', 930, 300, [1140, 260]],
  [16, 'MODEL PROPOSAL · choose_method · trace #16', 930, 300, [1140, 260]]];

/* ---------------- evidence ---------------- */
const CMP = Object.fromEntries(D.result.comparison.map(c => [c.model, c]));
const ALL = [['Lagged ridge · existing', 'B4_lagged_ridge', '#4ade80'], ['Tuned ridge', 'candidate-ridge-cv', '#f5b942'], ['TCN · neural', 'candidate-1', '#f87171'], ['Persistence', 'B0_persistence', '#64748b']];
function bars(host, key, max, pre) { $(host).innerHTML = ALL.map(([n, m, c], i) => `<div class="brow"><div class="bn">${n}</div><div class="tr"><div class="f" id="${pre}${i}" style="background:${c}"></div></div><div class="bv" id="${pre}v${i}">0</div></div>`).join(''); }
bars('bars-all', 'mae', 6, 'ba'); bars('bars-55', 'above_55_mae', 35, 'bb');
$('ax-all').innerHTML = [0, 1, 2, 3, 4, 5, 6].map(v => `<span style="left:${v / 6 * 100}%">${v}</span>`).join('');
const REC = recBy(42).data.proposal.reason;
// evidence trace ticker
const tick = document.createElement('div'); tick.id = 'evtick'; tick.style.cssText = 'position:absolute;left:40px;right:40px;top:840px;height:40px;font:500 17px var(--mono);color:#94a3b8;border-top:1px solid #1b2840;padding-top:12px';
$('L-evidence').appendChild(tick);

/* ---------------- 2015 ablation (published evidence) ---------------- */
const AB = [['Persistence', 'repeat the last value', 'B0', '#64748b'], ['+ PM2.5 history', 'ridge on 24 lags', 'B1', '#4ade80'], ['+ ERA5 wind and rain', '30 reanalysis features', 'B2', '#60a5fa'], ['+ FIRMS fires', '9 fire-count features', 'B3', '#ff9a3c']];
$('abars').innerHTML = AB.map(([n, d, k, c], i) => `<div class="abrow"><div class="an">${n}<small>${d}</small></div><div class="tr"><div class="f" id="af${i}" style="background:${c}"></div></div><div class="av" id="av${i}">0</div></div>`).join('');

/* ---------------- training (recorded run artifacts) ---------------- */
const TRN = D.train, NS = 'http://www.w3.org/2000/svg';
const el = (tag, at, host) => { const e = document.createElementNS(NS, tag); Object.entries(at).forEach(([k, v]) => e.setAttribute(k, v)); if (host) host.appendChild(e); return e; };
const YX = y => 70 + (y - 2014) / 5 * 470;
['2016', '2017', '2018'].forEach((y, i) => { const r = document.createElement('div'); r.className = 'cvr'; r.id = 'cv' + i; const Y = +y;
  r.innerHTML = `<div class="yr">${y}</div><div class="bar trn" style="left:${YX(2014)}px;width:${YX(Y) - YX(2014) - 4}px"></div><div class="bar val" style="left:${YX(Y)}px;width:${YX(Y + 1) - YX(Y)}px"></div>
  <div class="m">${TRN.fold_mae['10000'][y].toFixed(2)} <span style="color:#64748b">vs ${TRN.persistence_fold_mae[y].toFixed(2)}</span><small>ridge α 10,000 · persistence</small></div>`; $('cvrows').appendChild(r); });
{ const h = document.createElement('div'); h.className = 'cvr'; h.style.height = '24px'; h.innerHTML = [2014, 2015, 2016, 2017, 2018, 2019].map(y => `<span style="position:absolute;left:${YX(y)}px;font:14px var(--mono);color:#475569;transform:translateX(-50%)">${y}</span>`).join('')
  + `<span style="position:absolute;left:${YX(2014)}px;top:-6px"></span>`; $('cvrows').appendChild(h); }
const pen = $('pensvg'), PXa = a => 70 + Math.log10(a) / 4 * 660, PYa = v => 200 - (v - 5.94) / (6.12 - 5.94) * 180;
[5.95, 6.0, 6.05, 6.1].forEach(v => { el('line', { x1: 60, x2: 760, y1: PYa(v), y2: PYa(v), stroke: '#15213a' }, pen); const tx = el('text', { x: 10, y: PYa(v) + 5, fill: '#64748b', 'font-size': 14, 'font-family': 'monospace' }, pen); tx.textContent = v.toFixed(2); });
TRN.trials.forEach(([a]) => { const tx = el('text', { x: PXa(a), y: 226, fill: '#94a3b8', 'font-size': 15, 'text-anchor': 'middle', 'font-family': 'monospace' }, pen); tx.textContent = 'α ' + fmt(a); });
const penLine = el('polyline', { fill: 'none', stroke: '#f5b942', 'stroke-width': 2.5 }, pen);
const PENPTS = TRN.trials.map(([a, v], i) => { const c = el('circle', { cx: PXa(a), cy: PYa(v), r: 8, fill: i === TRN.trials.length - 1 ? '#4ade80' : '#f5b942', opacity: 0 }, pen);
  const tx = el('text', { x: PXa(a), y: PYa(v) - 16, fill: '#e6edf3', 'font-size': 17, 'text-anchor': 'middle', 'font-family': 'monospace', opacity: 0 }, pen); tx.textContent = v.toFixed(3); return [c, tx]; });
const penSel = document.createElement('span'); penSel.style.cssText = 'color:#4ade80;margin-left:14px;opacity:0'; penSel.textContent = '→ α 10,000 selected · top of range'; $('tr-pen').querySelector('.ph').appendChild(penSel);
$('tchips').innerHTML = [['parameters', fmt(TRN.tcn.parameters)], ['learning rate', TRN.job.learning_rate], ['batch', TRN.job.batch], ['patience', TRN.job.patience], ['max epochs', TRN.job.max_epochs],
  ['training', TRN.tcn.train_seconds + ' s'], ['seed', TRN.job.seed]].map(([k, v]) => `<span>${k} <b>${v}</b></span>`).join('');
const ls = $('losssvg'), LX = e => 70 + (e - 1) / 9 * 730, LY = v => 255 - (v - .2) / (.65 - .2) * 235;
[.2, .3, .4, .5, .6].forEach(v => { el('line', { x1: 60, x2: 810, y1: LY(v), y2: LY(v), stroke: '#15213a' }, ls); const tx = el('text', { x: 14, y: LY(v) + 5, fill: '#64748b', 'font-size': 14, 'font-family': 'monospace' }, ls); tx.textContent = v.toFixed(1); });
for (let e = 1; e <= 10; e++) { const tx = el('text', { x: LX(e), y: 290, fill: e > TRN.tcn.epochs_run ? '#334155' : '#94a3b8', 'font-size': 15, 'text-anchor': 'middle', 'font-family': 'monospace' }, ls); tx.textContent = e; }
el('rect', { x: LX(8.5), y: 15, width: LX(10) - LX(8.5) + 10, height: 245, fill: 'rgba(51,65,85,.18)' }, ls);
{ const tx = el('text', { x: LX(9.25) + 5, y: 40, fill: '#475569', 'font-size': 14, 'text-anchor': 'middle', 'font-family': 'monospace' }, ls); tx.textContent = 'not run'; }
const lTr = el('polyline', { fill: 'none', stroke: '#60a5fa', 'stroke-width': 3 }, ls), lVa = el('polyline', { fill: 'none', stroke: '#f5b942', 'stroke-width': 3 }, ls);
const H = TRN.tcn.history, BEST = H.reduce((b, h) => h.valid < b.valid ? h : b);
const bestG = el('g', { opacity: 0 }, ls); el('circle', { cx: LX(BEST.epoch), cy: LY(BEST.valid), r: 9, fill: 'none', stroke: '#4ade80', 'stroke-width': 3 }, bestG);
{ const tx = el('text', { x: LX(BEST.epoch), y: LY(BEST.valid) - 18, fill: '#4ade80', 'font-size': 16, 'text-anchor': 'middle', 'font-family': 'monospace' }, bestG); tx.textContent = `best validation · epoch ${BEST.epoch} · ${BEST.valid.toFixed(4)}`; }
const stopG = el('g', { opacity: 0 }, ls); el('line', { x1: LX(8), x2: LX(8), y1: 15, y2: 260, stroke: '#f87171', 'stroke-width': 2, 'stroke-dasharray': '6 5' }, stopG);
{ const tx = el('text', { x: LX(8) - 8, y: 150, fill: '#fca5a5', 'font-size': 16, 'text-anchor': 'end', 'font-family': 'monospace' }, stopG); tx.textContent = `early stop · ${TRN.job.patience} epochs without gain`; }
const pts = (key, upto) => { const out = []; for (let i = 0; i < H.length; i++) { const e = i + 1; if (e <= upto) out.push([LX(e), LY(H[i][key])]); else if (e - 1 < upto) { const f = upto - (e - 1), a = H[i - 1]; out.push([lerp(LX(e - 1), LX(e), f), lerp(LY(a[key]), LY(H[i][key]), f)]); break; } } return out.map(p => p.join(',')).join(' '); };
const t33 = recBy(33).data, t32 = recBy(32).data;
$('tr-ver').innerHTML = [['CODE EXECUTION', String(t33.max_abs_difference), `TCN reload max |Δ| · ${fmt(t33.rows)} rows · sha256 ${t33.model_sha256.slice(0, 8)}… ✓`],
  ['CODE EXECUTION', String(t32.reload_max_abs_difference), `ridge reload max |Δ| · weights ${t32.weights_sha256.slice(0, 8)}…`],
  ['RECORDED USAGE', TRN.tcn.train_seconds + ' s', `TCN training · predict ${TRN.tcn.predict_seconds} s · peak ${Math.round(TRN.usage.peak_training_rss_mb)} MB`],
  ['TRACE', '#31 → #33', 'family_comparison · tuning_verified · inference_verified']].map(([b, v, d]) => `<div class="tile"><span class="badge green">${b}</span><b>${v}</b><small>${d}</small></div>`).join('');

/* ---------------- data grid (exact region-hours) ---------------- */
const DN = ['15 Feb 2023', '15 Jul 2023', '15 Nov 2023'], RN = ['N', 'S', 'E', 'W', 'C'], CELLS = []; const GX = 640, GY = 190;
D.acq.days.forEach((day, di) => { const lab = document.createElement('div'); lab.className = 'dlab'; lab.style.left = GX + 'px'; lab.style.top = (GY + di * 215 - 36) + 'px';
  lab.textContent = `${DN[di]} · ${D.acq.present[day].length} region-hours`; $('grid').appendChild(lab);
  for (let r = 0; r < 5; r++) { const rl = document.createElement('div'); rl.className = 'dlab'; rl.style.cssText += `left:${GX - 34}px;top:${GY + di * 215 + r * 30}px;font-size:15px;color:#475569`; rl.textContent = RN[r]; $('grid').appendChild(rl);
    for (let h = 0; h < 24; h++) { const el = document.createElement('div'); el.className = 'dot'; el.style.left = (GX + h * 30) + 'px'; el.style.top = (GY + di * 215 + r * 30) + 'px';
      const has = D.acq.present[day].some(q => q[0] === r && q[1] === h), bad = D.acq.bad.some(q => q[0] === day && q[1] === r && q[2] === h);
      if (has) CELLS.push({ el, bad, k: CELLS.length }); else { el.style.background = 'none'; el.style.border = '1.5px dashed #2a3a55'; }
      $('grid').appendChild(el); } } });

/* ---------------- proof ---------------- */
const CH = [...D.trace.slice(0, 5), null, D.trace[D.trace.length - 1]];
CH.forEach((r, i) => { const b = document.createElement('div'); b.className = 'blk'; b.id = 'bk' + i; b.style.left = (110 + i * 245) + 'px';
  b.innerHTML = r ? `<div class="k">record ${r.seq + 1} · ${r.event}</div><div style="margin-top:12px">${r.hash.slice(0, 8)}</div><div class="k" style="margin-top:12px">links to previous</div>` : '<div style="font-size:44px;text-align:center;margin-top:28px">…</div>';
  if (!r) { b.style.border = 'none'; b.style.background = 'none'; } $('chain').appendChild(b);
  if (i) { const l = document.createElement('div'); l.className = 'lnk'; l.id = 'lk' + i; l.style.left = (110 + i * 245 - 55) + 'px'; $('chain').appendChild(l); } });
const VER = Object.fromEntries(D.verifications.map(v => [v.prediction_id, v]));
const PRED = D.ledger.map(p => [p.region[0].toUpperCase() + p.region.slice(1), p.value, VER[p.prediction_id].observed]);
const PX = v => 170 + v / 50 * 1150;
PRED.forEach((p, i) => { const r = document.createElement('div'); r.className = 'prow'; r.id = 'pr' + i; r.style.top = (470 + i * 58) + 'px';
  r.innerHTML = `<div class="lab">${p[0]}</div><div class="ax"></div><div class="abs" id="pe${i}" style="top:28px;height:3px;background:#475569"></div><div class="pd" id="pp${i}" style="background:#f5b942"></div><div class="pd" id="po${i}" style="background:#38e1d2"></div>`;
  $('prows').appendChild(r); });

/* ---------------- logo ---------------- */
'Empiraxis'.split('').forEach((ch, i) => { const s = document.createElement('span'); s.textContent = ch; s.id = 'lg' + i; $('logo').appendChild(s); });

/* ---------------- per-frame ---------------- */
const LOWER = { earth: ['SINGAPORE · 2015', 'The haze arrives.', 'REAL DATA · NASA FIRMS + NEA'], gate: ['HUMAN CONTROL', 'No model approves its own work.', 'REAL UI · RECORDED RUN'],
  data: ['SIGNED DATA', 'Fresh data. Honest disagreements.', 'REAL RUN RECORD'], no: ['NEGATIVE RESULTS', 'A defensible answer can be no.', 'REAL STUDIES · RECORDED'],
  proof: ['PROOF', 'Every step can be checked.', 'REAL TRACE + REAL LEDGER'], ablation: ['2015 HAZE STUDY', 'More data made it worse.', 'REAL RESULT · DETERMINISTIC'],
  next: ['NEXT · M5', 'Proposed research.', 'PLANNED · NO RESULTS YET'] };
let cursor = null;
function moveCursor(t, t0, from, to, hold) { if (t < t0 - .9 || t > t0 + hold) return; const p = ease((t - (t0 - .9)) / .8); cursor = [lerp(from[0], to[0], p), lerp(from[1], to[1], p)]; }

function frame(t) {
  cursor = null;
  const cur = TL.scenes.find(s => t >= s.start && t < s.end) || TL.scenes[TL.scenes.length - 1];
  const lo = LOWER[cur.id]; const lp = clamp((t - cur.start - .3) / .5) * clamp((cur.end - t) / .4);
  $('lower').style.opacity = lo ? lp : 0; $('tag').style.opacity = lo ? lp : 0;
  if (lo) { $('kicker').textContent = lo[0]; $('headline').textContent = lo[1]; $('tag').textContent = lo[2]; $('lower').style.transform = `translateY(${(1 - eout((t - cur.start - .3) / .5)) * 22}px)`; }

  // map visibility: earth → problem (dimming) and close/credits
  const pre = t < S.ablation.start ? 1 : t < S.product.start ? .55 * clamp(1 - (t - S.ablation.start) / (S.product.start - S.ablation.start)) : 0;
  const mapOn = Math.max(pre, vis('close', t, 1.2, .01), vis('credits', t, .01, 1) * .35);
  $('map').style.opacity = mapOn; $('mapshade').style.opacity = mapOn ? 1 : 0;
  $('hudgrid').style.opacity = clamp((t - S.problem.start - 4) / 2) * clamp((S.close.start + 1 - t) / 1);
  if (mapReady && mapOn > 0) { map.jumpTo(camEarth(t)); }
  // EARTH
  { const op = clamp((S.question.end - t) / .8) * (t >= 0 ? 1 : 0); $('L-earth').style.opacity = op;
    { const q = S.question, p = eout((t - q.start - .1) / .6); $('L-question').style.opacity = vis('question', t, .3, .6); $('chal').style.transform = `translateY(${(1 - p) * 30}px)`; }
    { const op2 = vis('ablation', t, .5, .6); $('L-ablation').style.opacity = op2; const l = LS('ablation')[0];
      [.0, .12, .42, .72].forEach((f, i) => { const k = AB[i][2], v = D.ablation.mae[k], p = eout((t - at(l, f)) / .8); $('af' + i).style.width = (v / 45 * 100 * p) + '%'; $('av' + i).textContent = (v * p).toFixed(2); });
      $('anote').style.opacity = clamp((t - at(l, .5)) / .5); } const e = LS('earth');
    if (mapReady) { const fp = clamp((t - e[0].start) / (e[0].dur + .5)); const day = Math.round(lerp(0, 68, ease(fp)));
      map.setFilter('firms', ['<=', ['get', 'd'], day]); map.setFilter('firms-glow', ['<=', ['get', 'd'], day]);
      const fo = clamp((t - e[0].start + .3) / .6) * (t < S.problem.start ? 1 : clamp(1 - (t - S.problem.start) / 3)) + vis('close', t, 1, .1) * .7 + vis('credits', t, .1, 1) * .5;
      map.setPaintProperty('firms', 'circle-opacity', .85 * fo); map.setPaintProperty('firms-glow', 'circle-opacity', .22 * fo);
      const bo = clamp((t - at(e[0], .45)) / .6) * (t < S.problem.start ? 1 : clamp(1 - (t - S.problem.start) / 2));
      map.setPaintProperty('boxes', 'line-opacity', .9 * bo);
      const no = clamp((t - e[1].start) / .6) * (t < S.product.start ? 1 : 0) + vis('close', t, 1, .1);
      map.setPaintProperty('nea', 'circle-opacity', no); map.setPaintProperty('nea-halo', 'circle-opacity', .5 * no * (.6 + .4 * Math.sin(t * 4)));
      const bx = D.boxes.map(b => b.extent);
      placeLabel('lbl-a', [bx[0].min_lon, bx[0].max_lat], bo * op, 4, -26); placeLabel('lbl-b', [bx[1].min_lon, bx[1].min_lat], bo * op, 4, 6); placeLabel('lbl-c', [bx[2].min_lon, bx[2].max_lat], bo * op, 4, -26);
      placeLabel('lbl-sg', [103.97, 1.42], no * op, 16, -12); }
    $('legend').style.opacity = clamp((t - e[0].start - .5) / .6);
    const pk = $('peak'); const pa = at(e[1], .45); pk.style.opacity = clamp((t - pa) / .4); pk.style.transform = `translateY(${(1 - eout((t - pa) / .5)) * 20}px)`; }
  // PROBLEM
  { $('L-problem').style.opacity = vis('problem', t, .4, .5); const l = LS('problem')[0];
    [.02, .5, .74].forEach((f, i) => { const a = at(l, f); const e = $('kt' + i); e.style.opacity = clamp((t - a) / .4); e.style.transform = `translateY(${(1 - eout((t - a) / .5)) * 30}px)`; }); }
  // PRODUCT
  { const s = S.product; $('L-product').style.opacity = vis('product', t, .3, .5);
    'Empiraxis'.split('').forEach((ch, i) => { const a = s.start + .2 + i * .07, p = eout((t - a) / .6), e = $('lg' + i);
      e.style.opacity = p; e.style.transform = `translateY(${(1 - p) * 60}px)`; e.style.color = i >= 4 ? '#38e1d2' : '#e6edf3'; e.style.textShadow = `0 0 ${40 * p}px rgba(56,225,210,${.35 * p})`; });
    $('logo-sub').style.opacity = clamp((t - s.start - 1.2) / .6); }
  // MISSION CONTROL chrome
  const mcOn = Math.max(vis('council', t, .8, .01), vis('train', t, .01, .01), vis('evidence', t, .01, .6)); $('L-mc').style.opacity = mcOn;
  const played = D.trace.filter((r, i) => REC_T[i] <= t); const lastT = played.length ? played[played.length - 1] : null;
  let state = 'requested'; played.forEach(r => { if (r.event === 'harness_transition') state = r.data.to; });
  STEPS.forEach((s, i) => { const el = $('sp-' + s); const k = STEPS.indexOf(state); el.className = 'step' + (i < k ? ' done' : i === k ? ' now' : ''); });
  // COUNCIL
  { const op = vis('council', t, .8, .6); $('L-council').style.opacity = op;
    if (op > 0) {
      let calls = 0, tok = 0, ok = 0, bad = 0; const rc = [0, 0, 0, 0], last = ['waiting', 'waiting', 'waiting', 'waiting'], used = new Set(), stamp = [null, null, null, null];
      played.forEach((r, j) => { const d = r.data, ri = roleIdx(d.role);
        if (r.event === 'model_turn') { calls++; tok += d.usage.prompt_tokens + d.usage.completion_tokens; if (ri >= 0) { rc[ri]++; (d.tool_calls || []).forEach(c => { used.add(ri + ':' + c.name); last[ri] = `#${r.seq} called ${c.name}`; }); } }
        if (r.event === 'proposal_reviewed') { d.valid ? ok++ : bad++; if (ri >= 0) stamp[ri] = [d.valid, REC_T[D.trace.indexOf(r)]]; }
        if (r.event === 'role_invocation' && d.status === 'verified' && ri >= 0) last[ri] = `#${r.seq} work verified by code`; });
      $('st-calls').textContent = calls; $('st-tok').textContent = fmt(tok); $('gate-ok').textContent = ok + ' valid'; $('gate-bad').textContent = bad + ' refused';
      ROLES.forEach((r, i) => { const recent = played.filter(x => x.event === 'model_turn' && x.data.role === r.key).map(x => REC_T[D.trace.indexOf(x)]);
        const on = recent.some(tt => t - tt < 2.6 && t >= tt); $('role' + i).classList.toggle('on', on); $('rc' + i).textContent = rc[i] + (rc[i] === 1 ? ' call' : ' calls');
        $('rl' + i).textContent = last[i]; $('role' + i).querySelectorAll('.tool').forEach(el => el.classList.toggle('used', used.has(i + ':' + el.dataset.tool)));
        const st = $('rs' + i); if (stamp[i] && t - stamp[i][1] < 2.4) { st.style.opacity = clamp((t - stamp[i][1]) / .2); st.className = 'stampx ' + (stamp[i][0] ? 'ok' : 'no'); st.textContent = stamp[i][0] ? 'VALID' : 'REFUSED'; } else st.style.opacity = 0;
        W[i].setAttribute('stroke', on ? '#38e1d2' : '#1f3a4a'); W[i].setAttribute('stroke-width', on ? 3 : 2); });
      // packet along the wire after each proposal review
      const pr = played.filter(r => r.event === 'proposal_reviewed' || r.event === 'model_turn').map(r => [r, REC_T[D.trace.indexOf(r)]]).filter(([, tt]) => t - tt < .9);
      if (pr.length) { const [r, tt] = pr[pr.length - 1]; const ri = roleIdx(r.data.role); if (ri >= 0) { const path = W[ri], L0 = path.getTotalLength(), q = path.getPointAtLength(L0 * clamp((t - tt) / .9)); pk.setAttribute('cx', q.x); pk.setAttribute('cy', q.y); pk.setAttribute('opacity', 1); } } else pk.setAttribute('opacity', 0);
      $('cn-gate').classList.toggle('on', pr.length > 0);
      const toolDone = n => played.some(r => r.event === 'tool_result' && r.data.name === n);
      $('tl-prep').classList.toggle('done', toolDone('prepare_data')); $('tl-train').classList.toggle('done', toolDone('train_models'));
      $('cn-tools').classList.toggle('on', played.some((r, j) => (r.event === 'tool_result' || r.event.endsWith('_verified') || r.event === 'family_comparison') && t - REC_T[D.trace.indexOf(r)] < 2));
      $('cn-eval').classList.toggle('on', state === 'evaluated'); $('cn-human').classList.toggle('on', state === 'forwarded');
      // feed: last 8 rows
      const host = $('feedrows'); const n = played.length; const show = ROWS.slice(Math.max(0, n - 8), n);
      if (host.dataset.n !== String(n)) { host.innerHTML = ''; show.forEach(el => host.appendChild(el)); host.dataset.n = n; }
      ROWS.forEach((el, i) => el.classList.toggle('now', i === n - 1));
      // recorded proposal popovers with a hover cursor
      let shown = false;
      for (const [seq, title, x, y, tgt] of POPS) { const tt = REC_T[seq]; moveCursor(t, tt + .2, [1000, 700], tgt, 3.4);
        if (t > tt + .3 && t < tt + 3.6) { const body = seq === 33 ? (() => { const d = recBy(33).data; return `model: ${d.model_id} (TCN)\nhash matches: ${d.model_sha256_matches}\nmax |Δ|: ${d.max_abs_difference} over ${fmt(d.rows)} rows\nsha256: ${d.model_sha256.slice(0, 16)}…`; })() : proposalText(seq);
          showPop(title, body, `recorded in trace · hash ${recBy(seq).hash}… · checked by code`, x, y, clamp((t - tt - .3) / .25) * clamp((tt + 3.6 - t) / .3)); shown = true; } }
      if (!shown && CAPTURE) showPop('', '', '', 0, 0, 0);
    } }
  // EVIDENCE
  { const op = vis('evidence', t, .6, .6); $('L-evidence').style.opacity = op;
    if (op > 0) { const e = E;
      ALL.forEach(([, m], i) => { const p = eout((t - e[0].start - .4 - i * .35) / .9); $('ba' + i).style.width = (CMP[m].mae / 6 * 100 * p) + '%'; $('bav' + i).textContent = (CMP[m].mae * p).toFixed(3); });
      ALL.forEach(([, m], i) => { const p = eout((t - e[1].start - .2 - i * .3) / .9); $('bb' + i).style.width = (CMP[m].above_55_mae / 35 * 100 * p) + '%'; const el = $('bbv' + i); if (el) el.textContent = (CMP[m].above_55_mae * p).toFixed(2); });
      $('d-note').style.opacity = clamp((t - at(e[0], .7)) / .4); $('n55').style.opacity = clamp((t - at(e[1], .55)) / .4);
      $('ch-55').style.opacity = clamp((t - e[1].start + .3) / .4);
      [...$('vtiles').children].forEach((c, i) => { const a = e[0].start + 2 + i * .3; c.style.opacity = clamp((t - a) / .4); });
      const ra = e[2].start; $('rec').style.opacity = clamp((t - ra) / .4); const nchar = Math.floor(REC.length * clamp((t - ra - .3) / (e[2].dur * .8)));
      $('rec-q').textContent = '“' + REC.slice(0, nchar) + (nchar < REC.length ? '▍' : '”');
      if (lastT) $('evtick').innerHTML = `LATEST TRACE RECORD &nbsp;<b style="color:#e6edf3">#${lastT.seq}</b> · ${lastT.actor} · <span style="color:#38e1d2">${lastT.event}</span> · ${detail(lastT)} · ${lastT.hash}`;
    } }
  // TRAIN
  { const op = vis('train', t, .5, .5); $('L-train').style.opacity = op;
    if (op > 0) { const [a, b, c] = TR;
      [0, 1, 2].forEach(i => { const s0 = a.start + .2 + i * .7; $('cv' + i).style.opacity = clamp((t - s0) / .4); });
      PENPTS.forEach(([cc, tx], i) => { const s0 = at(a, .5) + i * .35; const o = clamp((t - s0) / .25); cc.setAttribute('opacity', o); tx.setAttribute('opacity', o); });
      const np = clamp((t - at(a, .5)) / 1.75) * TRN.trials.length; penLine.setAttribute('points', TRN.trials.slice(0, Math.max(1, Math.ceil(np))).map(([x, v]) => PXa(x) + ',' + PYa(v)).join(' '));
      penSel.style.opacity = clamp((t - at(a, .82)) / .4); $('tr-arch').style.opacity = clamp((t - b.start + .6) / .5);
      const ep = 1 + 7 * clamp((t - b.start - .2) / (b.dur * .78)); lTr.setAttribute('points', pts('train', ep)); lVa.setAttribute('points', pts('valid', ep));
      $('tr-loss').style.opacity = clamp((t - b.start + .3) / .5); bestG.setAttribute('opacity', clamp((ep - BEST.epoch - .15) / .3)); stopG.setAttribute('opacity', clamp((t - at(b, .85)) / .3));
      [...$('tr-ver').children].forEach((x, i) => { const s0 = c.start + .2 + i * .35; x.style.opacity = clamp((t - s0) / .35); x.style.transform = `translateY(${(1 - eout((t - s0) / .4)) * 20}px)`; }); } }
  // NEXT (proposed research)
  { const op = vis('next', t, .5, .6); $('L-next').style.opacity = op; const l = LS('next')[0];
    $('nx-h').style.opacity = clamp((t - l.start + .3) / .4); [.1, .32, .5].forEach((f, i) => { const s0 = at(l, f); const e = $('nq' + i); e.style.opacity = clamp((t - s0) / .4); e.style.transform = `translateY(${(1 - eout((t - s0) / .5)) * 30}px)`; });
    $('nx-f').style.opacity = clamp((t - at(l, .72)) / .4); }
  // GATE (authentic UI capture)
  { const op = vis('gate', t, .5, .5); $('L-gate').style.opacity = op;
    if (op > 0) { const g = S.gate, p = ease((t - g.start) / (g.end - g.start)); const w = 980, x = 470, y = lerp(20, 250, p), sc = 1300 / w;
      const im = $('crimg'); im.style.width = (1920 * sc) + 'px'; im.style.transform = `translate(${-x * sc}px,${-y * sc}px)`;
      const b = META.cr.boxes['Human decision pending']; const hl = $('crhl'); hl.style.left = ((500 - x) * sc) + 'px'; hl.style.top = ((b[1] - 14 - y) * sc) + 'px'; hl.style.width = (920 * sc) + 'px'; hl.style.height = (60 * sc) + 'px';
      hl.style.opacity = clamp((t - at(G, .35)) / .3); $('lock').style.opacity = clamp((t - at(G, .55)) / .4); } }
  // DATA
  { const op = vis('data', t); $('L-data').style.opacity = op; const l = LS('data')[0];
    if (op > 0) { const sa = at(l, .22); $('signed').style.opacity = clamp((t - sa) / .2); $('signed').style.transform = `rotate(-6deg) scale(${1.6 - .6 * eout((t - sa) / .3)})`;
      $('limits').style.opacity = clamp((t - at(l, .38)) / .4); const fs = l.start + .3, fd = l.dur * .5, rb = t > at(l, .62);
      CELLS.forEach(c => { const on = t > fs + fd * c.k / CELLS.length; c.el.style.background = !on ? '#132038' : (c.bad && rb ? '#f87171' : '#22c55e'); c.el.style.boxShadow = c.bad && rb ? '0 0 14px #f87171' : 'none'; });
      $('c-ok').style.opacity = clamp((t - at(l, .55)) / .4); $('c-bad').style.opacity = clamp((t - at(l, .64)) / .4); } }
  // NO
  { const op = vis('no', t); $('L-no').style.opacity = op; const l = LS('no')[0];
    [.02, .32, .6].forEach((f, i) => { const a = at(l, f); const e = $('nc' + i); e.style.opacity = clamp((t - a) / .35); e.style.transform = `translateY(${(1 - eout((t - a) / .5)) * 40}px)`; }); }
  // PROOF
  { const op = vis('proof', t); $('L-proof').style.opacity = op; const l = LS('proof')[0], s = S.proof;
    CH.forEach((r, i) => { const a = s.start + .2 + i * .3; const b = $('bk' + i); b.style.opacity = clamp((t - a) / .3); b.style.transform = `translateY(${(1 - eout((t - a) / .4)) * 26}px)`;
      if (i) $('lk' + i).style.width = 55 * clamp((t - a + .1) / .25) + 'px'; });
    $('chainok').style.opacity = clamp((t - (s.start + 2.4)) / .4); $('pt').style.opacity = clamp((t - at(l, .4)) / .4); $('plegend').style.opacity = clamp((t - at(l, .75)) / .4);
    PRED.forEach((p, i) => { const a = at(l, .42) + i * .22; $('pr' + i).style.opacity = clamp((t - a) / .3);
      const pp = PX(p[1]), oo = PX(lerp(p[1], p[2], ease((t - a - .4) / .8))); $('pp' + i).style.left = (pp - 14) + 'px'; $('po' + i).style.left = (oo - 14) + 'px';
      $('po' + i).style.opacity = clamp((t - a - .3) / .3); const e = $('pe' + i); e.style.left = Math.min(pp, oo) + 'px'; e.style.width = Math.abs(pp - oo) + 'px'; }); }
  // CLOSE + CREDITS
  { const s = S.close; $('L-close').style.opacity = vis('close', t, .8, .6); const p = eout((t - s.start - .6) / 1);
    $('logo2').style.opacity = p; $('logo2').style.transform = `scale(${1.12 - .12 * p})`; $('tagl').style.opacity = clamp((t - LS('close')[0].start - .9) / .5);
    $('L-credits').style.opacity = vis('credits', t, .7, .8); }
  // cursor
  const c = $('cursor'); c.style.opacity = cursor ? 1 : 0; if (cursor) { c.style.left = cursor[0] + 'px'; c.style.top = cursor[1] + 'px'; }
}

/* ---------------- capture + interactive ---------------- */
let META = null;
fetch('img/meta.json').then(r => r.json()).then(m => { META = m; window.META = m; });
window.seek = async (t) => {
  while (!META) await new Promise(r => setTimeout(r, 50));
  frame(t);
  if (parseFloat($('map').style.opacity || 0) > 0) { while (!mapReady) await new Promise(r => setTimeout(r, 50)); map.jumpTo(camEarth(t)); frame(t);
    await new Promise(res => { if (map.loaded() && map.areTilesLoaded()) { map.once('render', () => res()); map.triggerRepaint(); } else map.once('idle', () => res()); }); }
  return true;
};
if (!CAPTURE) {
  const st = $('stage'); const fit = () => { const k = Math.min(innerWidth / 1920, (innerHeight - 44) / 1080); st.style.transform = `scale(${k})`; }; fit(); addEventListener('resize', fit);
  const au = $('audio'); let playing = false, t0 = 0, base = 0;
  const now = () => playing ? (au.readyState > 2 && !au.paused ? au.currentTime : base + (performance.now() - t0) / 1000) : base;
  $('play').onclick = () => { playing = !playing; $('play').textContent = playing ? '❚❚' : '▶'; if (playing) { t0 = performance.now(); au.currentTime = base; au.play().catch(() => {}); } else { base = now(); au.pause(); } };
  $('scrub').oninput = e => { base = e.target.value / 1000 * TL.total; au.currentTime = base; t0 = performance.now(); };
  const loop = () => { if (META) { const t = Math.min(now(), TL.total); frame(t); $('scrub').value = t / TL.total * 1000; $('clock').textContent = `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`; if (t >= TL.total) playing = false; } requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
  document.querySelectorAll('.tool').forEach(el => { el.title = `${el.dataset.tool}: ` + (D.trace.filter(r => r.event === 'model_turn' && (r.data.tool_calls || []).some(c => c.name === el.dataset.tool)).map(r => `trace #${r.seq} at ${r.ts.slice(11, 19)}`).join(', ') || 'not called in this run'); });
}
