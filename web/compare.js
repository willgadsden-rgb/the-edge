/* The Edge website: Compare tab.
 *
 *   Lengths calculator  ratings -> lengths at any distance (fitted lengths per point).
 *   Compare horses      2-4 horses from today's card or the database, side by side:
 *                       expected rating at a chosen trip and going (same weighting as
 *                       the engine's form model), lengths between them, best trip,
 *                       going, improvement signals and a ratings chart.
 * Uses globals from index.html / features.js (S, sb, esc, num, money, lppFor, GOING_OF,
 * STAGE_OF, DIST_OF, findInCard, EXCUSE_RE, WORM_COLOURS from race-tabs.js).
 */

const CMP = { slots: [null, null, null, null], runs: {}, dist: null, going: null, par: null, calc: [78, 70, '', ''], calcDist: 1200 };
const CMP_COL = ['#ff6600', '#38bdf8', '#10b981', '#f472b6'];

// ---------------------------------------------------------------- calculator
function renderCalc() {
  const box = document.getElementById('cmpCalc'); if (!box) return;
  const d = Number(CMP.calcDist) || 1200, lpp = lppFor(d);
  const vals = CMP.calc.map(v => (v === '' || v === null || isNaN(v)) ? null : Number(v));
  const best = Math.max(...vals.filter(v => v !== null));
  const rows = vals.map((v, i) => v === null ? '' : `
    <tr class="border-t border-[#1e2638]"><td class="py-2 font-sans text-white font-bold">Horse ${i + 1}</td><td class="text-right px-2">${num(v, 1)}</td>
      <td class="text-right px-2 ${v === best ? 'text-emerald-400 font-bold' : 'text-red-300'}">${v === best ? 'best' : '−' + ((best - v) * lpp).toFixed(1) + 'L'}</td></tr>`).join('');
  const a = vals[0], b = vals[1];
  const dists = [1000, 1200, 1400, 1600, 2000, 2400];
  box.innerHTML = `
    <div class="grid grid-cols-2 md:grid-cols-5 gap-3 items-end">
      ${[0, 1, 2, 3].map(i => `<label class="text-[10px] text-gray-500 uppercase tracking-widest">Horse ${i + 1} rating
        <input type="number" step="0.1" value="${CMP.calc[i]}" oninput="CMP.calc[${i}]=this.value;renderCalc()" class="syn-input w-full p-2 mt-1 text-base font-mono-numbers"></label>`).join('')}
      <label class="text-[10px] text-gray-500 uppercase tracking-widest">Distance (m)
        <input type="number" step="50" value="${d}" oninput="CMP.calcDist=this.value;renderCalc()" class="syn-input w-full p-2 mt-1 text-base font-mono-numbers"></label>
    </div>
    ${a !== null && b !== null ? `<div class="mt-4 text-lg text-white">At ${d}m, <b>${num(Math.max(a, b), 1)}</b> vs <b>${num(Math.min(a, b), 1)}</b> = <b class="text-[#ff6600] text-2xl">${(Math.abs(a - b) * lpp).toFixed(1)} lengths</b> <span class="text-sm text-gray-400">(${Math.abs(a - b).toFixed(1)} points × ${lpp.toFixed(2)} lengths a point)</span></div>` : ''}
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
      <table class="w-full font-mono-numbers text-xs"><thead class="text-gray-500 uppercase text-[10px]"><tr><th class="text-left py-1">&nbsp;</th><th class="text-right px-2">Rating</th><th class="text-right px-2">vs best</th></tr></thead><tbody>${rows}</tbody></table>
      ${a !== null && b !== null ? `<table class="w-full font-mono-numbers text-xs"><thead class="text-gray-500 uppercase text-[10px]"><tr><th class="text-left py-1">Same gap over</th>${dists.map(x => `<th class="text-right">${x}m</th>`).join('')}</tr></thead>
        <tbody><tr class="border-t border-[#1e2638]"><td class="py-2 font-sans text-gray-300">Horse 1 vs 2</td>${dists.map(x => `<td class="text-right ${x === d ? 'text-[#ff6600] font-bold' : ''}">${(Math.abs(a - b) * lppFor(x)).toFixed(1)}L</td>`).join('')}</tr></tbody></table>` : ''}
    </div>
    <p class="text-[10px] text-gray-500 mt-2">A rating point is worth more lengths the further they go (horses string out): about 0.47L at 1000m up to 0.74L at 2400m, fitted from horses that met in the same race.</p>`;
}

