/* The Edge website — race tabs: Speed Map (track journey), Form Worm, Track & Barriers.
 * Uses globals from index.html and features.js.
 */

// ---------------------------------------------------------------- track dimensions
// Circumference and home straight (metres) as published in track profiles
// (horise.com track pages, Nov 2026; Flemington from the VRC). firstTurn holds
// published run-to-the-first-turn facts by distance; 0 = starts on the turn,
// 'straight' = straight course (no turn). Anything else is estimated from the
// circumference and straight and labelled as an estimate.
const TRACKS = {
  'Ballarat':        { circ: 1900, straight: 450, src: 'horise.com' },
  'Bendigo':         { circ: 1995, straight: 400, src: 'horise.com' },
  'Caulfield':       { circ: 2080, straight: 367, src: 'horise.com', firstTurn: { 1800: 400 } },
  'Cranbourne':      { circ: 1700, straight: 300, src: 'horise.com' },
  'Echuca':          { circ: 1811, straight: 350, src: 'horise.com' },
  'Flemington':      { circ: 2312, straight: 450, src: 'VRC', firstTurn: { 1000: 'straight', 1100: 'straight', 1200: 'straight' } },
  'Geelong':         { circ: 2043, straight: 400, src: 'horise.com' },
  'Hamilton':        { circ: 2000, straight: 400, src: 'horise.com' },
  'Kilmore':         { circ: 1735, straight: 320, src: 'horise.com' },
  'Mildura':         { circ: 1765, straight: 390, src: 'horise.com' },
  'Moe':             { circ: 1740, straight: 300, src: 'horise.com' },
  'Moonee Valley':   { circ: 1805, straight: 173, src: 'horise.com', firstTurn: { 1600: 0, 2040: 200 } },
  'Mornington':      { circ: 1800, straight: 210, src: 'horise.com' },
  'Sale':            { circ: 2040, straight: 400, src: 'horise.com' },
  'Sandown-Hillside':{ circ: 2087, straight: 491, src: 'horise.com' },
  'Seymour':         { circ: 1800, straight: 380, src: 'horise.com' },
  'Stawell':         { circ: 1600, straight: 250, src: 'horise.com' },
  'Swan Hill':       { circ: 1900, straight: 475, src: 'horise.com' },
  'Wangaratta':      { circ: 1730, straight: 350, src: 'horise.com' },
  'Warrnambool':     { circ: 2100, straight: 350, src: 'horise.com' },
};
const RUN_PAST_POST = 50;          // straight left after the post before the first bend (assumed)
const TURN_OVERRIDE_KEY = 'edge_first_turn_v1';

function turnOverrides() { try { return JSON.parse(localStorage.getItem(TURN_OVERRIDE_KEY) || '{}'); } catch (e) { return {}; } }
function saveTurnOverride(track, dist, metres) {
  const o = turnOverrides(); const k = `${track}|${dist}`;
  if (metres === '' || metres === null) delete o[k]; else o[k] = Number(metres);
  try { localStorage.setItem(TURN_OVERRIDE_KEY, JSON.stringify(o)); } catch (e) {}
}

// Oval model: two equal straights joined by two semicircular bends.
function trackGeom(trackName, distance) {
  const t = TRACKS[trackName];
  if (!t) return null;
  const H = t.straight, S = H + RUN_PAST_POST;
  let R = (t.circ - 2 * S) / (2 * Math.PI);
  if (R < 50) R = 50;
  const B = Math.PI * R, C = 2 * S + 2 * B;
  const g = { t, H, S, R, B, C, distance, track: trackName };
  g.start = ((distance % C) + C) % C;
  g.laps = Math.floor(distance / C);
  // Segments, measured back from the post: home straight, home turn, back straight,
  // the turn out of the straight, the run past the post.
  const p = g.start;
  const segs = [[0, H, 'the home straight'], [H, H + B, 'the home turn'], [H + B, H + B + S, 'the back straight'],
                [H + B + S, H + 2 * B + S, 'the turn out of the straight'], [H + 2 * B + S, C, 'the straight past the post']];
  const seg = segs.find(x => p >= x[0] && p < x[1]) || segs[0];
  g.startWhere = seg[2];
  let est;
  if (seg === segs[0]) est = g.laps > 0 ? p + RUN_PAST_POST : 'straight';   // a lap race starting in the straight runs past the post first
  else if (seg === segs[1] || seg === segs[3]) est = 0;
  else if (seg === segs[2]) est = p - (H + B);
  else est = p - (H + 2 * B + S);
  const pub = t.firstTurn && t.firstTurn[distance] !== undefined ? t.firstTurn[distance] : undefined;
  const mine = turnOverrides()[`${trackName}|${distance}`];
  if (mine !== undefined) { g.firstTurn = mine; g.turnSrc = 'yours'; }
  else if (pub !== undefined) { g.firstTurn = pub; g.turnSrc = 'published'; }
  else { g.firstTurn = est; g.turnSrc = 'estimate'; }
  g.estimate = est;
  return g;
}

// Point on the oval, p metres back from the post, o metres out from the rail.
function ovalPoint(g, p, o) {
  const { H, S, R, B, C } = g;
  p = ((p % C) + C) % C;
  const r = R + o;
  if (p < H) return [H - p, R + r];                          // home straight (x from the left bend end)
  if (p < H + B) { const f = (p - H) / R; return [-r * Math.sin(f), R + r * Math.cos(f)]; }
  if (p < H + B + S) return [p - H - B, R - r];             // back straight, heading right when read backwards
  if (p < H + 2 * B + S) { const f = (p - H - B - S) / R; return [S + r * Math.sin(f), R - r * Math.cos(f)]; }
  return [S - (p - H - 2 * B - S), R + r];                   // past the post
}

