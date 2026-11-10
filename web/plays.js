/* The Edge website: plays board, rider/stable tags, trials, Rising Stars and
 * blackbook, the paper-bet Track Record and the Betfair-based Pattern Lab.
 * Loaded after features.js / race-tabs.js / compare.js / bets.js and uses their globals.
 */

const pctTxt = v => (v === null || v === undefined || isNaN(v)) ? '–' : Math.round(v) + '%';
const recTxt = s => { const m = String(s || '').match(/^(\d+):(\d+)-(\d+)-(\d+)/); return m ? { n: +m[1], w: +m[2], p: +m[2] + +m[3] + +m[4] } : null; };
const jsq = s => JSON.stringify(s).replace(/'/g, '&#39;').replace(/"/g, '&quot;');

// ---------------------------------------------------------------- runner row tags
function riderTags(r) {
  const out = [];
  const chip = (t, tip, cls = 'border-[#1e2638] text-gray-400') => `<span class="px-1.5 py-0.5 rounded border text-[10px] font-mono-numbers ${cls}" data-tip="${esc(tip)}">${t}</span>`;
  if (r.jockey_win_pct !== null && r.jockey_win_pct !== undefined)
    out.push(chip(`J ${pctTxt(r.jockey_win_pct)}`, `${r.jockey || 'Jockey'}: ${pctTxt(r.jockey_win_pct)} winners, ${pctTxt(r.jockey_place_pct)} placed from ${r.jockey_rides ?? '?'} rides in the last 12 months`,
      r.jockey_win_pct >= 15 ? 'border-emerald-500/50 text-emerald-300' : r.jockey_win_pct < 6 ? 'border-red-500/40 text-red-300' : undefined));
  if (r.trainer_win_pct !== null && r.trainer_win_pct !== undefined)
    out.push(chip(`T ${pctTxt(r.trainer_win_pct)}`, `${r.trainer || 'Trainer'}: ${pctTxt(r.trainer_win_pct)} winners in the last 12 months`,
      r.trainer_win_pct >= 15 ? 'border-emerald-500/50 text-emerald-300' : r.trainer_win_pct < 6 ? 'border-red-500/40 text-red-300' : undefined));
  const tj = recTxt(r.tj_form);
  if (tj && tj.n >= 5) out.push(chip(`J/T ${Math.round(tj.w / tj.n * 100)}%`, `This jockey for this trainer: ${tj.n} rides, ${tj.w} wins, ${tj.p} placed`,
    tj.w / tj.n >= 0.2 ? 'border-emerald-500/50 text-emerald-300' : undefined));
  if (r.class_move === 'up') out.push(chip(`▲ class`, `Up in class: today's winning par is ${num(r.class_move_pts, 1)} points higher than its last race's`, 'border-amber-500/50 text-amber-300'));
  if (r.class_move === 'down') out.push(chip(`▼ class`, `Down in class: today's winning par is ${num(Math.abs(r.class_move_pts), 1)} points lower than its last race's`, 'border-emerald-500/50 text-emerald-300'));
  if (r.first_starter) out.push(chip('1st starter', 'Has never raced', 'border-sky-500/50 text-sky-300'));
  const tr = parseJSON(r.trials, []);
  if (tr.length) {
    const t = tr[0];
    out.push(chip(`Trial ${t.pos ? ordinalTxt(t.pos) + (t.nrun ? '/' + t.nrun : '') : ''}`, `Latest jump-out/trial: ${t.date || ''} ${t.track || ''} ${t.dist ?? ''}m, ${t.pos ? ordinalTxt(t.pos) + ' of ' + (t.nrun ?? '?') : 'unplaced'}${t.margin ? ', margin ' + Math.abs(t.margin).toFixed(1) + 'L' : ''}. ${tr.length} on file; click the horse for all.`,
      t.pos === 1 ? 'border-emerald-500/50 text-emerald-300' : undefined));
  }
  return out.length ? `<span class="inline-flex flex-wrap gap-1 ml-1 align-middle">${out.join('')}</span>` : '';
}

function betCell(r, race) {
  if (r._scratched) return '<span class="pill sect-red">SCR</span>';
  if (r._value) return '<span class="pill sect-green">✅ VALUE</span>';
  if (r.play_flag && !r._fade) return `<span class="pill sect-green" data-tip="${esc('High-percentage play: ' + (r.play_reasons || ''))}">★ PLAY</span>`;
  if (r._fade) return `<span class="pill sect-red" data-tip="${esc(`The model rates it at ${num(r._p * 100, 1)}% against the market's ${num(r._pmkt * 100, 1)}%. On unseen races these won clearly less often than their price said. Lay candidate, or leave it out of multis.`)}">FADE</span>`;
  return '';
}

// ---------------------------------------------------------------- runner panel blocks
function connectionsBlock(r) {
  const row = (label, form, pct) => { const x = recTxt(form); return `<tr class="border-t border-[#1e2638]"><td class="py-1.5 font-sans text-gray-300">${label}</td><td class="text-right">${x ? `${x.n}: ${x.w}-${x.p - x.w}` : '–'}</td><td class="text-right ${x && x.n >= 5 && x.w / x.n >= 0.2 ? 'text-emerald-400 font-bold' : ''}">${x && x.n ? Math.round(x.w / x.n * 100) + '%' : pct !== undefined && pct !== null ? pctTxt(pct) : '–'}</td></tr>`; };
  return `<table class="w-full font-mono-numbers text-xs"><thead class="text-gray-500 text-[10px] uppercase"><tr><th class="text-left">&nbsp;</th><th class="text-right">Runs: W-P</th><th class="text-right">Win</th></tr></thead><tbody>
    <tr><td class="py-1.5 font-sans text-gray-300">${esc(r.jockey || 'Jockey')} (12 months)</td><td class="text-right">${r.jockey_rides ?? '–'} rides</td><td class="text-right">${pctTxt(r.jockey_win_pct)}</td></tr>
    <tr class="border-t border-[#1e2638]"><td class="py-1.5 font-sans text-gray-300">${esc(r.trainer || 'Trainer')} (12 months)</td><td class="text-right">&nbsp;</td><td class="text-right">${pctTxt(r.trainer_win_pct)}</td></tr>
    ${row('Jockey for this trainer', r.tj_form, r.tj_win_pct)}${row('Jockey on this horse', r.jh_form)}${row('Jockey at this track', r.jockey_track)}${row('Trainer at this track', r.trainer_track)}
  </tbody></table>
  ${r.fk_exp ? `<div class="text-[11px] text-gray-400 mt-2">Form King's own figures: expected <b class="text-white font-mono-numbers">${num(r.fk_exp, 1)}</b> · peak <b class="text-white font-mono-numbers">${num(r.fk_peak, 1)}</b> (a second opinion on our Form L)</div>` : ''}`;
}
function trialsBlock(r) {
  const tr = parseJSON(r.trials, []);
  if (!tr.length) return '<span class="text-gray-500 text-[11px]">No jump-outs or trials on file.</span>';
  return `<table class="w-full font-mono-numbers text-xs"><thead class="text-gray-500 text-[10px] uppercase"><tr><th class="text-left py-1">Date</th><th class="text-left">Track</th><th>Dist</th><th class="text-left">Going</th><th>Fin</th><th>Margin</th><th>Time</th><th class="text-left">Type</th></tr></thead>
    <tbody>${tr.map(t => `<tr class="border-t border-[#1e2638]"><td class="py-1.5 whitespace-nowrap">${esc(t.date || '')}</td><td class="font-sans">${esc(t.track || '')}</td><td class="text-center">${t.dist ?? ''}</td><td>${esc(t.going || '')}</td>
      <td class="text-center ${t.pos === 1 ? 'text-emerald-400 font-bold' : ''}">${t.pos ?? '–'}${t.nrun ? '/' + t.nrun : ''}</td><td class="text-center">${t.margin === null || t.margin === undefined ? '' : Math.abs(t.margin).toFixed(1)}</td>
      <td class="text-center">${t.time_ms ? (t.time_ms / 1000).toFixed(2) + 's' : ''}</td><td class="font-sans text-gray-400">${esc(t.name || '')}</td></tr>`).join('')}</tbody></table>`;
}
function playChecksBlock(r) {
  const c = parseJSON(r.play_checks, null);
  if (!c) return '';
  return `<div class="flex flex-wrap gap-1.5">${(c.ok || []).map(x => `<span class="pill sect-green">✓ ${esc(x)}</span>`).join('')}${(c.miss || []).map(x => `<span class="pill sect-red">✗ ${esc(x)}</span>`).join('')}</div>`;
}
function outOfRace(x) {
  if (x.next_runs === null || x.next_runs === undefined || !x.next_runs) return '<span class="text-gray-600">–</span>';
  const strong = x.next_wins >= 2 || (x.next_runs >= 3 && x.next_wins / x.next_runs >= 0.25);
  return `<span class="${strong ? 'text-emerald-400 font-bold' : x.next_wins ? 'text-gray-200' : 'text-gray-500'}" data-tip="Runners out of this race have had ${x.next_runs} starts since for ${x.next_wins || 0} wins">${x.next_wins || 0}/${x.next_runs}</span>`;
}

// ---------------------------------------------------------------- plays board (meeting page)
function renderPlays() {
  const box = document.getElementById('playsBoard'); if (!box) return;
  const plays = [], near = [], fades = [], watch = [];
  const bb = new Set((S.blackbook || []).map(b => b.horse_name.toLowerCase())), stars = new Set((S.stars || []).map(s => s.horse_name.toLowerCase()));
  S.races.forEach(race => {
    const rows = (S.runners[race.race_id] || []).filter(r => !r._scratched && !r.scratched);
    rows.forEach(r => {
      const key = r.horse_name.toLowerCase();
      if (bb.has(key) || stars.has(key)) watch.push({ race, r, kind: bb.has(key) ? 'Blackbook' : 'Rising star' });
      if (race.result_in) return;
      const c = parseJSON(r.play_checks, null);
      if (r.play_flag && !r._fade) plays.push({ race, r, c });
      else if (c && (r._p || 0) >= 0.25 && (c.miss || []).length === 1 && !r._fade) near.push({ race, r, c });
      if (r._fade) fades.push({ race, r });
    });
  });
  plays.sort((a, b) => (b.r._p || 0) - (a.r._p || 0)); near.sort((a, b) => (b.r._p || 0) - (a.r._p || 0)); fades.sort((a, b) => (a.r._market || 0) - (b.r._market || 0));
  const row = (x, extra = '') => `
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 border-t border-[#1e2638] cursor-pointer hover:bg-white/[.02]" onclick="selectView('${x.race.race_id}')">
      <span class="text-[#ff6600] font-black w-8">R${x.race.race_number}</span>
      <span class="text-white font-bold min-w-[140px]">${x.r.saddlecloth ?? ''}. ${esc(x.r.horse_name)}</span>
      <span class="font-mono-numbers text-xs">${num((x.r._p || 0) * 100, 0)}% · <span class="text-[#ffa366]">${money(x.r._fair)}</span> vs <span class="text-white">${money(x.r._market)}</span></span>
      <span class="text-[11px] text-gray-400">${extra}</span>
    </div>`;
  const card = (title, sub, body, tone) => `<div class="bg-[#11151d] p-5 rounded-xl border ${tone}"><h3 class="text-white font-black text-lg">${title}</h3><p class="text-[11px] text-gray-500 mb-2">${sub}</p>${body}</div>`;
  box.innerHTML = `
    ${watch.length ? `<div class="bg-[#11151d] border border-sky-500/40 rounded-xl p-4 mb-6"><span class="text-sky-300 font-black text-sm uppercase tracking-widest">On this card</span>
      <div class="flex flex-wrap gap-2 mt-2">${watch.map(x => `<button onclick="selectView('${x.race.race_id}')" class="px-2.5 py-1 rounded-md bg-[#0d1117] border border-[#1e2638] text-xs hover:border-sky-400"><span class="text-sky-300">${x.kind}</span> <b class="text-white">${esc(x.r.horse_name)}</b> <span class="text-gray-500">R${x.race.race_number} · ${money(x.r._market)}</span></button>`).join('')}</div></div>` : ''}
    <div class="grid grid-cols-1 xl:grid-cols-3 gap-6">
      ${card('★ High-percentage plays', 'Passes every rule: our chance 25%+, price at or above ours, top-2 form, maps well, suited by the going, no fade angle. Each one is paper-bet automatically and graded in Track Record.',
        plays.map(x => row(x, esc(x.r.play_reasons || ''))).join('') || '<div class="text-gray-500 text-sm py-2">None on this card right now. That is normal: most days have none or one.</div>', 'border-emerald-500/40')}
      ${card('Strong chances, one rule short', 'Our chance 25%+ but failing a single rule. Worth a look; the missing rule is shown.',
        near.slice(0, 8).map(x => row(x, `<span class="text-amber-300">✗ ${esc((x.c.miss || [])[0] || '')}</span>`)).join('') || '<div class="text-gray-500 text-sm py-2">None.</div>', 'border-amber-500/30')}
      ${card('Fades: think twice', 'The model rates these 20%+ below the market\'s own chance. Lay candidates, or leave them out of multis.',
        fades.slice(0, 10).map(x => row(x, `market ${num((x.r._pmkt || 0) * 100, 0)}%`)).join('') || '<div class="text-gray-500 text-sm py-2">None on this card.</div>', 'border-red-500/30')}
    </div>`;
}

// ---------------------------------------------------------------- Rising Stars + blackbook
async function loadWatchlists() {
  try {
    const [{ data: st }, { data: bk }] = await Promise.all([
      sb.from('edge_stars').select('*').order('score', { ascending: false }),
      sb.from('edge_blackbook').select('*').eq('removed', 0).order('created_at', { ascending: false })]);
    S.stars = st || []; S.blackbook = bk || [];
  } catch (e) { S.stars = S.stars || []; S.blackbook = S.blackbook || []; }
  const n = document.getElementById('starsBadge');
  if (n) { const on = entriesToday().length; n.textContent = on ? on : ''; n.classList.toggle('hidden', !on); }
}
function entriesToday() {
  const names = new Set([...(S.stars || []), ...(S.blackbook || [])].map(x => x.horse_name.toLowerCase()));
  const out = [];
  S.races.forEach(race => (S.runners[race.race_id] || []).forEach(r => { if (!r.scratched && !r._scratched && names.has(r.horse_name.toLowerCase())) out.push({ race, r }); }));
  return out;
}
async function upcomingFor(names) {
  if (!names.length) return {};
  const out = {};
  for (let i = 0; i < names.length; i += 80) {
    const { data } = await sb.from('edge_runners').select('race_id,horse_name,market_price,fair_price,scratched').in('horse_name', names.slice(i, i + 80));
    const ids = [...new Set((data || []).map(x => x.race_id))];
    if (!ids.length) continue;
    const { data: rc } = await sb.from('edge_races').select('race_id,meeting_id,meeting_date,race_number,result_in').in('race_id', ids).gte('meeting_date', melbDate());
    const R = Object.fromEntries((rc || []).map(x => [x.race_id, x]));
    (data || []).forEach(x => { if (R[x.race_id] && !x.scratched && !R[x.race_id].result_in) out[x.horse_name] = { ...x, race: R[x.race_id] }; });
  }
  return out;
}
async function blackbookSet(name, on, source = '') {
  let note = '';
  const res = await fetch('/api/blackbook' + (on ? '' : '?remove=1'), { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ horse_name: name, note, added_by: lsGet('edge_bettor') || '', source, pin: lsGet('edge_bet_pin') || '' }) });
  if (!res.ok) { status('Blackbook not saved: ' + ((await res.json().catch(() => ({}))).error || res.status), 'red'); return; }
  await loadWatchlists(); renderStars();
  const b = document.getElementById('bbBtn'); if (b) b.outerHTML = bbButton(name);
}
const inBlackbook = name => (S.blackbook || []).some(b => b.horse_name.toLowerCase() === String(name).toLowerCase());
function bbButton(name) {
  const on = inBlackbook(name);
  return `<button id="bbBtn" onclick='blackbookSet(${jsq(name)}, ${!on}, "horse page")' class="text-xs font-bold border rounded-lg px-3 py-1.5 ${on ? 'text-sky-300 border-sky-500/50 bg-sky-500/10' : 'text-gray-300 border-[#1e2638] hover:border-sky-400'}">${on ? '★ In blackbook' : '☆ Add to blackbook'}</button>`;
}
async function renderStars() {
  const box = document.getElementById('starsBody'); if (!box) return;
  if (!S.stars) { box.innerHTML = '<div class="text-gray-400 text-sm">Loading…</div>'; await loadWatchlists(); }
  const names = [...new Set([...(S.stars || []), ...(S.blackbook || [])].map(x => x.horse_name))];
  const up = await upcomingFor(names);
  const next = n => up[n] ? `<button onclick="goRace('${up[n].race.meeting_date}', '${up[n].race.meeting_id}', '${up[n].race_id}')" class="pill sect-green py-1">RUNS ${up[n].race.meeting_date === melbDate() ? 'TODAY' : esc(up[n].race.meeting_date)} R${up[n].race.race_number} · ${money(up[n].market_price)}</button>` : '';
  const horse = n => `<button class="text-white font-bold hover:text-[#ff6600]" onclick='openHorse(${jsq(n)})'>${esc(n)}</button>`;
  const stars = (S.stars || []).map((s, i) => `
    <tr class="border-t border-[#1e2638]">
      <td class="py-2.5 pr-2 text-gray-500">${i + 1}</td>
      <td class="pr-3">${horse(s.horse_name)} ${next(s.horse_name)}<div class="text-[10px] text-gray-500">${esc(s.trainer || '')}${s.sire ? ' · by ' + esc(s.sire) : ''}</div></td>
      <td class="px-2 text-center">${s.career_starts}: ${s.wins}</td>
      <td class="px-2 font-mono-numbers text-center text-gray-300">${esc((s.ratings || '').split(',').join(' → '))}</td>
      <td class="px-2 text-center font-mono-numbers ${s.vs_par_l >= 0 ? 'text-emerald-400 font-bold' : 'text-amber-300'}">${signed(s.vs_par_l, 1, 'L')}</td>
      <td class="px-2 text-[11px] text-gray-400">${esc(s.last_date || '')} ${esc(s.last_track || '')} ${s.last_distance ?? ''}m · ${ordinalTxt(s.last_pos)}</td>
      <td class="px-2 text-[11px] text-gray-300">${esc(s.reasons || '')}</td>
      <td class="pl-2 text-right"><button onclick='blackbookSet(${jsq(s.horse_name)}, ${!inBlackbook(s.horse_name)}, "rising stars")' class="text-sky-300 text-lg" title="${inBlackbook(s.horse_name) ? 'Remove from blackbook' : 'Add to blackbook'}">${inBlackbook(s.horse_name) ? '★' : '☆'}</button></td>
    </tr>`).join('');
  const bb = (S.blackbook || []).map(b => `
    <div class="flex flex-wrap items-center justify-between gap-2 py-2 border-t border-[#1e2638] text-xs">
      <span>${horse(b.horse_name)} ${next(b.horse_name)} <span class="text-gray-500">${esc(b.added_by || '')}${b.source ? ' · from ' + esc(b.source) : ''} · ${esc((b.created_at || '').slice(0, 10))}</span></span>
      <button onclick='blackbookSet(${jsq(b.horse_name)}, false)' class="text-gray-500 hover:text-red-400">remove</button>
    </div>`).join('');
  box.innerHTML = `
    <div class="bg-[#11151d] border border-sky-500/30 rounded-xl p-6 shadow-2xl">
      <h2 class="text-white font-black text-2xl uppercase tracking-widest mb-1">Blackbook</h2>
      <p class="text-[11px] text-gray-500 mb-2">Horses the syndicate is following. A green button appears when one is on a card we've loaded. Add from any horse page (☆) or the list below.</p>
      ${bb || '<div class="text-sm text-gray-500 py-2">Empty. Tap ☆ on a rising star or on any horse page.</div>'}
    </div>
    <div class="bg-[#11151d] border border-[#1e2638] rounded-xl p-6 shadow-2xl">
      <h2 class="text-white font-black text-2xl uppercase tracking-widest mb-1">Rising Stars</h2>
      <p class="text-[11px] text-gray-500 mb-3">Lightly raced (8 starts or fewer), raced in the last 60 days, latest run a new peak or ratings climbing, and within 1.5 lengths of the winning par for its class. Ranked by a score that rewards lengths above par, the size of the jump, winning and winners out of the race. Rebuilt every sync.</p>
      <div class="overflow-x-auto"><table class="w-full text-left text-xs">
        <thead class="text-gray-500 uppercase text-[10px]"><tr><th class="py-2">#</th><th>Horse</th><th class="px-2 text-center">Starts: wins</th><th class="px-2 text-center">Ratings (old → new)</th><th class="px-2 text-center">Last vs par</th><th class="px-2">Last run</th><th class="px-2">Why</th><th></th></tr></thead>
        <tbody>${stars || '<tr><td colspan="8" class="py-6 text-center text-gray-500">No horse meets the bar yet. The list fills as ratings for recent runs arrive.</td></tr>'}</tbody></table></div>
    </div>`;
}
async function goRace(dateStr, meetingId, raceId) {
  switchTab('racing');
  if (S.date !== dateStr) await loadMeetings(dateStr);
  if (!S.meeting || S.meeting.meeting_id !== meetingId) await loadMeeting(meetingId);
  selectView(raceId);
}