// ---------------------------------------------------------------- horse slots
let _cmpT = null;
function cmpSearch(i, q) {
  clearTimeout(_cmpT);
  _cmpT = setTimeout(async () => {
    const box = document.getElementById('cmpRes' + i);
    q = q.trim();
    if (q.length < 2) { box.innerHTML = ''; return; }
    const today = [];
    S.races.forEach(race => (S.runners[race.race_id] || []).forEach(r => { if (!r.scratched && r.horse_name.toLowerCase().includes(q.toLowerCase())) today.push(r.horse_name); }));
    let db = [];
    try { const { data } = await sb.rpc('edge_horse_search', { q }); db = (data || []).map(x => x.horse_name); } catch (e) {}
    const names = [...new Set(today.concat(db))].slice(0, 8);
    box.innerHTML = names.map(n => `<button class="block w-full text-left px-2 py-1.5 text-xs hover:bg-[#ff6600]/10 text-gray-200" onclick='cmpPick(${i}, ${JSON.stringify(n).replace(/'/g, "&#39;")})'>${esc(n)}${today.includes(n) ? ' <span class="text-[#ff6600]">· today</span>' : ''}</button>`).join('') || '<div class="text-xs text-gray-500 px-2 py-1">No horse found.</div>';
  }, 250);
}
async function cmpPick(i, name) {
  CMP.slots[i] = name;
  await cmpLoad(name);
  cmpDefaults();
  renderCompare();
}
function cmpClear(i) { CMP.slots[i] = null; renderCompare(); }

async function cmpLoad(name) {
  if (CMP.runs[name]) return;
  let runs = null;
  try { const { data, error } = await sb.rpc('edge_horse_runs', { p_name: name }); if (!error) runs = data || []; } catch (e) {}
  if (!runs || !runs.length) { const c = findInCard(name); runs = c ? runsFromCard(c.r) : []; }
  CMP.runs[name] = runs.map(x => ({ ...x, _d: x.race_date ? new Date(x.race_date) : null })).sort((a, b) => (b._d || 0) - (a._d || 0));
}

// Defaults: today's race of the first compared horse that is running today.
function cmpDefaults() {
  if (CMP.dist) return;
  for (const n of CMP.slots) {
    const c = n && findInCard(n);
    if (c) { CMP.dist = c.race.distance; CMP.going = GOING_OF((S.meeting || {}).going); CMP.par = c.race.form_par; CMP.race = c.race; return; }
  }
}

function cmpFromRace() {
  const race = S.races.find(r => r.race_id === S.view); if (!race) return;
  const book = byBook((S.runners[race.race_id] || []).filter(r => !r._scratched && !r.scratched));
  CMP.slots = [0, 1, 2, 3].map(i => book[i] ? book[i].horse_name : null);
  CMP.dist = race.distance; CMP.going = GOING_OF((S.meeting || {}).going); CMP.par = race.form_par; CMP.race = race;
  switchTab('compare');
  Promise.all(CMP.slots.filter(Boolean).map(cmpLoad)).then(renderCompare);
}

