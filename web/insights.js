/* Insights: sires and stables, the shape of a preparation, ground made late,
 * whether our percentages are honest, and a written review of a meeting.
 * Everything here is computed from runs we hold — nothing is estimated.
 */

const INS = { sires: null, stables: null, kind: 'trainer', calib: null };

// ---------------------------------------------------------------- sires and stables
const pctCell = (v, good = 15, bad = 7) => v === null || v === undefined
  ? '<span class="text-gray-600">–</span>'
  : `<span class="${v >= good ? 'text-emerald-400 font-bold' : v < bad ? 'text-gray-500' : 'text-gray-200'}">${v}%</span>`;

async function loadSires() {
  const box = document.getElementById('sireBody'); if (!box) return;
  box.innerHTML = '<div class="text-sm text-gray-400 p-4">Reading three years of Victorian runs…</div>';
  if (!INS.sires) {
    try { const { data, error } = await sb.rpc('edge_sire_stats', { p_min_runs: 40 }); if (error) throw error; INS.sires = data || []; }
    catch (e) { box.innerHTML = `<div class="text-sm text-amber-300 p-4">This switches on after the next engine run. (${esc(e.message || e)})</div>`; return; }
  }
  const rows = INS.sires.slice().sort((a, b) => b.win_pct - a.win_pct);
  box.innerHTML = `
    <p class="text-[11px] text-gray-500 mb-3">Every sire with 40+ runs in our database over the last three years. The useful columns are the differences: a sire whose progeny win first-up, or go better in the wet than the dry, or sprint but do not get a trip. ${rows.length} sires.</p>
    <div class="overflow-x-auto max-h-[70vh] overflow-y-auto"><table class="w-full text-left font-mono-numbers text-xs">
      <thead class="bg-[#0d1117] text-gray-500 uppercase text-[10px] tracking-wider sticky top-0"><tr>
        <th class="p-2 font-sans">Sire</th><th class="p-2">Runs</th><th class="p-2">Win</th><th class="p-2">Place</th>
        <th class="p-2" data-tip="Strike rate of its progeny first-up from a spell">1st-up</th>
        <th class="p-2" data-tip="Soft, slow or heavy ground">Wet</th><th class="p-2">Dry</th>
        <th class="p-2" data-tip="1300m and under">Sprint</th><th class="p-2" data-tip="1800m and over">Route</th>
        <th class="p-2">Avg rating</th></tr></thead>
      <tbody class="divide-y divide-[#1e2638]">${rows.map(s => `<tr>
        <td class="p-2 font-sans text-white font-bold">${esc(s.sire)}</td><td class="p-2 text-gray-400">${s.runs}</td>
        <td class="p-2">${pctCell(s.win_pct, 13, 6)}</td><td class="p-2 text-gray-300">${s.place_pct}%</td>
        <td class="p-2">${pctCell(s.first_up_win_pct, 15, 6)} <span class="text-gray-600">${s.first_up_runs || 0}</span></td>
        <td class="p-2">${pctCell(s.wet_win_pct, 15, 6)} <span class="text-gray-600">${s.wet_runs || 0}</span></td>
        <td class="p-2">${pctCell(s.dry_win_pct, 15, 6)}</td>
        <td class="p-2">${pctCell(s.sprint_win_pct, 15, 6)}</td><td class="p-2">${pctCell(s.route_win_pct, 15, 6)}</td>
        <td class="p-2 text-gray-300">${s.avg_rating ?? '–'}</td></tr>`).join('')}</tbody></table></div>`;
}