// ---------------------------------------------------------------- Track Record (paper bets)
const REC = { kind: 'play', data: null };
const KIND_INFO = {
  play: ['★ Plays', 'High-percentage plays, struck the first time each was flagged.'],
  value: ['✅ Value flags', 'Edge 20%+ at $2.20 to $18.'],
  top: ['Top of our book', 'Our most likely winner in every race: the baseline.'],
  fade: ['Fades', 'Runners the model rated 20%+ below the market. These are graded as horses to AVOID: fewer winners than the price implied is the goal.'],
};
async function loadRecord() {
  const box = document.getElementById('recordBody');
  box.innerHTML = '<div class="p-6 text-gray-400 text-sm">Grading the paper bets…</div>';
  const { data: bets, error } = await sb.from('edge_paper_bets').select('*').order('flagged_at', { ascending: false }).limit(5000);
  if (error) { box.innerHTML = `<div class="p-6 text-amber-300 text-sm">The paper-bet ledger switches on after the next engine run. (${esc(error.message)})</div>`; return; }
  const ids = [...new Set((bets || []).map(b => b.race_id))];
  const res = {}, races = {};
  for (let i = 0; i < ids.length; i += 100) {
    const [{ data: rs }, { data: ra }] = await Promise.all([
      sb.from('edge_runners').select('race_id,horse_name,finish_pos,result_bsp,result_sp,scratched').in('race_id', ids.slice(i, i + 100)),
      sb.from('edge_races').select('race_id,result_in,commission').in('race_id', ids.slice(i, i + 100))]);
    (rs || []).forEach(r => { res[r.race_id + '|' + r.horse_name] = r; });
    (ra || []).forEach(r => { races[r.race_id] = r; });
  }
  REC.data = (bets || []).map(b => {
    const r = res[b.race_id + '|' + b.horse_name], race = races[b.race_id] || {};
    const done = race.result_in && r && r.finish_pos && !r.scratched;
    const stake = stakeFor(b.price), win = done && r.finish_pos === 1;
    const bsp = done ? r.result_bsp : null, stB = bsp ? stakeFor(bsp) : null;
    return { ...b, done, win, pos: r ? r.finish_pos : null, scratched: r && r.scratched, stake, pl: done ? (win ? stake * (b.price - 1) : -stake) : null,
             bsp, stB, plB: bsp ? (win ? stB * (bsp - 1) * (1 - (race.commission ?? 0.08)) : -stB) : null, clv: bsp ? b.price / bsp - 1 : null };
  });
  renderRecord();
}
function renderRecord() {
  const box = document.getElementById('recordBody');
  const all = REC.data || [], list = all.filter(b => b.kind === REC.kind), g = list.filter(b => b.done);
  const n = g.length, wins = g.filter(b => b.win).length, st = g.reduce((a, b) => a + b.stake, 0), pl = g.reduce((a, b) => a + b.pl, 0);
  const exp = g.reduce((a, b) => a + (b.p || 0), 0), expM = g.reduce((a, b) => a + (b.p_market || 0), 0);
  const gb = g.filter(b => b.plB !== null), stB = gb.reduce((a, b) => a + b.stB, 0), plB = gb.reduce((a, b) => a + b.plB, 0);
  const clv = g.map(b => b.clv).filter(v => v !== null);
  const beat = clv.filter(v => v > 0).length;
  const fade = REC.kind === 'fade';
  const tile = (l, v, sub = '', tone = 'text-white') => `<div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3"><div class="text-[10px] text-gray-500 uppercase tracking-widest">${l}</div><div class="text-xl font-black font-mono-numbers ${tone}">${v}</div><div class="text-[10px] text-gray-500">${sub}</div></div>`;
  const tabs = Object.entries(KIND_INFO).map(([k, [l]]) => `<button onclick="REC.kind='${k}';renderRecord()" class="rt-btn ${REC.kind === k ? 'active' : ''}" style="font-size:11px;padding:6px 12px">${l} <span class="opacity-60">${all.filter(b => b.kind === k).length}</span></button>`).join('');
  const target = 500, prog = Math.min(100, n / target * 100);
  const money0 = v => (v >= 0 ? '+$' : '−$') + Math.abs(Math.round(v)).toLocaleString();
  box.innerHTML = `
    <div class="flex flex-wrap gap-2 mb-3">${tabs}</div>
    <p class="text-[11px] text-gray-500 mb-3">${KIND_INFO[REC.kind][1]} Written to the ledger automatically before the race at the published price and never changed. Staking: to win $100, capped at $75.</p>
    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 mb-3">
      ${tile('Graded', n, `${list.length - n} pending`)}
      ${tile('Winners', `${wins} (${n ? Math.round(wins / n * 100) : 0}%)`, fade ? `price implied ${num(expM, 1)}` : `we expected ${num(exp, 1)}`, fade ? (wins < expM ? 'text-emerald-400' : 'text-red-400') : (wins >= exp ? 'text-emerald-400' : 'text-white'))}
      ${tile(fade ? 'If you had backed them' : 'Profit / loss', n ? money0(pl) : '–', `on $${Math.round(st).toLocaleString()} at our published price`, fade ? (pl < 0 ? 'text-emerald-400' : 'text-red-400') : (pl >= 0 ? 'text-emerald-400' : 'text-red-400'))}
      ${tile('ROI', st ? signed(pl / st * 100, 1, '%') : '–', 'published price')}
      ${tile('ROI at Betfair SP', stB ? signed(plB / stB * 100, 1, '%') : '–', `after commission, ${gb.length} bets`, plB >= 0 ? 'text-emerald-400' : 'text-white')}
      ${tile('Beat the Betfair SP', clv.length ? `${Math.round(beat / clv.length * 100)}%` : '–', clv.length ? `avg ${signed(clv.reduce((a, b) => a + b, 0) / clv.length * 100, 1, '%')} better or worse` : 'of bets')}
      ${tile('Proof progress', `${n}/${target}`, `<div class="h-1.5 bg-[#1e2638] rounded mt-1"><div class="h-1.5 rounded bg-[#ff6600]" style="width:${prog}%"></div></div>`)}
    </div>
    <div class="overflow-x-auto"><table class="w-full text-left font-mono-numbers text-xs">
      <thead class="bg-[#0d1117] text-gray-500 uppercase text-[10px] tracking-wider"><tr><th class="p-3">Date</th><th class="p-3 font-sans">Race</th><th class="p-3 font-sans">Horse</th><th class="p-3">Price</th><th class="p-3">Ours</th><th class="p-3">BSP</th><th class="p-3">Fin</th><th class="p-3">Stake</th><th class="p-3">P/L</th><th class="p-3 font-sans">Why</th></tr></thead>
      <tbody class="divide-y divide-[#1e2638]">${list.slice(0, 400).map(b => `
        <tr><td class="p-3 whitespace-nowrap">${esc(b.meeting_date || '')}</td><td class="p-3 font-sans whitespace-nowrap">${esc(b.track || '')} R${b.race_number ?? ''}</td>
          <td class="p-3 font-sans text-white font-bold">${b.saddlecloth ?? ''}. ${esc(b.horse_name)}</td><td class="p-3">${money(b.price)}</td><td class="p-3 text-[#ffa366]">${money(b.fair_price)}</td>
          <td class="p-3">${money(b.bsp)}${b.clv !== null ? ` <span class="${b.clv > 0 ? 'text-emerald-400' : 'text-gray-500'}">${signed(b.clv * 100, 0, '%')}</span>` : ''}</td>
          <td class="p-3 ${b.win ? 'text-emerald-400 font-bold' : ''}">${b.scratched ? 'SCR' : b.done ? b.pos : '…'}</td><td class="p-3">$${num(b.stake, 2)}</td>
          <td class="p-3 ${b.pl > 0 ? 'text-emerald-400' : b.pl < 0 ? 'text-red-400' : 'text-gray-500'}">${b.pl === null ? '–' : (b.pl >= 0 ? '+' : '−') + '$' + num(Math.abs(b.pl), 2)}</td>
          <td class="p-3 font-sans text-[11px] text-gray-400">${esc(b.reasons || '')}</td></tr>`).join('') || '<tr><td colspan="10" class="p-8 text-center text-gray-500">Nothing in this list yet. It fills from the next sync.</td></tr>'}</tbody></table></div>
    <p class="text-[10px] text-gray-500 mt-2">What "proven" means here: 500+ graded bets, more winners than expected, a positive return at the Betfair SP after commission, and beating the Betfair SP more often than not. Until then treat every list as a test, not a tip.</p>`;
}

