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
  if (tab === 'odds') renderLadder(race);
  if (tab === 'map') { renderTrackProfile(race); renderSpeedMap(race); }
  if (tab === 'worm') renderWorm(race);
  if (tab === 'track') renderTrackStats(race);
}

// ---------------------------------------------------------------- speed map tab
function railMetres(rail) { const m = String(rail || '').match(/([+-]?\d+(\.\d+)?)\s*m/i); return m ? Math.abs(parseFloat(m[1])) : 0; }

function renderTrackProfile(race) {
  const m = S.meeting || {}, g = trackGeom(m.track, race.distance);
  const box = document.getElementById('trackProfile');
  let turn = 'Unknown', turnNote = '';
  if (g) {
    if (g.firstTurn === 'straight') turn = 'No turn (straight course)';
    else if (g.firstTurn === 0) turn = 'Starts on the turn';
    else turn = `${g.turnSrc === 'estimate' ? '≈ ' : ''}${Math.round(g.firstTurn / 10) * 10}m`;
    turnNote = g.turnSrc === 'estimate' ? 'estimate from the track size' : g.turnSrc === 'published' ? 'published figure' : 'your figure';
  }
  const start = g ? (g.firstTurn === 'straight' ? 'Straight course' : 'On ' + g.startWhere + (g.laps ? ', passing the post once' : '')) : 'Unknown';
  const rm = railMetres(m.rail);
  box.innerHTML = `
    <div class="bg-[#11151d] border border-[#1e2638] rounded-xl p-5 shadow-2xl">
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div><div class="text-[10px] text-gray-500 uppercase tracking-widest">Where they start (${race.distance}m)</div>
          <div class="text-white font-black text-xl mt-1">${esc(start)}</div></div>
        <div><div class="text-[10px] text-gray-500 uppercase tracking-widest">Run to the first turn</div>
          <div class="text-white font-black text-xl mt-1">${turn} <span class="text-[11px] font-normal ${g && g.turnSrc === 'estimate' ? 'text-amber-300' : 'text-gray-500'}">${turnNote}</span></div></div>
      </div>
      <div class="text-[11px] text-gray-500 mt-3">${esc(m.track || '')}${g ? ` · ${g.t.circ}m circuit · ${g.t.straight}m straight` : ''} · rail ${esc(m.rail || '–')}${rm ? ` <span class="text-amber-300">(out ${rm}m: inside draws lose some edge)</span>` : ''} · ${esc(m.going || '')}</div>
      ${g ? `<div class="flex flex-wrap items-center gap-2 mt-2 text-[11px] text-gray-500">
        <span>Race book says different?</span>
        <input id="turnFix" type="number" class="syn-input px-2 py-1 w-24 text-xs" placeholder="metres" value="${g.turnSrc === 'yours' ? g.firstTurn : ''}">
        <button class="text-[#ff6600] font-bold" onclick="saveTurnOverride('${esc(m.track)}', ${race.distance}, document.getElementById('turnFix').value); renderRaceTab(S.races.find(r=>r.race_id===S.view))">Save</button>
        <span class="text-gray-600">(0 = starts on the turn; blank = back to the ${g.turnSrc === 'published' ? 'published figure' : 'estimate'})</span>
      </div>` : `<p class="text-[11px] text-gray-500 mt-2">No published dimensions for ${esc(m.track || 'this track')} yet.</p>`}
    </div>`;
}

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
    const nameTip = esc(`${s.r.saddlecloth ?? ''}. ${s.r.horse_name} · ${money(s.r._fair)} true`);
    let out = `<path d="${d}" fill="none" stroke="${hiOn ? s.col : '#4b5563'}" stroke-width="${hiOn ? 3 : 1.2}" opacity="${hiOn ? 1 : .45}"/>
      <path d="${d}" fill="none" stroke="transparent" stroke-width="12" data-tip="${nameTip}" style="cursor:pointer" onclick="wormToggle(${JSON.stringify(s.r.horse_name).replace(/"/g, '&quot;')})"/>`;
    s.pts.forEach(q => {
      const lv = lengthsVsPar(q.v, race);
      const tip = `${s.r.horse_name}: ${q.x.date || ''} ${q.x.track || ''} ${q.x.dist ?? ''}m · ${q.x.pos ?? ''}/${q.x.field ?? ''} · rating ${num(q.v, 1)}` +
        (lv === null ? '' : ` (${lv >= 0 ? '+' : ''}${lv.toFixed(1)}L vs par)`) + (q.x.prep ? ` · run ${q.x.prep} of prep` : '');
      out += `<circle cx="${X(q.k)}" cy="${Y(q.v)}" r="${hiOn ? 4.5 : 2.5}" fill="${hiOn ? (q.x.pos === 1 ? '#fff' : s.col) : '#4b5563'}" stroke="${hiOn ? s.col : 'none'}" stroke-width="2" opacity="${hiOn ? 1 : .5}"/>
        <circle cx="${X(q.k)}" cy="${Y(q.v)}" r="10" fill="transparent" data-tip="${esc(tip)}"/>`;
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


// ---------------------------------------------------------------- lengths ladder
// How many lengths each runner has to find on the favourite (and on the top
// rated), from its last start, its last-3 average, or today's expected run.
function ladderValue(r, race, basis) {
  if (basis === 'form') return r.form_gap_l ?? null;                  // already lengths vs par
  const xs = parseJSON(r.last_runs, []).map(x => x.rating).filter(v => v);
  if (!xs.length) return null;
  const v = basis === 'last' ? xs[0] : xs.slice(0, 3).reduce((a, b) => a + b, 0) / Math.min(3, xs.length);
  return v * lppFor(race.distance, race);                              // ratings -> lengths scale
}
function renderLadder(race) {
  const box = document.getElementById('lengthsLadder'); if (!box) return;
  const basis = S.ladderBasis || 'last';
  const rows = (S.runners[race.race_id] || []).filter(r => !r._scratched && !r.scratched)
    .map(r => ({ r, v: ladderValue(r, race, basis), px: r._market || r.market_price }))
    .sort((a, b) => (a.px || 999) - (b.px || 999));
  const rated = rows.filter(x => x.v !== null);
  if (!rated.length) { box.innerHTML = ''; return; }
  const fav = rows.find(x => x.v !== null && x.px) || rated[0];
  const top = rated.slice().sort((a, b) => b.v - a.v)[0];
  const second = rated.slice().sort((a, b) => b.v - a.v)[1];
  const lab = { last: 'last start', avg3: 'average of the last 3 runs', form: "today's expected run (Form L)" }[basis];
  const L = v => (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(1) + 'L';
  const maxGap = Math.max(1, ...rated.map(x => top.v - x.v));
  let head = `On ${lab}, <b class="text-white">${esc(top.r.horse_name)}</b> is the top-rated`;
  if (second) head += `, <b class="text-emerald-400">${(top.v - second.v).toFixed(1)}L</b> clear of ${esc(second.r.horse_name)}`;
  head += '.';
  if (fav && fav !== top) head += ` The favourite, <b class="text-white">${esc(fav.r.horse_name)}</b> (${money(fav.px)}), has <b class="text-amber-300">${(top.v - fav.v).toFixed(1)}L</b> to find on it.`;
  else if (fav) head += ' The favourite is also the top-rated.';
  const btn = (k, l) => `<button onclick="S.ladderBasis='${k}';renderLadder(S.races.find(r=>r.race_id===S.view))" class="rt-btn ${basis === k ? 'active' : ''}" style="font-size:10px;padding:5px 10px">${l}</button>`;
  box.innerHTML = `
    <div class="bg-[#11151d] border border-[#1e2638] rounded-xl p-5 shadow-2xl">
      <div class="flex flex-wrap justify-between items-center gap-2 mb-2">
        <h2 class="text-white font-black text-lg">Lengths to find</h2>
        <div class="flex flex-wrap gap-2">${btn('last', 'Last start')}${btn('avg3', 'Last 3 average')}${btn('form', "Today's form")}</div>
      </div>
      <p class="text-sm text-gray-300 mb-3">${head}</p>
      <div class="overflow-x-auto"><table class="w-full font-mono-numbers text-xs">
        <thead class="text-gray-500 uppercase text-[10px]"><tr>
          <th class="text-left py-2">Price</th><th class="text-left font-sans">Horse</th>
          <th class="text-right px-2" title="Lengths behind (−) or ahead (+) of the favourite">vs favourite</th>
          <th class="text-right px-2" title="Lengths behind the top-rated runner">vs top-rated</th>
          <th class="px-3 w-1/3"></th></tr></thead>
        <tbody>${rows.map(x => {
          if (x.v === null) return `<tr class="border-t border-[#1e2638]"><td class="py-2">${money(x.px)}</td><td class="font-sans text-gray-400">${x.r.saddlecloth ?? ''}. ${esc(x.r.horse_name)}</td><td colspan="3" class="text-gray-600 px-2">no rated runs</td></tr>`;
          const vf = x.v - fav.v, vt = x.v - top.v;
          const w = Math.max(2, (1 - (top.v - x.v) / maxGap) * 100);
          const col = vt >= -0.05 ? '#10b981' : vt >= -2 ? '#f59e0b' : '#ef4444';
          return `<tr class="border-t border-[#1e2638] ${x === fav ? 'bg-[#ff6600]/5' : ''}">
            <td class="py-2 text-white">${money(x.px)}${x === fav ? ' <span class="text-[#ff6600] text-[10px]">FAV</span>' : ''}</td>
            <td class="font-sans text-white font-bold">${x.r.saddlecloth ?? ''}. ${esc(x.r.horse_name)}</td>
            <td class="text-right px-2 ${x === fav ? 'text-gray-500' : vf >= 0 ? 'text-emerald-400' : 'text-gray-300'}">${x === fav ? '–' : L(vf)}</td>
            <td class="text-right px-2 ${vt >= -0.05 ? 'text-emerald-400 font-bold' : vt >= -2 ? 'text-amber-300' : 'text-red-400'}">${vt >= -0.05 ? 'top' : L(vt)}</td>
            <td class="px-3"><div class="h-2 rounded bg-[#0d1117]"><div class="h-2 rounded" style="width:${w}%;background:${col}"></div></div></td></tr>`; }).join('')}</tbody>
      </table></div>
      <p class="text-[10px] text-gray-500 mt-2">Ordered by price. Rating gaps are turned into lengths at ${lppFor(race.distance, race).toFixed(2)} lengths per rating point for ${race.distance}m (fitted from horses that met in the same race). Ratings already allow for weight and age on the day they were run; today's weights aren't in them.</p>
    </div>`;
}