// ---------------------------------------------------------------- tab switching
function setRaceTab(tab) {
  S.raceTab = tab;
  document.querySelectorAll('#raceTabs .rt-btn').forEach(b => b.classList.toggle('active', b.dataset.rt === tab));
  ['odds', 'map', 'worm', 'track'].forEach(t => document.getElementById('rt-' + t).classList.toggle('hidden', t !== tab));
  const race = S.races.find(r => r.race_id === S.view);
  if (race) renderRaceTab(race);
}
function renderRaceTab(race) {
  const tab = S.raceTab || 'odds';
  document.querySelectorAll('#raceTabs .rt-btn').forEach(b => b.classList.toggle('active', b.dataset.rt === tab));
  ['odds', 'map', 'worm', 'track'].forEach(t => document.getElementById('rt-' + t).classList.toggle('hidden', t !== tab));
  if (tab === 'map') { renderTrackProfile(race); renderJourney(race); renderSpeedMap(race); renderJourneyTable(race); }
  if (tab === 'worm') renderWorm(race);
  if (tab === 'track') renderTrackStats(race);
}

// ---------------------------------------------------------------- speed map tab
function railMetres(rail) { const m = String(rail || '').match(/([+-]?\d+(\.\d+)?)\s*m/i); return m ? Math.abs(parseFloat(m[1])) : 0; }