// ---------------------------------------------------------------- Pattern Lab (Betfair, unbiased)
async function loadLab() {
  const box = document.getElementById('labBody');
  box.innerHTML = '<div class="p-6 text-gray-400 text-sm">Loading the models and the study…</div>';
  const get = async name => { try { const { data, error } = await sb.rpc('edge_model_report', { p_name: name }); return (!error && data && data[0]) ? JSON.parse(data[0].params_json) : null; } catch (e) { return null; } };
  const [v3, v2, ang] = await Promise.all([get('v3'), get('v2'), get('angles_bf')]);
  const tile = (l, v, sub = '', tone = 'text-white') => `<div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3"><div class="text-[10px] text-gray-500 uppercase tracking-widest">${l}</div><div class="text-xl font-black font-mono-numbers ${tone}">${v}</div><div class="text-[10px] text-gray-500">${sub}</div></div>`;
  const pill = (on, yes, no) => `<span class="pill ${on ? 'sect-green' : 'sect-yellow'} py-1">${on ? yes : no}</span>`;
  const bars = (imp, desc) => { const xs = Object.entries(imp || {}).filter(([k]) => k !== 'mkt' && k !== 'has_fk').sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 16); const mx = Math.max(0.01, ...xs.map(([, v]) => Math.abs(v)));
    return `<div class="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1">${xs.map(([k, v]) => `<div class="flex items-center gap-2 text-xs"><span class="w-52 text-gray-300">${esc(desc[k] || k)}</span><div class="flex-1 h-2 bg-[#0d1117] rounded relative"><div class="absolute top-0 h-2 rounded ${v >= 0 ? 'bg-emerald-500 left-1/2' : 'bg-red-500 right-1/2'}" style="width:${Math.abs(v) / mx * 50}%"></div></div><span class="w-12 text-right font-mono-numbers ${v >= 0 ? 'text-emerald-400' : 'text-red-400'}">${v >= 0 ? '+' : ''}${v.toFixed(2)}</span></div>`).join('')}</div>`; };
  const D3 = { first_start: 'First starter', log_days: 'Days since last run', spell: 'First-up from a spell', backup: 'Backing up in 10 days', prep2: '2nd-up', prep3: '3rd-up', prep4: '4th-up or deeper', last_win: 'Won last start', last_place: 'Placed last start', last_logp: 'Well fancied last start', short_beaten: 'Beaten at $3.50 or shorter last start', wins3: 'Wins in last 3', places3: 'Placings in last 3', career_wr: 'Career win rate', runs_cap: 'More experienced', light: 'Lightly raced (1-3 runs)', up_trip: 'Up 200m+ in trip', down_trip: 'Down 200m+ in trip', same_track: 'Same track as last start', travel: 'Last start interstate', mdn_grad: 'Out of maidens today', gap_l: 'Form L (rating vs par)', no_form: 'No rated runs', rel: 'Depth of rated form', last_l: 'Last start rating vs par', best3_l: 'Best of last 3 vs par', trend: 'Ratings trend', close_last: 'Just beaten last start', excuse_last: 'Excuse last start', going_suit: 'Suited by the going', early: 'Settles back', barrier_frac: 'Wide barrier' };
  const perfRow = (label, p) => p && p.n ? `<tr class="border-t border-[#1e2638]"><td class="py-1.5 font-sans text-gray-200">${label}</td><td class="text-right">${p.n.toLocaleString()}</td><td class="text-right">${p.strike}%</td><td class="text-right">$${p.avg_bsp}</td><td class="text-right ${p.ae_vs_bsp >= 1 ? 'text-emerald-400' : 'text-gray-300'}">${p.ae_vs_bsp}</td><td class="text-right ${p.roi_bsp_net >= 0 ? 'text-emerald-400 font-bold' : 'text-red-400'}">${p.roi_bsp_net >= 0 ? '+' : ''}${p.roi_bsp_net}%</td></tr>` : '';
  let h = '';
  if (v3) {
    const P = v3.perf || {};
    h += `<div class="bg-[#0d1117]/60 border border-[#1e2638] rounded-xl p-4 mb-5">
      <div class="flex flex-wrap items-center gap-2 mb-3"><h3 class="text-white font-black text-lg">Model v3: complete fields from Betfair</h3>
        ${pill(v3.use_for_pricing, 'PRICING THE CARDS', 'NOT PRICING YET')}${pill(v3.overlays_proven, 'OVERLAYS PROVEN', 'OVERLAYS NOT PROVEN')}${pill(v3.fades_proven, 'FADES PROVEN', 'FADES NOT PROVEN')}
        <span class="text-[11px] text-gray-500">fitted ${esc((v3.fitted_at || '').slice(0, 10))} · trained on ${Number(v3.n_train_races).toLocaleString()} races · tested on ${Number(v3.n_test_races).toLocaleString()} it never saw</span></div>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
        ${tile('Better than the Betfair SP?', `${v3.gain_pct >= 0 ? '+' : ''}${v3.gain_pct}%`, `95% range ${(v3.gain_ci || []).map(x => x === null ? '–' : (x >= 0 ? '+' : '') + Number(x).toFixed(4)).join(' to ')} per race`, (v3.gain_ci || [0])[0] > 0 ? 'text-emerald-400' : 'text-amber-300')}
        ${tile('Its top pick', P.top_pick ? P.top_pick.strike + '%' : '–', P.top_pick ? `wins · ROI ${P.top_pick.roi_bsp_net}% (favourite: ${P.favourite ? P.favourite.strike + '%, ' + P.favourite.roi_bsp_net + '%' : '–'})` : '')}
        ${tile('Strong chances (25%+)', P.strong_25 ? P.strong_25.strike + '%' : '–', P.strong_25 ? `${P.strong_25.n.toLocaleString()} bets · ROI ${P.strong_25.roi_bsp_net}% at BSP` : '', P.strong_25 && P.strong_25.roi_bsp_net >= 0 ? 'text-emerald-400' : 'text-white')}
        ${(f => tile('Fades', f ? 'A/E ' + f.ae_vs_bsp : '–', f ? `${f.n.toLocaleString()} runs we hold form for · backing them returned ${f.roi_bsp_net}%` : '', f && f.ae_vs_bsp < 0.95 ? 'text-emerald-400' : 'text-white'))((P.fades_120_fk && P.fades_120_fk.n >= 300) ? P.fades_120_fk : P.fades_120)}
      </div>
      <div class="overflow-x-auto mb-3"><table class="w-full font-mono-numbers text-xs"><thead class="text-gray-500 text-[10px] uppercase"><tr><th class="text-left py-1">Backing at Betfair SP after 8% commission (unseen races)</th><th class="text-right">Bets</th><th class="text-right">Strike</th><th class="text-right">Avg BSP</th><th class="text-right" title="Winners vs what the Betfair SP implied">A/E</th><th class="text-right">ROI</th></tr></thead><tbody>
        ${perfRow('Every favourite', P.favourite)}${perfRow("Model's top pick", P.top_pick)}${perfRow('Strong chances: model 25%+ and above the market', P.strong_25)}${perfRow('…in Victoria only', P.strong_25_vic)}
        ${perfRow('Overlays: model 10%+ above market, $2.20-$18', P.overlays_110)}${perfRow('Overlays: model 20%+ above market', P.overlays_120)}${perfRow('…in Victoria only', P.overlays_120_vic)}
        ${perfRow('Overlays on runners we hold form for', P.overlays_120_fk)}${perfRow('Fades: model 20%+ below market', P.fades_120)}${perfRow('Fades on runners we hold form for', P.fades_120_fk)}${perfRow('…in Victoria only', P.fades_120_vic)}${perfRow('Every runner $2.20-$18', P.all_in_band)}</tbody></table></div>
      <div class="text-[10px] text-gray-500 uppercase tracking-widest mb-1">What it learned beyond the price (green = wins more than the price says)</div>${bars(v3.importance_per_sd, D3)}
      <p class="text-[10px] text-gray-500 mt-2">Learns from every runner in every Australian race since ${esc(v3.train_from)} (no survivorship), with our Form King ratings added where we hold them (${Math.round((v3.has_fk_share_test || 0) * 100)}% of test runners). It prices the cards only when the gain over the market is positive with 95% confidence. Refits weekly.</p></div>`;
  }
  if (ang && ang.rows) {
    const verdict = r => (r.ae_old >= 1.03 && r.ae_recent >= 1.03) ? '<span class="pill sect-green">MARKET UNDER-RATES</span>' : (r.ae_old !== null && r.ae_recent !== null && r.ae_old <= 0.97 && r.ae_recent <= 0.97) ? '<span class="pill sect-red">MARKET OVER-RATES</span>' : '<span class="pill bg-[#11151d] border border-[#1e2638] text-gray-400">FAIRLY PRICED</span>';
    const c = v => v === null || v === undefined ? '–' : v;
    h += `<h3 class="text-white font-black text-lg mb-1">Pattern Lab: Victoria, every runner</h3>
      <p class="text-sm text-gray-300 mb-3">${Number(ang.runs).toLocaleString()} runs in ${Number(ang.races).toLocaleString()} Victorian races since ${esc(ang.since)}, from Betfair's complete results. A/E compares actual winners with what the <b class="text-white">Betfair SP</b> implied (1.00 = fairly priced). ROI is backing every one at Betfair SP after 8% commission. A pattern only counts when it holds in both periods.</p>
      <div class="overflow-x-auto"><table class="w-full text-left font-mono-numbers text-xs">
        <thead class="bg-[#0d1117] text-gray-500 uppercase text-[10px] tracking-wider"><tr><th class="p-3 font-sans">Pattern</th><th class="p-3">Runs (older | recent)</th><th class="p-3">A/E older</th><th class="p-3">A/E recent</th><th class="p-3">ROI older</th><th class="p-3">ROI recent</th><th class="p-3">Strike</th><th class="p-3">Verdict</th></tr></thead>
        <tbody class="divide-y divide-[#1e2638]">${ang.rows.map(r => `<tr><td class="p-3 font-sans text-white font-bold">${esc(r.angle)}</td><td class="p-3 text-gray-400">${Number(r.n_old).toLocaleString()} | ${Number(r.n_recent).toLocaleString()}</td>
          <td class="p-3 ${r.ae_old >= 1 ? 'text-emerald-400' : 'text-red-400'}">${c(r.ae_old)}</td><td class="p-3 ${r.ae_recent >= 1 ? 'text-emerald-400' : 'text-red-400'}">${c(r.ae_recent)}</td>
          <td class="p-3 ${r.roi_old >= 0 ? 'text-emerald-400' : 'text-gray-400'}">${c(r.roi_old)}%</td><td class="p-3 ${r.roi_recent >= 0 ? 'text-emerald-400' : 'text-gray-400'}">${c(r.roi_recent)}%</td><td class="p-3">${c(r.strike)}%</td><td class="p-3">${verdict(r)}</td></tr>`).join('')}</tbody></table></div>
      <p class="text-[10px] text-gray-500 mt-2">Split at ${esc(ang.split)}. This replaces the earlier study, which used our own history and was skewed towards horses that kept racing.</p>`;
  }
  if (v2) h += `<details class="mt-5"><summary class="text-xs text-gray-400 cursor-pointer">Model v2 (our Form King history only)</summary><div id="modelCard" class="bg-[#0d1117]/60 border border-[#1e2638] rounded-xl p-4 mt-2"></div></details>`;
  box.innerHTML = h || '<div class="text-sm text-gray-400">The models have not been fitted yet.</div>';
  if (v2) modelCard();
}