// ---------------------------------------------------------------- the maths (mirrors form_model.FormModel.rate)
const HALF_LIFE = 120;
function expectedRating(runs, dist, going) {
  const rated = runs.filter(x => x.wfa_rating);
  if (!rated.length) return null;
  const now = new Date();
  let sw = 0, swr = 0, sw2 = 0;
  rated.forEach(x => {
    const age = x._d ? Math.max(0, (now - x._d) / 864e5) : 365;
    const wr = Math.pow(0.5, age / HALF_LIFE);
    const wg = !going || GOING_OF(x.going) === going ? 1 : 0.5;
    const dd = dist && x.distance ? Math.abs(x.distance - dist) : 0;
    const wd = !dist ? 1 : dd <= 200 ? 1 : dd <= 400 ? 0.7 : 0.4;
    const we = x.stewards_comment && EXCUSE_RE.test(x.stewards_comment) ? 0.5 : 1;
    const w = wr * wg * wd * we;
    sw += w; swr += w * x.wfa_rating; sw2 += w * w;
  });
  return { rating: swr / sw, depth: sw * sw / sw2 };
}
function bandStats(runs, keyFn) {
  const g = {};
  runs.forEach(x => { const k = keyFn(x); if (!k || k === '–') return; (g[k] = g[k] || []).push(x); });
  const out = {};
  Object.entries(g).forEach(([k, xs]) => {
    const r = xs.map(x => x.wfa_rating).filter(Boolean);
    out[k] = { n: xs.length, w: xs.filter(x => x.finish_pos === 1).length, p: xs.filter(x => x.finish_pos && x.finish_pos <= 3).length,
               avg: r.length ? r.reduce((a, b) => a + b, 0) / r.length : null, best: r.length ? Math.max(...r) : null };
  });
  return out;
}
function nextStage(runs, name) {
  const c = findInCard(name);
  if (c && c.r.prep_run) return c.r.prep_run;
  const last = runs[0];
  if (!last || !last._d) return 1;
  const days = (new Date() - last._d) / 864e5;
  return days > 60 ? 1 : (last.race_in_prep || 0) + 1;
}
function improvementSignals(runs, name, dist, going, exp) {
  const out = [];
  const rated = runs.filter(x => x.wfa_rating);
  if (!rated.length) return out;
  // 1. Prep pattern: how it rates at today's stage vs the stage before.
  const st = nextStage(runs, name);
  const by = bandStats(rated, x => x.race_in_prep >= 5 ? 5 : x.race_in_prep);
  const cur = by[Math.min(st, 5)], prev = by[Math.min(st - 1, 5)];
  if (st > 1 && cur && prev && cur.n >= 1 && prev.n >= 1 && cur.avg !== null && prev.avg !== null) {
    const d = cur.avg - prev.avg;
    if (Math.abs(d) >= 1.5) out.push({ good: d > 0, t: `${STAGE_OF(st)} it averages ${cur.avg.toFixed(1)} vs ${prev.avg.toFixed(1)} the run before (${d > 0 ? '+' : ''}${d.toFixed(1)} pts, ${cur.n} run${cur.n > 1 ? 's' : ''})` });
  } else if (st === 1 && by[1] && by[2] && by[1].avg !== null && by[2].avg !== null && by[2].avg - by[1].avg >= 2) {
    out.push({ good: false, t: `First-up today; it usually runs ${(by[2].avg - by[1].avg).toFixed(1)} pts better second-up, so expect improvement next start` });
  }
  // 2. Trend.
  if (rated.length >= 4) {
    const a = rated.slice(0, 3).reduce((s, x) => s + x.wfa_rating, 0) / 3, bxs = rated.slice(3, 6), b = bxs.reduce((s, x) => s + x.wfa_rating, 0) / bxs.length;
    if (Math.abs(a - b) >= 2) out.push({ good: a > b, t: `Last 3 average ${a.toFixed(1)} vs ${b.toFixed(1)} before (${a > b ? 'improving' : 'declining'} ${Math.abs(a - b).toFixed(1)} pts)` });
  }
  // 3. Headroom: best in the last 12 months vs what we expect today.
  const yr = rated.filter(x => x._d && (new Date() - x._d) / 864e5 <= 365);
  if (yr.length && exp) {
    const best = Math.max(...yr.map(x => x.wfa_rating));
    const hl = (best - exp.rating) * lppFor(dist);
    if (hl >= 1.5) out.push({ good: true, t: `Has run ${hl.toFixed(1)}L better than today's expected (best ${best.toFixed(1)} in the last 12 months)` });
  }
  // 4. Trip and going today vs its best.
  const db = bandStats(rated, x => DIST_OF(x.distance));
  const today = DIST_OF(dist);
  const bestBand = Object.entries(db).filter(([, v]) => v.n >= 2 && v.avg !== null).sort((a, b) => b[1].avg - a[1].avg)[0];
  if (bestBand && db[today] && bestBand[0] !== today && bestBand[1].avg - db[today].avg >= 2) out.push({ good: false, t: `Rates ${(bestBand[1].avg - db[today].avg).toFixed(1)} pts better at ${bestBand[0]} than at today's ${today}` });
  if (bestBand && bestBand[0] === today) out.push({ good: true, t: `Today's trip (${today}) is its best distance band` });
  if (!db[today] && dist) out.push({ good: null, t: `Unraced at ${today}` });
  const gb = bandStats(rated, x => GOING_OF(x.going));
  if (going && gb[going] && gb[going].avg !== null) {
    const all = rated.reduce((s, x) => s + x.wfa_rating, 0) / rated.length;
    const d = gb[going].avg - all;
    if (Math.abs(d) >= 1.5) out.push({ good: d > 0, t: `${d > 0 ? 'Better' : 'Worse'} on ${BAND_LABEL[going] || going} (${d > 0 ? '+' : ''}${d.toFixed(1)} pts vs its average, ${gb[going].n} runs)` });
  } else if (going) out.push({ good: null, t: `Unraced on ${(BAND_LABEL[going] || going).toLowerCase()} going` });
  // 5. Days since.
  const last = runs[0];
  if (last && last._d) { const days = Math.round((new Date() - last._d) / 864e5); if (days <= 10) out.push({ good: null, t: `Backing up quickly (${days} days)` }); }
  return out;
}