function renderTrackProfile(race) {
  const m = S.meeting || {}, g = trackGeom(m.track, race.distance);
  const box = document.getElementById('trackProfile');
  const fact = (k, v, tip = '') => `<div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3" title="${esc(tip)}"><div class="text-[10px] text-gray-500 uppercase tracking-widest">${k}</div><div class="text-white font-bold text-sm mt-0.5">${v}</div></div>`;
  let turn = '–', turnTip = '';
  if (g) {
    if (g.firstTurn === 'straight') turn = 'No turn: straight course';
    else if (g.firstTurn === 0) turn = 'Starts on the turn';
    else turn = `${g.turnSrc === 'estimate' ? '≈ ' : ''}${Math.round(g.firstTurn / 10) * 10}m`;
    turnTip = g.turnSrc === 'estimate' ? 'Estimated from the circumference and home straight (two equal straights, two even bends). Real tracks vary; correct it below if your race book map says otherwise.'
      : g.turnSrc === 'published' ? 'From the published track profile.' : 'Your correction (saved on this device).';
  }
  const rm = railMetres(m.rail);
  box.innerHTML = `
    <div class="bg-[#11151d] border border-[#1e2638] rounded-xl p-5 shadow-2xl">
      <div class="flex flex-wrap justify-between gap-2 mb-3">
        <h2 class="text-white font-black text-lg">${esc(m.track || '')} ${race.distance}m: track profile</h2>
        ${g ? `<span class="pill ${g.turnSrc === 'estimate' ? 'sect-yellow' : 'sect-green'} text-[11px] py-1">first turn: ${g.turnSrc}</span>` : ''}
      </div>
      <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        ${fact('Run to the first turn', turn, turnTip)}
        ${fact('Start', g ? (g.firstTurn === 'straight' ? 'straight course' : 'on ' + g.startWhere) + (g.laps ? ` (+${g.laps} lap)` : '') : '–', g && g.turnSrc === 'estimate' ? 'Estimated position of the barriers on the circuit.' : '')}
        ${fact('Circumference', g ? g.t.circ + 'm' : '–', g ? 'Source: ' + g.t.src : '')}
        ${fact('Home straight', g ? g.t.straight + 'm' : '–', g ? 'Source: ' + g.t.src : '')}
        ${fact('Rail', esc(m.rail || '–') + (rm ? ` <span class="text-amber-300 text-xs">(+${rm}m: inside gates lose some edge, runners race a little further)</span>` : ''))}
        ${fact('Going', esc(m.going || '–'))}
      </div>
      ${g ? `<div class="flex flex-wrap items-center gap-2 mt-3 text-[11px] text-gray-400">
        <span>Know the real run to the first turn from the race book map?</span>
        <input id="turnFix" type="number" class="syn-input px-2 py-1 w-24 text-xs" placeholder="metres" value="${g.turnSrc === 'yours' ? g.firstTurn : ''}">
        <button class="text-[#ff6600] font-bold" onclick="saveTurnOverride('${esc(m.track)}', ${race.distance}, document.getElementById('turnFix').value); renderRaceTab(S.races.find(r=>r.race_id===S.view))">Save</button>
        <span class="text-gray-600">(0 = starts on the turn, blank = back to ${g.turnSrc === 'published' ? 'published' : 'estimate'})</span>
      </div>` : `<p class="text-[11px] text-gray-500 mt-3">No published dimensions for ${esc(m.track || 'this track')} yet, so the track drawing and first-turn distance are off. Send me the circumference and straight and I'll add it.</p>`}
    </div>`;
}

const JOURNEY_STEPS = [
  { id: 'jump', label: 'The jump' }, { id: 'turn', label: 'First turn' },
  { id: 'settled', label: 'Settled (home turn)' }, { id: 'finish', label: 'The finish (our book)' },
];

function journeyRows(race) {
  const rows = (S.runners[race.race_id] || []).filter(r => !r._scratched);
  const book = byBook(rows);
  const finishRank = new Map(book.map((r, i) => [r.horse_name, i + 1]));
  const settled = rows.slice().sort((a, b) => (a.settle_rank || 99) - (b.settle_rank || 99));
  const settleRank = new Map(settled.map((r, i) => [r.horse_name, i + 1]));
  const laneOf = r => Math.max(0, ['Rail (Fence)', 'One-Off', '3-Wide', '4-Wide'].indexOf(r.map_lane));
  return rows.map(r => ({ r, bar: r.barrier || 1, settle: settleRank.get(r.horse_name), lane: laneOf(r), fin: finishRank.get(r.horse_name) }));
}

function journeyPositions(g, race, step, jr) {
  const n = jr.length, gap = 26, laneW = 12;       // metres between runners (exaggerated), metres per lane
  const turnP = g.firstTurn === 'straight' ? 0 : g.start - (g.firstTurn === 0 ? 30 : Math.max(0, g.firstTurn) + 40);
  const out = {};
  jr.forEach(x => {
    let p, o;
    if (step === 'jump') { p = g.start; o = (Math.min(x.bar, 16) - 1) * 3.2 + 2; }
    else if (step === 'turn') { p = turnP + (x.settle - 1) * gap; o = x.lane * laneW + 2; }
    else if (step === 'settled') { p = g.H + g.B * 0.55 + (x.settle - 1) * gap; o = x.lane * laneW + 2; }
    else { p = (x.fin - 1) * gap * 0.8; o = ((x.fin - 1) % 3) * laneW + 2; }
    out[x.r.horse_name] = ovalPoint(g, p, o);
  });
  return out;
}

function renderJourney(race) {
  const m = S.meeting || {}, g = trackGeom(m.track, race.distance);
  const box = document.getElementById('journeyCard');
  if (!g || g.firstTurn === 'straight') { box.innerHTML = ''; return; }
  const jr = journeyRows(race);
  const W = 900, Hh = 430, pad = 60;
  const sx = (W - 2 * pad) / (g.S + 2 * g.R + 40), sy = (Hh - 2 * pad) / (2 * g.R + 40);
  const sc = Math.min(sx, sy);
  const ox = W / 2 - (g.S / 2) * sc, oy = Hh / 2 - g.R * sc;
  const P = ([x, y]) => [ox + x * sc, oy + y * sc];
  const trackPath = (o) => { const pts = []; for (let p = 0; p <= g.C; p += g.C / 240) pts.push(P(ovalPoint(g, p, o))); return 'M' + pts.map(q => q[0].toFixed(1) + ',' + q[1].toFixed(1)).join(' L') + ' Z'; };
  const post = P(ovalPoint(g, 0, -6)), post2 = P(ovalPoint(g, 0, 46));
  const st = P(ovalPoint(g, g.start, -6)), st2 = P(ovalPoint(g, g.start, 52));
  const ftP = g.firstTurn === 0 ? null : g.start - g.firstTurn;
  const book = byBook(jr.map(x => x.r));
  const top = book[0] && book[0].horse_name;
  const step = S.journeyStep || 'turn';
  const pos = journeyPositions(g, race, step, jr);
  let svg = `<svg viewBox="0 0 ${W} ${Hh}" class="w-full" style="max-height:460px">
    <path d="${trackPath(-4)}" fill="none" stroke="#e5e7eb" stroke-width="2.5" opacity=".85"/>
    <path d="${trackPath(48)}" fill="none" stroke="#374151" stroke-width="1.5"/>
    <path d="${trackPath(22)}" fill="none" stroke="#14532d" stroke-width="${48 * sc}" opacity=".35"/>
    <line x1="${post[0]}" y1="${post[1]}" x2="${post2[0]}" y2="${post2[1]}" stroke="#ff6600" stroke-width="3"/>
    <text x="${post2[0]}" y="${post2[1] + 16}" fill="#ff6600" font-size="12" font-weight="800" text-anchor="middle">POST</text>
    <line x1="${st[0]}" y1="${st[1]}" x2="${st2[0]}" y2="${st2[1]}" stroke="#10b981" stroke-width="3" stroke-dasharray="4 3"/>
    <text x="${st2[0]}" y="${st2[1] + (st2[1] > oy + g.R * sc ? 16 : -8)}" fill="#10b981" font-size="12" font-weight="800" text-anchor="middle">START ${race.distance}m</text>`;
  if (ftP !== null) {
    const a = P(ovalPoint(g, ftP, -6)), b = P(ovalPoint(g, ftP, 48));
    svg += `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="#f59e0b" stroke-width="2" stroke-dasharray="2 3"/>
      <text x="${(a[0] + b[0]) / 2}" y="${Math.min(a[1], b[1]) - 8}" fill="#f59e0b" font-size="11" font-weight="700" text-anchor="middle">1st turn ${g.turnSrc === 'estimate' ? '≈' : ''}${Math.round(g.firstTurn / 10) * 10}m</text>`;
  }
  const ht = P(ovalPoint(g, g.H, -10));
  svg += `<text x="${ht[0] + 6}" y="${ht[1] - 6}" fill="#6b7280" font-size="10">home turn</text>`;
  svg += `<text x="${ox + g.S * sc / 2}" y="${oy + g.R * sc + 4}" fill="#4b5563" font-size="11" text-anchor="middle">← racing anti-clockwise</text>`;
  jr.slice().sort((a, b) => (b.r.horse_name === top) - (a.r.horse_name === top)).reverse().forEach(x => {
    const [px, py] = P(pos[x.r.horse_name]);
    const cls = x.r.horse_name === top ? '#ff6600' : x.r._value ? '#10b981' : '#2a3348';
    svg += `<g class="jr-horse" data-h="${esc(x.r.horse_name)}" style="transform: translate(${px.toFixed(1)}px, ${py.toFixed(1)}px)">
      <title>${esc(x.r.horse_name)} · barrier ${x.bar} · settles ${x.settle} (${esc(zoneShort(x.r.map_zone) || '')}, ${esc((x.r.map_lane || '').toLowerCase())}) · our book ${x.fin}</title>
      <circle r="10" fill="${cls}" stroke="${x.r.horse_name === top ? '#ffa366' : '#9ca3af'}" stroke-width="1.5"/>
      <text y="4" fill="${x.r.horse_name === top ? '#000' : '#fff'}" font-size="10" font-weight="800" text-anchor="middle" font-family="JetBrains Mono, monospace">${x.r.saddlecloth ?? ''}</text></g>`;
  });
  svg += '</svg>';
  const btns = JOURNEY_STEPS.map(s => `<button onclick="journeyStep('${s.id}')" class="rt-btn ${s.id === step ? 'active' : ''}" style="font-size:11px;padding:6px 12px">${s.label}</button>`).join('');
  box.innerHTML = `
    <div class="bg-[#11151d] border border-[#1e2638] rounded-xl p-5 shadow-2xl">
      <div class="flex flex-wrap justify-between items-center gap-2 mb-2">
        <h2 class="text-white font-black text-lg">Race journey</h2>
        <div class="flex flex-wrap gap-2">${btns}<button onclick="playJourney()" class="rt-btn" style="font-size:11px;padding:6px 12px">▶ Play</button></div>
      </div>
      <div class="overflow-x-auto"><div style="min-width:620px">${svg}</div></div>
      <div class="mt-2"><div class="text-[10px] text-gray-500 uppercase tracking-widest mb-1">From the gates: barrier 1 on the fence, out to the widest (colour = early speed)</div>
        <div class="flex flex-wrap gap-1">${jr.slice().sort((a, b) => a.bar - b.bar).map(x => { const es = x.r.early_speed; const c = es >= 7 ? '#ff6600' : es >= 5 ? '#f59e0b' : es >= 3 ? '#6b7280' : '#374151';
          return `<div class="px-2 py-1 rounded text-[11px] font-mono-numbers" style="background:#0d1117;border:1px solid ${c}" title="Early speed ${num(es, 1)}/10 · settles ${ordinal(x.settle)}"><span class="text-gray-500">b${x.bar}</span> <b class="text-white">${x.r.saddlecloth ?? ''}</b> <span class="text-gray-300">${esc(shortName(x.r.horse_name))}</span></div>`; }).join('')}</div></div>
      <p class="text-[10px] text-gray-500 mt-1">Where every runner is at each stage: barriers at the jump, its expected spot at the first turn and settled down the back, then finishing in our book order. Track drawn from its circumference and straight; gaps between runners are stretched so the numbers are readable. Orange = top of our book, green = value flag. Hover a horse for details.</p>
    </div>`;
}
function journeyStep(step) {
  S.journeyStep = step;
  const race = S.races.find(r => r.race_id === S.view); const m = S.meeting || {};
  const g = trackGeom(m.track, race.distance); if (!g) return;
  const jr = journeyRows(race), pos = journeyPositions(g, race, step, jr);
  const svg = document.querySelector('#journeyCard svg');
  if (!svg) { renderJourney(race); return; }
  const vb = svg.viewBox.baseVal, W = vb.width, Hh = vb.height, pad = 60;
  const sc = Math.min((W - 2 * pad) / (g.S + 2 * g.R + 40), (Hh - 2 * pad) / (2 * g.R + 40));
  const ox = W / 2 - (g.S / 2) * sc, oy = Hh / 2 - g.R * sc;
  svg.querySelectorAll('g.jr-horse').forEach(el => {
    const p = pos[el.dataset.h]; if (!p) return;
    el.style.transform = `translate(${(ox + p[0] * sc).toFixed(1)}px, ${(oy + p[1] * sc).toFixed(1)}px)`;
  });
  document.querySelectorAll('#journeyCard .rt-btn').forEach((b, i) => { if (i < JOURNEY_STEPS.length) b.classList.toggle('active', JOURNEY_STEPS[i].id === step); });
}
function playJourney() {
  let i = 0; journeyStep('jump');
  const tick = () => { i++; if (i < JOURNEY_STEPS.length) { journeyStep(JOURNEY_STEPS[i].id); setTimeout(tick, 1400); } };
  setTimeout(tick, 1100);
}

function renderJourneyTable(race) {
  const jr = journeyRows(race).sort((a, b) => a.settle - b.settle);
  const g = trackGeom((S.meeting || {}).track, race.distance);
  const tip = TAG_FLAG;
  document.getElementById('journeyTable').innerHTML = `
    <div class="bg-[#11151d] border border-[#1e2638] rounded-xl overflow-hidden shadow-2xl">
      <div class="p-4 border-b border-[#1e2638] bg-[#0d1117]"><h2 class="text-white font-black text-lg">Where every horse gets to</h2></div>
      <div class="overflow-x-auto"><table class="w-full text-left font-mono-numbers text-xs">
        <thead class="bg-[#0d1117] text-gray-500 uppercase text-[10px] tracking-wider"><tr>
          <th class="p-3 font-sans">Horse</th><th class="p-3">Barrier</th><th class="p-3" title="0-10 from its real early positions">Early speed</th>
          <th class="p-3">${g && g.firstTurn !== 'straight' ? 'At the first turn' : 'Early'}</th><th class="p-3">Settles</th><th class="p-3">Run</th><th class="p-3 text-[#ffa366]">Finish (our book)</th><th class="p-3">True</th></tr></thead>
        <tbody class="divide-y divide-[#1e2638]">${jr.map(x => {
          const f = tip[x.r.map_tag];
          return `<tr>
            <td class="p-3 font-sans text-white font-bold">${x.r.saddlecloth ?? ''}. ${esc(x.r.horse_name)}</td>
            <td class="p-3">${x.bar}</td>
            <td class="p-3">${num(x.r.early_speed, 1)}</td>
            <td class="p-3">${ordinal(x.settle)}, ${esc((x.r.map_lane || '–').toLowerCase())}</td>
            <td class="p-3">${esc(zoneShort(x.r.map_zone) || '–')}</td>
            <td class="p-3 font-sans text-[11px] ${f ? (x.r.map_tag === 'Box Seat' ? 'text-emerald-400' : 'text-amber-300') : 'text-gray-500'}">${f ? esc(f.why) : 'clear run'}</td>
            <td class="p-3 text-[#ffa366] font-bold">${ordinal(x.fin)}</td>
            <td class="p-3">${money(x.r._fair)}</td></tr>`; }).join('')}</tbody>
      </table></div>
      <p class="p-3 text-[10px] text-gray-500">"At the first turn" and "Settles" come from each horse's real early positions in its recent runs. "Finish" is our book order (most likely winner first), not a guarantee.</p>
    </div>`;
}
const ordinal = n => !n ? '–' : n + (['th', 'st', 'nd', 'rd'][(n % 100 > 10 && n % 100 < 14) ? 0 : (n % 10 < 4 ? n % 10 : 0)]);

// ---------------------------------------------------------------- form worm
const WORM_COLOURS = ['#ff6600', '#10b981', '#38bdf8', '#f472b6', '#facc15', '#a78bfa', '#fb7185', '#34d399', '#60a5fa', '#f97316', '#e879f9', '#22d3ee', '#a3e635', '#fbbf24', '#c084fc', '#4ade80'];

function renderWorm(race) {
  const box = document.getElementById('rt-worm');
  const rows = byBook((S.runners[race.race_id] || []).filter(r => !r._scratched));
  if (!S.wormPick || S.wormPick.race !== race.race_id) S.wormPick = { race: race.race_id, on: new Set(rows.slice(0, 4).map(r => r.horse_name)) };
  const on = S.wormPick.on;
  const N = 8;
  const series = rows.map((r, i) => {
    const runs = parseJSON(r.last_runs, []).slice(0, N);
    const pts = runs.map((x, k) => ({ k, v: x.rating, x })).filter(q => q.v);
    return { r, i, col: WORM_COLOURS[i % WORM_COLOURS.length], pts };
  });
  const vals = series.flatMap(s => s.pts.map(q => q.v)).concat(race.form_par ? [race.form_par] : []);
  const W = 960, H = 420, pl = 44, pr = 150, pt = 20, pb = 34;
  if (!vals.length) { box.innerHTML = '<div class="bg-[#11151d] border border-[#1e2638] rounded-xl p-8 text-gray-500">No rated runs in this field yet.</div>'; return; }
  const lo = Math.floor(Math.min(...vals) - 2), hi = Math.ceil(Math.max(...vals) + 2);
  const X = k => pl + (N - 1 - k) * (W - pl - pr) / (N - 1), Y = v => pt + (hi - v) / (hi - lo) * (H - pt - pb);
  let svg = `<svg viewBox="0 0 ${W} ${H}" class="w-full">`;
  for (let v = Math.ceil(lo / 5) * 5; v <= hi; v += 5) svg += `<line x1="${pl}" x2="${W - pr}" y1="${Y(v)}" y2="${Y(v)}" stroke="#1e2638"/><text x="${pl - 6}" y="${Y(v) + 3}" fill="#6b7280" font-size="10" text-anchor="end">${v}</text>`;
  for (let k = 0; k < N; k++) svg += `<text x="${X(k)}" y="${H - 12}" fill="#6b7280" font-size="10" text-anchor="middle">${k === 0 ? 'last start' : k + 1 + ' back'}</text>`;
  if (race.form_par) svg += `<line x1="${pl}" x2="${W - pr}" y1="${Y(race.form_par)}" y2="${Y(race.form_par)}" stroke="#ff6600" stroke-dasharray="5 4" opacity=".8"/><text x="${pl + 4}" y="${Y(race.form_par) - 5}" fill="#ff6600" font-size="10">winning par for today's race ${num(race.form_par, 1)}</text>`;
  const draw = (s, hiOn) => {
    if (s.pts.length < 1) return '';
    const d = s.pts.map((q, j) => `${j ? 'L' : 'M'}${X(q.k).toFixed(1)},${Y(q.v).toFixed(1)}`).join(' ');
    let out = `<path d="${d}" fill="none" stroke="${hiOn ? s.col : '#4b5563'}" stroke-width="${hiOn ? 3 : 1.2}" opacity="${hiOn ? 1 : .45}"><title>${esc(s.r.horse_name)}</title></path>`;
    s.pts.forEach(q => {
      out += `<circle cx="${X(q.k)}" cy="${Y(q.v)}" r="${hiOn ? 4.5 : 2.5}" fill="${hiOn ? (q.x.pos === 1 ? '#fff' : s.col) : '#4b5563'}" stroke="${hiOn ? s.col : 'none'}" stroke-width="2" opacity="${hiOn ? 1 : .5}">
        <title>${esc(s.r.horse_name)}: ${esc(q.x.date || '')} ${esc(q.x.track || '')} ${q.x.dist ?? ''}m · ${q.x.pos ?? ''}/${q.x.field ?? ''} · rating ${num(q.v, 1)}${q.x.prep ? ' · run ' + q.x.prep + ' of prep' : ''}</title></circle>`;
    });
    if (hiOn) { const l = s.pts[0]; labels.push({ x: X(l.k) + 8, y: Y(l.v) + 4, col: s.col, t: `${s.r.saddlecloth ?? ''}. ${shortName(s.r.horse_name)}` }); }
    return out;
  };
  const labels = [];
  series.filter(s => !on.has(s.r.horse_name)).forEach(s => svg += draw(s, false));
  series.filter(s => on.has(s.r.horse_name)).forEach(s => svg += draw(s, true));
  labels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < labels.length; i++) if (labels[i].y - labels[i - 1].y < 13) labels[i].y = labels[i - 1].y + 13;
  labels.forEach(l => { svg += `<text x="${l.x}" y="${l.y}" fill="${l.col}" font-size="11" font-weight="800">${esc(l.t)}</text>`; });
  svg += '</svg>';
  const chips = series.map(s => `<button onclick="wormToggle(${JSON.stringify(s.r.horse_name).replace(/"/g, '&quot;')})" class="pill py-1 text-[11px] mr-1 mb-1" style="border:1px solid ${on.has(s.r.horse_name) ? s.col : '#1e2638'};color:${on.has(s.r.horse_name) ? s.col : '#9ca3af'};background:#0d1117">${s.r.saddlecloth ?? ''}. ${esc(s.r.horse_name)} <span class="text-gray-500">${money(s.r._fair)}</span></button>`).join('');
  const trend = series.filter(s => s.pts.length >= 3).map(s => {
    const a = s.pts.slice(0, 3).map(q => q.v), b = s.pts.slice(3, 6).map(q => q.v);
    const avg = xs => xs.reduce((x, y) => x + y, 0) / xs.length;
    return { s, last3: avg(a), d: b.length ? avg(a) - avg(b) : null, best: Math.max(...s.pts.map(q => q.v)) };
  });
  const rising = trend.filter(t => t.d !== null && t.d >= 2).sort((a, b) => b.d - a.d).slice(0, 4);
  const atPar = trend.filter(t => race.form_par && t.last3 >= race.form_par).sort((a, b) => b.last3 - a.last3);
  box.innerHTML = `
    <div class="bg-[#11151d] border border-[#1e2638] rounded-xl p-5 shadow-2xl">
      <div class="flex flex-wrap justify-between gap-2 mb-1">
        <h2 class="text-white font-black text-lg">Form Worm: every runner's last ${N} ratings</h2>
        <div class="text-[11px] text-gray-500">Tap horses to compare · top four in our book shown first</div>
      </div>
      <div class="mb-2">${chips}<button onclick="wormAll(true)" class="pill py-1 text-[11px] sect-yellow mr-1">All</button><button onclick="wormAll(false)" class="pill py-1 text-[11px] sect-red">None</button></div>
      <div class="overflow-x-auto"><div style="min-width:640px">${svg}</div></div>
      <p class="text-[10px] text-gray-500">Form King rating for each run (higher is better), read left to right towards today. White dot = won. Dashed orange = the rating that usually wins today's class at this level of track.</p>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3 text-xs">
        <div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3"><div class="text-[10px] text-gray-500 uppercase tracking-widest mb-1">On the rise (last 3 vs the 3 before)</div>
          ${rising.map(t => `<div><b class="text-white">${esc(t.s.r.horse_name)}</b> <span class="text-emerald-400">+${num(t.d, 1)}</span> <span class="text-gray-500">avg ${num(t.last3, 1)}</span></div>`).join('') || '<div class="text-gray-500">Nobody clearly improving.</div>'}</div>
        <div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3"><div class="text-[10px] text-gray-500 uppercase tracking-widest mb-1">Already running to the winning par (last 3 avg)</div>
          ${atPar.map(t => `<div><b class="text-white">${esc(t.s.r.horse_name)}</b> <span class="text-gray-400">${num(t.last3, 1)} vs par ${num(race.form_par, 1)}</span></div>`).join('') || '<div class="text-gray-500">Nobody yet: the race is open to an improver.</div>'}</div>
      </div>
    </div>`;
}
function wormToggle(name) { const on = S.wormPick.on; on.has(name) ? on.delete(name) : on.add(name); renderWorm(S.races.find(r => r.race_id === S.view)); }
function wormAll(all) { const race = S.races.find(r => r.race_id === S.view); S.wormPick.on = new Set(all ? (S.runners[race.race_id] || []).map(r => r.horse_name) : []); renderWorm(race); }