// Tags on the cards follow the unbiased study once it exists: a pattern keeps its
// ▲ / ▼ only if Betfair's complete results agree in both periods.
async function syncAngleTags() {
  try {
    const { data, error } = await sb.rpc('edge_model_report', { p_name: 'angles_bf' });
    if (error || !data || !data[0]) return;
    const rows = JSON.parse(data[0].params_json).rows || [];
    const map = { 'Won last start': 'Won last start', 'Up 200m+ in trip': 'Up 200m+ in trip', 'Down 200m+ in trip': 'Down 200m+ in trip' };
    Object.entries(map).forEach(([bf, mine]) => {
      const r = rows.find(x => x.angle === bf), i = ANGLE_INFO[mine];
      if (!r || !i || r.ae_old === null || r.ae_recent === null) return;
      i.old = r.ae_old; i.recent = r.ae_recent;
      i.side = (r.ae_old >= 1.03 && r.ae_recent >= 1.03) ? 'back' : (r.ae_old <= 0.97 && r.ae_recent <= 0.97) ? 'fade' : 'neutral';
    });
    if (ANGLE_INFO['Led and won last start'] && ANGLE_INFO['Won last start']) ANGLE_INFO['Led and won last start'].side = ANGLE_INFO['Won last start'].side;
    ['Priced $3 to $6', 'Priced $25+', 'Hard-luck excuse last start (stewards)', 'Beaten 1L or less last start'].forEach(k => { if (ANGLE_INFO[k]) ANGLE_INFO[k].side = 'neutral'; });
    if (typeof renderView === 'function' && S.races.length) renderView();
  } catch (e) {}
}