// ---------------------------------------------------------------- render
function renderCompare() {
  renderCalc();
  const box = document.getElementById('cmpBody'); if (!box) return;
  const names = CMP.slots;
  const slots = names.map((n, i) => `
    <div class="bg-[#0d1117] border rounded-lg p-3" style="border-color:${n ? CMP_COL[i] : '#1e2638'}">
      <div class="text-[10px] uppercase tracking-widest mb-1" style="color:${CMP_COL[i]}">Horse ${i + 1}</div>
      ${n ? `<div class="flex justify-between items-center gap-2"><b class="text-white">${esc(n)}</b><button class="text-gray-500 hover:text-red-400 font-bold" onclick="cmpClear(${i})">×</button></div>`
          : `<input class="syn-input w-full p-2 text-sm" placeholder="Type a name" oninput="cmpSearch(${i}, this.value)"><div id="cmpRes${i}" class="mt-1 max-h-48 overflow-y-auto"></div>`}
    </div>`).join('');
  const chosen = names.map((n, i) => n ? { n, i, runs: CMP.runs[n] || [] } : null).filter(Boolean);
  const dist = Number(CMP.dist) || 1200, going = CMP.going || '';
  const ctrl = `
    <div class="flex flex-wrap items-end gap-3 mt-4">
      <label class="text-[10px] text-gray-500 uppercase tracking-widest">Compare over (m)<input type="number" step="50" value="${dist}" onchange="CMP.dist=this.value;renderCompare()" class="syn-input block w-28 p-2 mt-1 font-mono-numbers"></label>
      <label class="text-[10px] text-gray-500 uppercase tracking-widest">Going<select onchange="CMP.going=this.value;renderCompare()" class="syn-input block p-2 mt-1">
        ${[['', 'Any'], ['Good', 'Dry'], ['Soft', 'Soft'], ['Heavy', 'Heavy'], ['Synthetic', 'Synthetic']].map(([v, l]) => `<option value="${v}" ${going === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
      <label class="text-[10px] text-gray-500 uppercase tracking-widest">Winning par (optional)<input type="number" step="0.1" value="${CMP.par ?? ''}" onchange="CMP.par=this.value===''?null:Number(this.value);renderCompare()" class="syn-input block w-28 p-2 mt-1 font-mono-numbers"></label>
      ${S.view !== 'ALL' && S.races.find(r => r.race_id === S.view) ? `<button onclick="cmpFromRace()" class="text-xs font-bold text-[#ff6600] border border-[#ff6600]/40 rounded-lg px-3 py-2">Load top 4 from R${S.races.find(r => r.race_id === S.view).race_number}</button>` : ''}
    </div>`;
  if (chosen.length < 2) {
    box.innerHTML = `<div class="grid grid-cols-1 md:grid-cols-4 gap-3">${slots}</div>${ctrl}<div class="text-sm text-gray-400 mt-4">Pick at least two horses. Tip: open a race and press <b class="text-white">Compare</b> above the Odds Matrix to load its top four.</div>`;
    return;
  }
  const lpp = lppFor(dist);
  chosen.forEach(c => { c.exp = expectedRating(c.runs, dist, going || null); c.rated = c.runs.filter(x => x.wfa_rating); });
  const ranked = chosen.filter(c => c.exp).sort((a, b) => b.exp.rating - a.exp.rating);
  const top = ranked[0];
  const head = top ? (ranked.length > 1 ? `On form weighted to ${dist}m${going ? ' and ' + (BAND_LABEL[going] || going).toLowerCase() + ' going' : ''}, <b class="text-white">${esc(top.n)}</b> rates best: ` +
      ranked.slice(1).map(c => `<b class="text-white">${((top.exp.rating - c.exp.rating) * lpp).toFixed(1)}L</b> better than ${esc(c.n)}`).join(', ') + '.' : '') : 'No rated runs to compare.';
  // pairwise matrix
  const matrix = ranked.length > 1 ? `<table class="w-full font-mono-numbers text-xs"><thead class="text-gray-500 text-[10px] uppercase"><tr><th class="text-left py-1">Row vs column</th>${ranked.map(c => `<th class="text-right px-2" style="color:${CMP_COL[c.i]}">${esc(shortName(c.n))}</th>`).join('')}</tr></thead><tbody>${ranked.map(a => `<tr class="border-t border-[#1e2638]"><td class="py-2 font-sans font-bold" style="color:${CMP_COL[a.i]}">${esc(a.n)}</td>${ranked.map(b => {
      if (a === b) return '<td class="text-right px-2 text-gray-600">–</td>';
      const l = (a.exp.rating - b.exp.rating) * lpp; return `<td class="text-right px-2 ${l >= 0 ? 'text-emerald-400' : 'text-red-400'}">${l >= 0 ? '+' : '−'}${Math.abs(l).toFixed(1)}L</td>`; }).join('')}</tr>`).join('')}</tbody></table>` : '';
  // per-horse cards
  const card = c => {
    const r = c.rated, last5 = r.slice(0, 5);
    const avg5 = last5.length ? last5.reduce((s, x) => s + x.wfa_rating, 0) / last5.length : null;
    const yr = r.filter(x => x._d && (new Date() - x._d) / 864e5 <= 365);
    const w = c.runs.filter(x => x.finish_pos === 1).length, pl = c.runs.filter(x => x.finish_pos && x.finish_pos <= 3).length;
    const st = nextStage(c.runs, c.n);
    const vsPar = CMP.par && c.exp ? (c.exp.rating - CMP.par) * lpp : null;
    const sig = improvementSignals(c.runs, c.n, dist, going || null, c.exp);
    const days = c.runs[0] && c.runs[0]._d ? Math.round((new Date() - c.runs[0]._d) / 864e5) : null;
    const stat = (l, v, cls = 'text-white') => `<div><div class="text-[10px] text-gray-500 uppercase tracking-widest">${l}</div><div class="font-mono-numbers font-bold ${cls}">${v}</div></div>`;
    return `<div class="bg-[#11151d] border rounded-xl p-4 space-y-3" style="border-color:${CMP_COL[c.i]}66">
      <div class="flex justify-between items-start gap-2"><div><div class="text-[10px] uppercase tracking-widest" style="color:${CMP_COL[c.i]}">Horse ${c.i + 1}</div>
        <button class="text-white font-black text-lg hover:text-[#ff6600] text-left" onclick='openHorse(${JSON.stringify(c.n).replace(/'/g, "&#39;")})'>${esc(c.n)}</button></div>
        ${top === c ? '<span class="pill sect-green">RATES BEST</span>' : ''}</div>
      <div class="grid grid-cols-3 gap-3">
        ${stat('Expected today', c.exp ? c.exp.rating.toFixed(1) : '–', 'text-[#ffa366]')}
        ${stat('vs top', c.exp && top && top !== c ? '−' + ((top.exp.rating - c.exp.rating) * lpp).toFixed(1) + 'L' : top === c ? 'best' : '–', top === c ? 'text-emerald-400' : 'text-red-300')}
        ${stat('vs par', vsPar === null ? '–' : (vsPar >= 0 ? '+' : '−') + Math.abs(vsPar).toFixed(1) + 'L', vsPar === null ? 'text-gray-400' : vsPar >= 0 ? 'text-emerald-400' : vsPar >= -2 ? 'text-amber-300' : 'text-red-400')}
        ${stat('Last start', r[0] ? r[0].wfa_rating.toFixed(1) : '–')}
        ${stat('Avg last 5', avg5 ? avg5.toFixed(1) : '–')}
        ${stat('Best (12 mths)', yr.length ? Math.max(...yr.map(x => x.wfa_rating)).toFixed(1) : '–')}
        ${stat('Record', `${c.runs.length}: ${w}-${pl - w}`)}
        ${stat('Today', STAGE_OF(st))}
        ${stat('Days since', days ?? '–')}
      </div>
      <div><div class="text-[10px] text-gray-500 uppercase tracking-widest mb-1">Improvement signals</div>
        ${sig.map(s => `<div class="text-xs ${s.good === true ? 'text-emerald-300' : s.good === false ? 'text-red-300' : 'text-gray-400'}">${s.good === true ? '▲' : s.good === false ? '▼' : '•'} ${esc(s.t)}</div>`).join('') || '<div class="text-xs text-gray-500">Nothing stands out.</div>'}</div>
      <div class="text-[10px] text-gray-500">Form depth: ${c.exp ? c.exp.depth.toFixed(1) : 0} effective runs at this trip/going ${c.exp && c.exp.depth < 1.5 ? '<span class="text-amber-300">(thin: treat with care)</span>' : ''}</div>
    </div>`;
  };
  // distance and going tables
  const bandTable = (title, keyFn, order, todayKey, labelFn = k => k) => {
    const stats = chosen.map(c => bandStats(c.rated, keyFn));
    return `<div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3 overflow-x-auto"><h4 class="text-[11px] font-bold text-gray-400 uppercase tracking-widest mb-2">${title}: average rating (runs)</h4>
      <table class="w-full font-mono-numbers text-xs"><thead class="text-[10px] uppercase"><tr><th class="text-left py-1 text-gray-500">&nbsp;</th>${chosen.map(c => `<th class="text-right px-2" style="color:${CMP_COL[c.i]}">${esc(shortName(c.n))}</th>`).join('')}</tr></thead>
      <tbody>${order.map(k => {
        const vals = stats.map(s => s[k] && s[k].avg !== null ? s[k].avg : null);
        if (vals.every(v => v === null)) return '';
        const mx = Math.max(...vals.filter(v => v !== null));
        return `<tr class="border-t border-[#1e2638] ${k === todayKey ? 'bg-[#ff6600]/10' : ''}"><td class="py-1.5 font-sans ${k === todayKey ? 'text-[#ff6600] font-bold' : 'text-gray-300'}">${esc(labelFn(k))}${k === todayKey ? ' ◀' : ''}</td>${stats.map((s, j) => s[k] && s[k].avg !== null
          ? `<td class="text-right px-2 ${vals[j] === mx && vals.filter(v => v !== null).length > 1 ? 'text-emerald-400 font-bold' : 'text-gray-200'}">${s[k].avg.toFixed(1)} <span class="text-gray-500">(${s[k].n})</span></td>` : '<td class="text-right px-2 text-gray-600">–</td>').join('')}</tr>`; }).join('')}</tbody></table></div>`;
  };
  // overlay chart: last 12 rated runs each, oldest -> newest
  const N = 12, W = 960, H = 300, pl = 40, pr = 20, pt = 16, pb = 28;
  const series = chosen.map(c => ({ c, pts: c.rated.slice(0, N).reverse() }));
  const allv = series.flatMap(s => s.pts.map(x => x.wfa_rating)).concat(CMP.par ? [CMP.par] : []);
  let chart = '';
  if (allv.length) {
    const lo = Math.floor(Math.min(...allv) - 2), hi = Math.ceil(Math.max(...allv) + 2);
    const X = (k, n) => pl + (N - n + k) * (W - pl - pr) / (N - 1), Y = v => pt + (hi - v) / (hi - lo) * (H - pt - pb);
    chart = `<svg viewBox="0 0 ${W} ${H}" class="w-full">`;
    for (let v = Math.ceil(lo / 5) * 5; v <= hi; v += 5) chart += `<line x1="${pl}" x2="${W - pr}" y1="${Y(v)}" y2="${Y(v)}" stroke="#1e2638"/><text x="${pl - 6}" y="${Y(v) + 3}" fill="#6b7280" font-size="10" text-anchor="end">${v}</text>`;
    if (CMP.par) chart += `<line x1="${pl}" x2="${W - pr}" y1="${Y(CMP.par)}" y2="${Y(CMP.par)}" stroke="#ff6600" stroke-dasharray="5 4" opacity=".7"/><text x="${pl + 4}" y="${Y(CMP.par) - 4}" fill="#ff6600" font-size="10">par ${num(CMP.par, 1)}</text>`;
    chart += `<text x="${W - pr}" y="${H - 8}" fill="#6b7280" font-size="10" text-anchor="end">most recent →</text>`;
    series.forEach(s => {
      const n = s.pts.length; if (!n) return;
      const col = CMP_COL[s.c.i];
      chart += `<path d="${s.pts.map((x, k) => `${k ? 'L' : 'M'}${X(k, n).toFixed(1)},${Y(x.wfa_rating).toFixed(1)}`).join(' ')}" fill="none" stroke="${col}" stroke-width="2.5"/>`;
      s.pts.forEach((x, k) => {
        chart += `<circle cx="${X(k, n)}" cy="${Y(x.wfa_rating)}" r="4" fill="${x.finish_pos === 1 ? '#fff' : col}" stroke="${col}" stroke-width="2"/>
          <circle cx="${X(k, n)}" cy="${Y(x.wfa_rating)}" r="10" fill="transparent" data-tip="${esc(`${s.c.n}: ${x.race_date || ''} ${x.track || ''} ${x.distance ?? ''}m ${x.going || ''} · ${x.finish_pos ?? ''}/${x.field_size ?? ''} · rating ${num(x.wfa_rating, 1)} · ${STAGE_OF(x.race_in_prep)}`)}"/>`;
      });
    });
    chart += '</svg>';
  }
  box.innerHTML = `
    <div class="grid grid-cols-1 md:grid-cols-4 gap-3">${slots}</div>
    ${ctrl}
    <div class="text-base text-gray-200 mt-5">${head}</div>
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">${chosen.map(card).join('')}</div>
    ${matrix ? `<div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3 mt-4"><h4 class="text-[11px] font-bold text-gray-400 uppercase tracking-widest mb-2">Lengths between them at ${dist}m (expected ratings)</h4>${matrix}</div>` : ''}
    <div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3 mt-4"><h4 class="text-[11px] font-bold text-gray-400 uppercase tracking-widest mb-1">Last 12 rated runs</h4>${chart}
      <div class="text-[10px] text-gray-500">White dot = won. Hover a dot for the run.</div></div>
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
      ${bandTable('By distance', x => DIST_OF(x.distance), ['≤1100m', '1101–1300m', '1301–1600m', '1601–2000m', '2001m+'], DIST_OF(dist))}
      ${bandTable('By track condition', x => GOING_OF(x.going), ['Good', 'Soft', 'Heavy', 'Synthetic'], going, k => BAND_LABEL[k] || k)}
      ${bandTable('By preparation stage', x => x.race_in_prep >= 5 ? '5th-up+' : STAGE_OF(x.race_in_prep), ['1st-up', '2nd-up', '3rd-up', '4th-up', '5th-up+'], null)}
    </div>
    <p class="text-[10px] text-gray-500 mt-3">"Expected today" weights every rated run by how recent it is (half-life 120 days), whether it was at a similar trip (within 200m full weight, 400m 70%, further 40%) and on the same going (else half), and halves runs with a stewards excuse: the same method the engine uses for Form L. Lengths use ${lpp.toFixed(2)} lengths per rating point at ${dist}m.</p>`;
}