// ---------------------------------------------------------------- track & barriers
const TS = { range: 100, going: 'all', rail: 'all', cache: {} };

async function renderTrackStats(race) {
  const box = document.getElementById('rt-track');
  const m = S.meeting || {};
  const goingBand = (typeof GOING_OF === 'function') ? GOING_OF(m.going) : null;
  const dmin = TS.range === 'all' ? 0 : race.distance - TS.range, dmax = TS.range === 'all' ? 9999 : race.distance + TS.range;
  const going = TS.going === 'today' ? goingBand : null;
  const rail = TS.rail === 'all' ? null : TS.rail;
  const key = [m.track, dmin, dmax, going, rail].join('|');
  const sel = (id, opts, cur) => `<select onchange="TS['${id}']=this.value==='all'?'all':(isNaN(this.value)?this.value:Number(this.value));renderTrackStats(S.races.find(r=>r.race_id===S.view))" class="syn-input px-2 py-1.5 text-xs">${opts.map(([v, l]) => `<option value="${v}" ${String(cur) === String(v) ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
  const head = `
    <div class="flex flex-wrap justify-between items-center gap-2 mb-3">
      <h2 class="text-white font-black text-lg">${esc(m.track || '')}: barriers and running position</h2>
      <div class="flex flex-wrap gap-2">
        ${sel('range', [[50, `${race.distance}m (±50m)`], [100, `${race.distance - 100}–${race.distance + 100}m`], [200, `${race.distance - 200}–${race.distance + 200}m`], ['all', 'All distances']], TS.range)}
        ${sel('going', [['all', 'All going'], ['today', `Today's going (${goingBand || '–'})`]], TS.going)}
        ${sel('rail', [['all', 'Any rail'], ['True', 'Rail true'], ['Out', 'Rail out']], TS.rail)}
      </div>
    </div>`;
  if (!TS.cache[key]) {
    box.innerHTML = `<div class="bg-[#11151d] border border-[#1e2638] rounded-xl p-5 shadow-2xl">${head}<div class="text-gray-400 text-sm">Crunching the history…</div></div>`;
    try {
      const { data, error } = await sb.rpc('edge_track_stats', { p_track: m.track, p_dmin: dmin, p_dmax: dmax, p_going: going, p_rail: rail });
      if (error) throw error;
      TS.cache[key] = data || [];
    } catch (e) {
      box.innerHTML = `<div class="bg-[#11151d] border border-[#1e2638] rounded-xl p-5 shadow-2xl">${head}<div class="text-amber-300 text-sm">Track stats switch on after the next engine run (it adds the database function). Try again after the next sync.</div></div>`;
      return;
    }
  }
  if (S.view !== race.race_id || (S.raceTab || 'odds') !== 'track') return;
  const rows = TS.cache[key];
  const meta = rows.find(r => r.dim === 'meta') || { races: 0, wins: 0 };
  const races = Number(meta.races) || 0;
  const bars = rows.filter(r => r.dim === 'barrier' && Number(r.expected) >= 0.5).sort((a, b) => a.sort_key - b.sort_key);
  const groups = rows.filter(r => r.dim === 'group' && Number(r.expected) > 0).sort((a, b) => a.sort_key - b.sort_key);
  const settle = rows.filter(r => r.dim === 'settle' && Number(r.expected) > 0).sort((a, b) => a.sort_key - b.sort_key);
  const conf = races >= 120 ? ['High', 'sect-green'] : races >= 50 ? ['Medium', 'sect-yellow'] : ['Low', 'sect-red'];
  const ivTone = (iv, wins) => (wins < 5 || iv === null) ? 'text-gray-400' : iv >= 1.2 ? 'text-emerald-400 font-bold' : iv <= 0.8 ? 'text-red-400 font-bold' : 'text-gray-200';
  const verdict = r => { const iv = Number(r.iv), w = Number(r.wins); if (w < 5 || races < 30) return '<span class="text-gray-500">small sample</span>'; return iv >= 1.2 ? '<span class="pill sect-green">GOOD</span>' : iv <= 0.8 ? '<span class="pill sect-red">BAD</span>' : '<span class="pill sect-yellow">FAIR</span>'; };
  const table = (title, list, note) => `
    <div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3">
      <h4 class="text-[11px] font-bold text-gray-400 uppercase tracking-widest mb-1">${title}</h4>
      <table class="w-full font-mono-numbers text-xs"><thead class="text-gray-500 text-[10px] uppercase"><tr><th class="text-left py-1">&nbsp;</th><th>Winners</th><th>Expected</th><th title="Impact value: winners ÷ expected. 1.0 = fair share">IV</th><th>Verdict</th></tr></thead>
      <tbody>${list.map(r => `<tr class="border-t border-[#1e2638]"><td class="py-1.5 font-sans text-gray-200">${esc(r.bucket)}</td><td class="text-center">${r.wins}</td><td class="text-center text-gray-400">${num(r.expected, 1)}</td><td class="text-center ${ivTone(Number(r.iv), Number(r.wins))}">${num(r.iv, 2)}</td><td class="text-center">${verdict(r)}</td></tr>`).join('')}</tbody></table>
      ${note ? `<p class="text-[10px] text-gray-500 mt-1">${note}</p>` : ''}</div>`;
  const maxIv = Math.max(2, ...bars.map(b => Number(b.iv) || 0));
  const chart = bars.length ? `<div class="flex items-end gap-1 h-40 mt-2">${bars.map(b => {
    const iv = Number(b.iv) || 0, h = Math.max(3, iv / maxIv * 100);
    const col = Number(b.wins) < 3 ? '#374151' : iv >= 1.2 ? '#10b981' : iv <= 0.8 ? '#ef4444' : '#9ca3af';
    return `<div class="flex-1 flex flex-col items-center justify-end h-full" title="Barrier ${b.bucket}: ${b.wins} winners from ${num(b.expected, 1)} expected (IV ${num(iv, 2)})">
      <div class="text-[9px] text-gray-400 mb-0.5">${num(iv, 1)}</div><div style="height:${h}%;background:${col}" class="w-full rounded-t"></div><div class="text-[10px] text-gray-400 mt-1">${b.bucket}</div></div>`; }).join('')}</div>
    <p class="text-[10px] text-gray-500 mt-1">Impact value per barrier (1.0 = its fair share of winners). Green 1.2+ good, red 0.8 or less bad, grey = fewer than 3 winners.</p>` : '';
  // facts and today's field
  const best = groups.filter(g => Number(g.wins) >= 5).sort((a, b) => b.iv - a.iv)[0], worst = groups.filter(g => Number(g.wins) >= 5).sort((a, b) => a.iv - b.iv)[0];
  const led = settle.find(s => s.sort_key === 1), back = settle.find(s => s.sort_key === 4);
  const facts = [];
  if (races) facts.push(`${races} races with a known winner at ${esc(m.track)} ${TS.range === 'all' ? 'over all distances' : `between ${dmin}m and ${dmax}m`}${going ? ` on ${going.toLowerCase()} going` : ''}${rail ? ` with the rail ${rail === 'True' ? 'true' : 'out'}` : ''}.`);
  if (best && worst && best !== worst) facts.push(`Best draw: <b class="text-emerald-400">${esc(best.bucket)}</b> (IV ${num(best.iv, 2)}); worst: <b class="text-red-400">${esc(worst.bucket)}</b> (IV ${num(worst.iv, 2)}).`);
  if (led && Number(led.races)) facts.push(`Leaders won ${Math.round(led.wins / led.races * 100)}% of races (IV ${num(led.iv, 2)}); back-half runners ${back ? Math.round(back.wins / back.races * 100) : 0}% (IV ${num(back && back.iv, 2)}). ${Number(led.iv) >= 2 ? 'On-pace track: speed holds.' : Number(back && back.iv) >= 0.9 ? 'Fair to swoopers.' : ''}`);
  const railN = Number(meta.wins) || 0;
  const field = (S.runners[race.race_id] || []).filter(r => !r._scratched).sort((a, b) => (a.barrier || 99) - (b.barrier || 99));
  const ivFor = b => { const g = groups.find(x => (x.sort_key === 1 && b <= 3) || (x.sort_key === 2 && b >= 4 && b <= 7) || (x.sort_key === 3 && b >= 8 && b <= 11) || (x.sort_key === 4 && b >= 12)); return g; };
  box.innerHTML = `
    <div class="bg-[#11151d] border border-[#1e2638] rounded-xl p-5 shadow-2xl space-y-4">
      ${head}
      <div class="flex flex-wrap items-center gap-2 text-xs"><span class="pill ${conf[1]} py-1">${conf[0]} confidence</span><span class="text-gray-400">${races} races · rail recorded for ${railN} of them</span></div>
      <div class="text-sm text-gray-300 space-y-1">${facts.map(f => `<div>${f}</div>`).join('') || '<div class="text-gray-500">No races in the history for this filter. Widen the distance range.</div>'}</div>
      ${chart}
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
        ${table('Barrier groups', groups, 'Barriers past the field size count as the outside gate.')}
        ${table('Where the winner settled', settle, 'From the winner\'s settling position in the run. "Led" expected = 1 runner\'s share of the field.')}
      </div>
      <div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3">
        <h4 class="text-[11px] font-bold text-gray-400 uppercase tracking-widest mb-2">Today's field by draw</h4>
        <div class="flex flex-wrap gap-2">${field.map(r => { const g = ivFor(r.barrier || 0); const iv = g ? Number(g.iv) : null; const tone = !g || Number(g.wins) < 5 ? 'border-[#1e2638] text-gray-300' : iv >= 1.2 ? 'border-emerald-500/50 text-emerald-300' : iv <= 0.8 ? 'border-red-500/50 text-red-300' : 'border-[#1e2638] text-gray-300';
          return `<span class="px-2 py-1 rounded border ${tone} text-xs font-mono-numbers" title="${g ? esc(g.bucket) + ' IV ' + num(iv, 2) : ''}">b${r.barrier} ${esc(shortName(r.horse_name))} · ${esc(zoneShort(r.map_zone) || '–')}</span>`; }).join('')}</div>
      </div>
      <p class="text-[10px] text-gray-500">Impact value (IV) = winners from a group ÷ the winners it would have if every gate or position had an equal chance. Only winners are counted, so it isn't skewed by which losers are in the history. ${railN < races ? 'Rail position only goes back to the meetings the engine has pulled itself (from Nov 2026), so the rail filter fills in over the coming months.' : ''}</p>
    </div>`;
}