// ---------------------------------------------------------------- one past race
// A last-start line opens the race it came out of: the whole field, what each
// one rated that day, where they were at the 800m and 400m, and what they have
// done since. This is how you tell a strong race from a weak one.
function pastOverlay() {
  let ov = document.getElementById('pastOverlay');
  if (!ov) {
    ov = document.createElement('div');
    ov.id = 'pastOverlay';
    ov.className = 'fixed inset-0 z-50 bg-black/70 backdrop-blur-sm overflow-y-auto hidden';
    ov.innerHTML = `<div class="min-h-full flex items-start justify-center p-3 md:p-8" onclick="if(event.target===this)closePast()">
        <div class="bg-[#11151d] border border-[#1e2638] rounded-xl shadow-2xl w-full max-w-6xl p-5 md:p-7">
          <div class="flex justify-end"><button onclick="closePast()" class="text-gray-400 hover:text-white text-2xl leading-none">&times;</button></div>
          <div id="pastBody"></div>
        </div></div>`;
    document.body.appendChild(ov);
  }
  return ov;
}
function closePast() { const o = document.getElementById('pastOverlay'); if (o) o.classList.add('hidden'); document.body.style.overflow = ''; }

async function openPastRace(raceId, horse) {
  if (!raceId) return;
  const ov = pastOverlay(); ov.classList.remove('hidden'); document.body.style.overflow = 'hidden';
  const body = document.getElementById('pastBody');
  body.innerHTML = '<div class="p-10 text-center text-gray-400">Loading the race…</div>';
  let rows = [];
  try { const { data, error } = await sb.rpc('edge_past_race', { p_race_id: raceId }); if (error) throw error; rows = data || []; } catch (e) { rows = []; }
  renderPastRace(raceId, horse, rows);
}