async function loadStables(kind) {
  INS.kind = kind || INS.kind;
  const box = document.getElementById('stableBody'); if (!box) return;
  box.innerHTML = '<div class="text-sm text-gray-400 p-4">Reading three years of Victorian runs…</div>';
  const key = INS.kind;
  if (!INS.stables || INS.stables.kind !== key) {
    try {
      const { data, error } = await sb.rpc('edge_stable_stats', { p_kind: key, p_min_runs: key === 'jockey' ? 100 : 60 });
      if (error) throw error;
      INS.stables = { kind: key, rows: data || [] };
    } catch (e) { box.innerHTML = `<div class="text-sm text-amber-300 p-4">This switches on after the next engine run. (${esc(e.message || e)})</div>`; return; }
  }
  const rows = INS.stables.rows.slice().sort((a, b) => b.win_pct - a.win_pct);
  const best = r => {
    const xs = [['1st-up', r.up1_pct], ['2nd-up', r.up2_pct], ['3rd-up', r.up3_pct], ['4th-up+', r.up4_pct]].filter(x => x[1] !== null);
    if (xs.length < 2) return '';
    xs.sort((a, b) => b[1] - a[1]);
    return xs[0][1] - xs[xs.length - 1][1] >= 6 ? `<span class="text-emerald-300">best ${xs[0][0]}</span>` : '<span class="text-gray-600">even through a prep</span>';
  };
  box.innerHTML = `
    <div class="flex gap-2 mb-3">
      <button onclick="loadStables('trainer')" class="rt-btn ${key === 'trainer' ? 'active' : ''}" style="font-size:11px;padding:6px 12px">Stables</button>
      <button onclick="loadStables('jockey')" class="rt-btn ${key === 'jockey' ? 'active' : ''}" style="font-size:11px;padding:6px 12px">Jockeys</button>
    </div>
    <p class="text-[11px] text-gray-500 mb-3">Three years of Victorian runs. The column that matters is the shape through a preparation: some stables have them ready first-up, others need three runs. ${rows.length} ${key === 'jockey' ? 'jockeys' : 'stables'}.</p>
    <div class="overflow-x-auto max-h-[70vh] overflow-y-auto"><table class="w-full text-left font-mono-numbers text-xs">
      <thead class="bg-[#0d1117] text-gray-500 uppercase text-[10px] tracking-wider sticky top-0"><tr>
        <th class="p-2 font-sans">${key === 'jockey' ? 'Jockey' : 'Stable'}</th><th class="p-2">Runs</th><th class="p-2">Win</th><th class="p-2">Place</th>
        <th class="p-2">1st-up</th><th class="p-2">2nd-up</th><th class="p-2">3rd-up</th><th class="p-2">4th-up+</th>
        <th class="p-2">Wet</th><th class="p-2">Metro</th><th class="p-2 font-sans">Shape</th></tr></thead>
      <tbody class="divide-y divide-[#1e2638]">${rows.map(s => `<tr>
        <td class="p-2 font-sans text-white font-bold">${esc(s.name)}</td><td class="p-2 text-gray-400">${s.runs}</td>
        <td class="p-2">${pctCell(s.win_pct, 15, 7)}</td><td class="p-2 text-gray-300">${s.place_pct}%</td>
        <td class="p-2">${pctCell(s.up1_pct)}</td><td class="p-2">${pctCell(s.up2_pct)}</td>
        <td class="p-2">${pctCell(s.up3_pct)}</td><td class="p-2">${pctCell(s.up4_pct)}</td>
        <td class="p-2">${pctCell(s.wet_pct)}</td><td class="p-2">${pctCell(s.metro_pct)}</td>
        <td class="p-2 font-sans text-[11px]">${best(s)}</td></tr>`).join('')}</tbody></table></div>`;
}

// ---------------------------------------------------------------- the prep clock
// Where a horse sits in this preparation, and where it has done its best work
// before. A horse past the run it has ever won from is a fade the market is slow
// to price; a horse arriving at its best run is the opposite.
function prepClock(r) {
  const runs = parseJSON(r.last_runs, []) || [];
  const here = r.prep_run;
  if (!here && !runs.length) return '';
  // This preparation = the runs since the last spell, newest first in last_runs.
  const thisPrep = [];
  for (const x of runs) {
    if (!x.prep) break;
    thisPrep.push(x);
    if (x.prep === 1) break;
  }
  thisPrep.reverse();
  const byPrep = {};
  runs.forEach(x => { if (x.prep && x.rating) (byPrep[x.prep] = byPrep[x.prep] || []).push(x.rating); });
  const avg = k => byPrep[k] ? byPrep[k].reduce((a, b) => a + b, 0) / byPrep[k].length : null;
  const peaks = Object.keys(byPrep).map(Number).sort((a, b) => avg(b) - avg(a));
  const peak = peaks.length >= 2 ? peaks[0] : null;
  const wins = runs.filter(x => x.pos === 1 && x.prep).map(x => x.prep);
  const deepestWin = wins.length ? Math.max(...wins) : null;
  const dots = [];
  const n = Math.max(here || 0, thisPrep.length, 1);
  for (let i = 1; i <= Math.max(n, 5); i++) {
    const run = thisPrep.find(x => x.prep === i);
    const isNow = i === here;
    const tone = isNow ? 'bg-[#ff6600] text-black' : run ? 'bg-[#1e2638] text-gray-200' : 'bg-[#0d1117] text-gray-600 border border-[#1e2638]';
    dots.push(`<span class="inline-flex flex-col items-center mr-1.5">
      <span class="w-7 h-7 rounded-full ${tone} flex items-center justify-center text-[11px] font-bold" data-tip="${esc(run ? `${run.date || ''} ${run.track || ''} ${run.dist || ''}m · ${ordinalTxt(run.pos)} · rated ${num(run.rating, 1)}` : (isNow ? 'today' : 'no run at this number this preparation'))}">${i}</span>
      <span class="text-[9px] font-mono-numbers ${run && run.rating ? 'text-gray-400' : 'text-transparent'}">${run && run.rating ? num(run.rating, 0) : '–'}</span></span>`);
  }
  let verdict = '';
  if (here && deepestWin && here > deepestWin)
    verdict = `<span class="pill sect-red">↓ run ${here}; has never won past run ${deepestWin}</span>`;
  else if (here && peak && here === peak)
    verdict = `<span class="pill sect-green">↑ this is the run number it rates best at</span>`;
  else if (here && peak && here > peak)
    verdict = `<span class="pill sect-yellow">past its best run (${peak}) this prep</span>`;
  return `<div class="flex flex-wrap items-center gap-2">
      <div class="flex items-end">${dots.join('')}</div>${verdict}
      ${peak ? `<span class="text-[11px] text-gray-500">best run number on record: ${peak}${deepestWin ? ` · deepest win: run ${deepestWin}` : ''}</span>` : ''}
    </div>`;
}