function renderPastRace(raceId, horse, rows) {
  const body = document.getElementById('pastBody');
  if (!rows.length) {
    body.innerHTML = `<h2 class="text-white font-black text-xl mb-2">We don't hold that race yet</h2>
      <p class="text-sm text-gray-400">${esc(raceId)} isn't in the history database. Meetings are pulled as they're raced, and older ones as they're backfilled — press Sync Data after racing, or ask for that meeting to be pulled.</p>`;
    return;
  }
  const h = rows[0];
  const rated = rows.filter(r => r.wfa_rating);
  const best = rated.length ? Math.max(...rated.map(r => r.wfa_rating)) : null;
  const winner = rows.find(r => r.finish_pos === 1);
  const since = rows.reduce((a, r) => a + (r.next_wins || 0), 0);
  const sinceRuns = rows.reduce((a, r) => a + (r.next_runs || 0), 0);
  const strongest = rated.slice().sort((a, b) => b.wfa_rating - a.wfa_rating).slice(0, 3).map(r => r.horse_name);
  const cls = v => v === null || v === undefined || best === null ? 'text-gray-300'
    : v >= best - 1 ? 'text-emerald-400 font-bold' : v >= best - 4 ? 'text-emerald-300' : v >= best - 8 ? 'text-amber-300' : 'text-red-400';
  const chip = (t, tip = '') => `<span class="pill bg-[#0d1117] border border-[#1e2638] text-gray-300 text-[11px] py-1" data-tip="${esc(tip)}">${t}</span>`;
  body.innerHTML = `
    <h2 class="text-white font-black text-2xl">${esc(h.track || '')} ${h.race_number ? 'R' + h.race_number : ''} · ${esc(h.race_date || '')}</h2>
    <div class="text-sm text-gray-400 mb-2">${esc(h.race_name || '')}</div>
    <div class="flex flex-wrap gap-1.5 mb-4">
      ${chip(`📏 ${h.distance ?? '–'}m`)}${h.restrictions ? chip(`🏷️ ${esc(h.restrictions)}`) : ''}${h.going ? chip(`🌤️ ${esc(h.going)}`) : ''}
      ${h.rail ? chip(`🛤️ ${esc(h.rail)}`) : ''}${h.prize_money ? chip(`💰 $${Math.round(h.prize_money).toLocaleString()}`) : ''}
      ${chip(`${rows.length} runners on file${h.field_size && h.field_size > rows.length ? ' of ' + h.field_size : ''}`, 'What we hold for this race. Fewer than the field means the rest have not been pulled yet.')}
      ${best !== null ? chip(`⭐ Best rating ${num(best, 1)}`, 'The highest rating run in the race — often not the winner') : ''}
      ${sinceRuns ? chip(`🏆 ${since} winner${since === 1 ? '' : 's'} out of it since`, `${sinceRuns} starts by these runners since this race`) : ''}
    </div>
    ${winner && best !== null && winner.wfa_rating && winner.wfa_rating < best - 0.5
      ? `<p class="text-[11px] text-amber-300 mb-3">The winner wasn't the best run in the race — ${esc(strongest[0])} rated higher. Worth a look next start.</p>` : ''}
    <div class="overflow-x-auto"><table class="w-full text-left font-mono-numbers text-xs">
      <thead class="bg-[#0d1117] text-gray-500 uppercase text-[10px] tracking-wider"><tr>
        <th class="p-2">Fin</th><th class="p-2 font-sans">Horse</th><th class="p-2">Bar</th><th class="p-2">Wt</th><th class="p-2 font-sans">Jockey</th>
        <th class="p-2">Margin</th><th class="p-2">Settled</th><th class="p-2">800</th><th class="p-2">400</th><th class="p-2">Rating</th>
        <th class="p-2">SP</th><th class="p-2">BSP</th><th class="p-2" data-tip="Starts and wins by this horse since this race">Since</th><th class="p-2 font-sans">Stewards</th></tr></thead>
      <tbody class="divide-y divide-[#1e2638]">${rows.map(r => {
        const me = horse && r.horse_name && r.horse_name.toLowerCase() === String(horse).toLowerCase();
        return `<tr class="${me ? 'bg-[#ff6600]/10' : ''}">
          <td class="p-2 font-bold ${r.finish_pos === 1 ? 'text-emerald-400' : 'text-gray-300'}">${r.finish_pos ?? '–'}</td>
          <td class="p-2 font-sans"><button class="text-white font-bold hover:text-[#ff6600]" onclick='closePast();openHorse(${jsq(r.horse_name || "")})'>${esc(r.horse_name || '')}</button>${me ? ' <span class="text-[#ff6600] text-[10px]">◀</span>' : ''}</td>
          <td class="p-2">${r.barrier ?? ''}</td><td class="p-2">${num(r.weight, 1)}</td><td class="p-2 font-sans text-gray-400">${esc(r.jockey || '')}</td>
          <td class="p-2">${r.margin === null || r.margin === undefined ? '' : r.finish_pos === 1 ? signed(r.margin, 1) : num(Math.abs(r.margin), 1)}</td>
          <td class="p-2">${r.settle_pos ?? ''}</td><td class="p-2">${r.pos_800 ?? ''}</td><td class="p-2">${r.pos_400 ?? ''}</td>
          <td class="p-2 font-bold ${cls(r.wfa_rating)}">${num(r.wfa_rating, 1)}</td>
          <td class="p-2">${money(r.sp)}</td><td class="p-2">${money(r.bsp)}</td>
          <td class="p-2 ${r.next_wins ? 'text-emerald-400 font-bold' : 'text-gray-500'}">${r.next_runs ? (r.next_wins || 0) + '/' + r.next_runs : '–'}</td>
          <td class="p-2 font-sans text-[11px] ${r.stewards_comment ? 'text-amber-300' : 'text-gray-600'}">${esc(r.stewards_comment || '')}</td>
        </tr>`; }).join('')}</tbody></table></div>
    <p class="text-[10px] text-gray-500 mt-2">Ratings are on the same 0–100 scale as the cards, so the field here can be read straight against today's par. Green is within a length of the best run in the race.</p>`;
}
window.addEventListener('keydown', e => { if (e.key === 'Escape') closePast(); });

// ---------------------------------------------------------------- how the track is playing
// Today's winners as they come in, and the last few meetings at the same track.
// If the fence and the leaders are winning, a horse that did it the hard way
// deserves an upgrade — and one that got the run of the race does not.
const BIAS = { track: null, recent: null };

function barThird(bar, field) {
  if (!bar || !field || field < 5) return null;
  const t = Math.ceil(field / 3);
  return bar <= t ? 'inside' : bar <= 2 * t ? 'middle' : 'wide';
}
function zoneOfSettle(s, field) {
  if (!s || !field) return null;
  return s === 1 ? 'led' : s <= 3 ? 'handy' : s <= Math.ceil(field * 0.6) ? 'midfield' : 'back';
}
function biasLine(items, label) {
  const n = items.length;
  if (!n) return '';
  const count = k => items.filter(x => x === k).length;
  const pct = k => Math.round(count(k) / n * 100);
  const parts = label === 'draw'
    ? [['inside', 'inside third'], ['middle', 'middle third'], ['wide', 'outside third']]
    : [['led', 'led'], ['handy', 'handy'], ['midfield', 'midfield'], ['back', 'from the back']];
  // Don't call a bias off a handful of races: a third of winners come from each
  // third of the barriers by chance alone.
  const strong = parts.filter(([k]) => n >= 8 && pct(k) >= (label === 'draw' ? 50 : 45));
  return `<div class="flex flex-wrap items-center gap-1.5 text-[11px]">
    <span class="text-gray-500 uppercase tracking-widest w-20">${label === 'draw' ? 'Barriers' : 'Run style'}</span>
    ${parts.map(([k, t]) => `<span class="pill ${strong.some(s => s[0] === k) ? 'sect-green' : 'bg-[#0d1117] border border-[#1e2638] text-gray-400'} py-1">${t} ${count(k)}<span class="opacity-60">/${n}</span></span>`).join('')}
    ${strong.length ? `<span class="text-emerald-300">← ${strong.map(s => s[1]).join(' and ')} on top</span>` : n >= 8 ? '<span class="text-gray-500">spread evenly — no bias worth playing</span>' : `<span class="text-gray-500">${n} winner${n === 1 ? '' : 's'} is too few to call a bias</span>`}
  </div>`;
}