// ---------------------------------------------------------------- ground made
// Where each runner was at the 800m and 400m against where it finished: who was
// making ground and who stopped, without watching a replay.
async function renderGround(raceId) {
  const box = document.getElementById('groundBody'); if (!box) return;
  const race = S.races.find(r => r.race_id === raceId);
  if (!race || !race.result_in) { box.innerHTML = ''; return; }
  box.innerHTML = '<div class="text-[11px] text-gray-500">Loading the run of the race…</div>';
  let runs = [];
  try { const { data, error } = await sb.rpc('edge_race_runs', { p_race_ids: [raceId] }); if (!error) runs = data || []; } catch (e) {}
  const byName = {};
  runs.forEach(x => { byName[String(x.horse_name).toLowerCase()] = x; });
  const rows = (S.runners[raceId] || []).filter(r => !r.scratched && r.finish_pos).map(r => {
    const h = byName[r.horse_name.toLowerCase()] || {};
    return { ...r, pos_800: h.pos_800, pos_400: h.pos_400, settle_pos: h.settle_pos };
  });
  box.innerHTML = groundMade(race, rows);
}

function groundMade(race, rows) {
  const live = (rows || []).filter(r => !r.scratched && !r._scratched && r.finish_pos);
  const withRun = live.filter(r => r.pos_800 || r.pos_400);
  if (!withRun.length) return '<div class="text-[11px] text-gray-500">In-run positions for this race have not arrived yet — they come with the ratings.</div>';
  const n = Math.max(...live.map(r => r.finish_pos || 0), withRun.length);
  const W = 560, H = Math.max(120, live.length * 18 + 30), L = 150, R = 30;
  const X = i => L + i * (W - L - R) / 2;
  const Y = p => 18 + ((p - 1) / Math.max(1, n - 1)) * (H - 40);
  const line = r => {
    const pts = [[0, r.pos_800], [1, r.pos_400], [2, r.finish_pos]].filter(p => p[1]);
    if (pts.length < 2) return '';
    const gain = (r.pos_800 || r.finish_pos) - r.finish_pos;
    const c = gain >= 3 ? '#10b981' : gain <= -3 ? '#ef4444' : '#64748b';
    const d = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p[0])},${Y(p[1])}`).join(' ');
    return `<path d="${d}" stroke="${c}" stroke-width="${r.finish_pos === 1 ? 2.5 : 1.5}" fill="none" opacity="${r.finish_pos <= 4 ? 1 : 0.45}"/>
      <circle cx="${X(2)}" cy="${Y(r.finish_pos)}" r="3" fill="${c}"/>
      <text x="${L - 8}" y="${Y(pts[0][1]) + 3}" text-anchor="end" font-size="10" fill="${r.finish_pos <= 4 ? '#e2e8f0' : '#64748b'}">${esc(r.horse_name)}</text>`;
  };
  return `<svg viewBox="0 0 ${W} ${H}" class="w-full" style="max-height:${H}px">
      ${[0, 1, 2].map(i => `<line x1="${X(i)}" y1="12" x2="${X(i)}" y2="${H - 18}" stroke="#1e2638"/>`).join('')}
      ${['800m', '400m', 'Finish'].map((t, i) => `<text x="${X(i)}" y="${H - 5}" text-anchor="middle" font-size="10" fill="#64748b">${t}</text>`).join('')}
      ${live.map(line).join('')}
    </svg>
    <p class="text-[10px] text-gray-500">Green made at least three places from the 800m, red lost three or more. The eye-catching run is often the one that finished fourth after being last at the 800m.</p>`;
}

// ---------------------------------------------------------------- is our book honest?
// Of the runners we price at 30%, do 30% win? That is the only test of a model
// that matters, and it is the one most tipping services never show.
async function loadCalibration() {
  const box = document.getElementById('calibBody'); if (!box) return;
  box.innerHTML = '<div class="text-sm text-gray-400 p-4">Reading every priced runner we have a result for…</div>';
  let rows = [];
  try {
    const { data, error } = await sb.from('edge_runners')
      .select('race_id,horse_name,p_blend,morning_p,fair_price,market_price,morning_price,finish_pos,result_bsp,scratched')
      .not('finish_pos', 'is', null).limit(20000);
    if (error) throw error;
    rows = (data || []).filter(r => !r.scratched && (r.morning_p || r.p_blend));
  } catch (e) { box.innerHTML = `<div class="text-sm text-amber-300 p-4">Could not read the runners: ${esc(e.message || e)}</div>`; return; }
  const BANDS = [[0, 0.02], [0.02, 0.05], [0.05, 0.10], [0.10, 0.15], [0.15, 0.25], [0.25, 0.40], [0.40, 1.01]];
  const out = BANDS.map(([lo, hi]) => {
    const g = rows.filter(r => { const p = r.morning_p || r.p_blend; return p >= lo && p < hi; });
    const exp = g.reduce((a, r) => a + (r.morning_p || r.p_blend), 0);
    const won = g.filter(r => r.finish_pos === 1).length;
    const mkt = g.reduce((a, r) => a + (r.market_price > 1 ? 1 / r.market_price : 0), 0);
    return { lo, hi, n: g.length, exp, won, mkt };
  }).filter(b => b.n >= 10);
  const tot = out.reduce((a, b) => a + b.n, 0);
  const bar = b => {
    const act = b.n ? b.won / b.n : 0, pred = b.n ? b.exp / b.n : 0;
    const w = v => Math.min(100, v / 0.5 * 100);
    return `<tr class="border-t border-[#1e2638]">
      <td class="p-2 font-mono-numbers">${Math.round(b.lo * 100)}–${Math.round(b.hi * 100)}%</td>
      <td class="p-2 text-gray-400">${b.n.toLocaleString()}</td>
      <td class="p-2 font-mono-numbers text-[#ffa366]">${num(pred * 100, 1)}%</td>
      <td class="p-2 font-mono-numbers ${act >= pred ? 'text-emerald-400' : 'text-red-400'}">${num(act * 100, 1)}%</td>
      <td class="p-2 font-mono-numbers text-gray-400">${num(b.mkt / b.n * 100, 1)}%</td>
      <td class="p-2 w-1/3"><div class="h-3 bg-[#0d1117] rounded relative">
        <div class="absolute h-3 rounded bg-[#ffa366]/40" style="width:${w(pred)}%"></div>
        <div class="absolute h-3 rounded border-r-2 border-white" style="width:${w(act)}%"></div></div></td></tr>`;
  };
  const over = out.filter(b => b.won < b.exp * 0.8).length, under = out.filter(b => b.won > b.exp * 1.25).length;
  box.innerHTML = `
    <p class="text-[11px] text-gray-500 mb-3">Every runner we priced before a race we now have the result for: ${tot.toLocaleString()} runners. If the model is honest, the runners we called 30% chances won about 30% of the time. The pale bar is what we said, the white line is what happened.</p>
    <div class="overflow-x-auto"><table class="w-full text-left text-xs">
      <thead class="bg-[#0d1117] text-gray-500 uppercase text-[10px] tracking-wider"><tr>
        <th class="p-2">Our price band</th><th class="p-2">Runners</th><th class="p-2">We said</th><th class="p-2">Actually won</th><th class="p-2">Market said</th><th class="p-2">&nbsp;</th></tr></thead>
      <tbody>${out.map(bar).join('') || '<tr><td colspan="6" class="p-6 text-center text-gray-500">Not enough graded runners yet.</td></tr>'}</tbody></table></div>
    <p class="text-[11px] mt-2 ${over ? 'text-amber-300' : 'text-gray-500'}">${
      !out.length ? '' : over ? `${over} band${over === 1 ? '' : 's'} where we are over-rating runners — be careful backing those prices.` :
      under ? `${under} band${under === 1 ? '' : 's'} where runners win more than we say — there may be value we are not taking.` :
      'Every band is close to honest. That is what you want before trusting the prices with money.'}</p>`;
}

// ---------------------------------------------------------------- meeting review, written
async function writeMeetingReport() {
  const btn = document.getElementById('reportBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Writing…'; }
  switchTab('ask');
  await askSend(`Write the review of ${(S.meeting || {}).track || 'this meeting'} on ${S.date}. Cover, in this order: how the track played (bias in the draw and run style), the races where the result made sense and where it did not, any horse that rated well above the winning par, hard-luck stories from the stewards' comments and the in-run positions, horses worth following next start with the reason, and what our own book got right and wrong. Keep it tight.`);
  if (btn) { btn.disabled = false; btn.textContent = '✍️ Write the review'; }
}