async function renderBias() {
  const box = document.getElementById('biasBoard'); if (!box) return;
  const m = S.meeting || {}; if (!m.track) { box.innerHTML = ''; return; }
  // Today: winners of the races already run on this card.
  const draws = [], styles = [], sps = [], favs = [];
  S.races.filter(r => r.result_in).forEach(race => {
    const rows = (S.runners[race.race_id] || []);
    const w = rows.find(r => r.finish_pos === 1); if (!w) return;
    const field = race.field_size || rows.filter(r => !r.scratched).length;
    const d = barThird(w.barrier, field); if (d) draws.push(d);
    const z = zoneOfSettle(w.settle_rank, field); if (z) styles.push(z);
    if (w.result_sp) sps.push(w.result_sp);
    const fav = rows.filter(r => !r.scratched && r.market_price).sort((a, b) => a.market_price - b.market_price)[0];
    if (fav) favs.push(fav.horse_name === w.horse_name ? 1 : 0);
  });
  if (BIAS.track !== m.track) {
    BIAS.track = m.track; BIAS.recent = null;
    try { const { data, error } = await sb.rpc('edge_track_recent', { p_track: m.track, p_days: 90 }); if (!error) BIAS.recent = data || []; } catch (e) {}
  }
  const rec = (BIAS.recent || []).filter(x => x.race_date !== S.date);
  const days = [...new Set(rec.map(x => x.race_date))].slice(0, 3);
  const last = rec.filter(x => days.includes(x.race_date));
  const rDraw = last.map(x => barThird(x.barrier, x.field_size)).filter(Boolean);
  const rStyle = last.map(x => zoneOfSettle(x.settle_pos, x.field_size)).filter(Boolean);
  const avgSp = sps.length ? sps.reduce((a, b) => a + b, 0) / sps.length : null;
  box.innerHTML = `
    <div class="bg-[#11151d] border border-[#1e2638] rounded-xl p-5">
      <div class="flex flex-wrap items-baseline justify-between gap-2 mb-2">
        <h3 class="text-white font-black text-lg">How ${esc(m.track)} is playing</h3>
        <span class="text-[11px] text-gray-500">${esc(m.going || '')}${m.rail ? ' · rail ' + esc(m.rail) : ''}</span>
      </div>
      <div class="space-y-1.5 mb-3">
        <div class="text-[10px] text-gray-500 uppercase tracking-widest">Today · ${draws.length || styles.length ? (S.races.filter(r => r.result_in).length + ' race' + (S.races.filter(r => r.result_in).length === 1 ? '' : 's') + ' run') : 'nothing run yet'}</div>
        ${draws.length ? biasLine(draws, 'draw') : '<div class="text-[11px] text-gray-500">The first result will start this off.</div>'}
        ${styles.length ? biasLine(styles, 'style') : ''}
        ${avgSp ? `<div class="text-[11px] text-gray-400">Winners averaging <b class="text-white font-mono-numbers">${money(avgSp)}</b>${favs.length ? ` · favourites ${favs.reduce((a, b) => a + b, 0)}/${favs.length}` : ''}${avgSp > 9 ? " — an outsiders' day so far, be careful backing short ones" : avgSp < 4.5 ? ' — form is holding up' : ''}</div>` : ''}
      </div>
      <div class="space-y-1.5 border-t border-[#1e2638] pt-3">
        <div class="text-[10px] text-gray-500 uppercase tracking-widest">Last ${days.length} meeting${days.length === 1 ? '' : 's'} here${days.length ? ' · ' + days.map(esc).join(', ') : ''}</div>
        ${rDraw.length ? biasLine(rDraw, 'draw') + biasLine(rStyle, 'style') : '<div class="text-[11px] text-gray-500">No recent meetings at this track in the database yet.</div>'}
      </div>
      <p class="text-[10px] text-gray-500 mt-2">Read it the other way too: a horse that won against the bias is better than it looks, and one that got every favour is worse. Settling positions come in with the ratings, so today's run-style line fills in through the evening.</p>
    </div>`;
}

// ---------------------------------------------------------------- pace verdict
// One line on what the tempo does to the race, and who it helps. The speed map
// shows where they'll be; this says what that's worth.
function paceVerdict(race, rows) {
  const live = rows.filter(r => !r._scratched && !r.scratched);
  if (!live.length) return '';
  const tempo = String(race.tempo || '').toLowerCase();
  const leaders = live.filter(r => r.map_zone === 'Leader');
  const onPace = live.filter(r => r.map_zone === 'Leader' || r.map_zone === "Leader's Back / Box Seat" || r.map_zone === 'Handy');
  const back = live.filter(r => r.map_zone === 'Backmarker' || r.map_zone === 'Worse Than Midfield');
  const name = r => `${r.saddlecloth ?? ''} ${r.horse_name}`;
  const byChance = xs => xs.slice().sort((a, b) => (b._p || 0) - (a._p || 0));
  let verdict, helps, hurts, tone;
  if (tempo.includes('fast') || leaders.length >= 3) {
    verdict = leaders.length >= 3
      ? `${leaders.length} of them want the lead, so expect pressure in front`
      : 'the tempo shapes up fast';
    helps = byChance(back).slice(0, 3); hurts = byChance(leaders).slice(0, 2);
    tone = 'text-sky-300';
  } else if (tempo.includes('slow') || leaders.length === 0) {
    verdict = leaders.length === 0
      ? 'nothing in the field is a natural leader, so it can crawl'
      : 'the tempo shapes up soft';
    helps = byChance(onPace).slice(0, 3); hurts = byChance(back).slice(0, 2);
    tone = 'text-amber-300';
  } else {
    verdict = 'an even tempo, so the map matters less than the ratings';
    helps = []; hurts = []; tone = 'text-gray-400';
  }
  const list = xs => xs.map(r => `<b class="text-white">${esc(name(r))}</b>`).join(', ');
  return `<div class="mt-2 text-[11px] ${tone}">⚡ Pace read: ${verdict}.${
    helps.length ? ` Helps ${list(helps)}.` : ''}${
    hurts.length ? ` <span class="text-gray-400">Against ${list(hurts)}.</span>` : ''}${
    back.length && (tempo.includes('fast') || leaders.length >= 3) ? '' : ''}</div>`;
}
