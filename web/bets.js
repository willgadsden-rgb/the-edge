/* The Edge website: Bet Log.
 * Every bet is to win $100, capped at a $75 stake. Bets are written by the
 * /api/bets Netlify function (shared syndicate PIN) and read straight from
 * public.edge_bets. Results settle themselves from the published race results.
 */

const TARGET = 100, MAX_STAKE = 75;
const stakeFor = o => (o && o > 1) ? Math.min(TARGET / (o - 1), MAX_STAKE) : 0;
const BL = { bets: null, results: {}, filter: 'all', pin: null, form: {} };
const lsGet = k => { try { return localStorage.getItem(k); } catch (e) { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };

function betFormRunners() {
  const race = S.races.find(r => r.race_id === BL.form.race_id) || null;
  return race ? byBook((S.runners[race.race_id] || []).filter(r => !r._scratched && !r.scratched)) : [];
}

function prefillBet(raceId, horse) {
  BL.form = { race_id: raceId, horse };
  const r = (S.runners[raceId] || []).find(x => x.horse_name === horse);
  if (r && r._market) BL.form.odds = r._market;
  switchTab('bets');
}

function renderBetForm() {
  const box = document.getElementById('betForm'); if (!box) return;
  if (!BL.form.race_id && S.races.length) BL.form.race_id = (S.view !== 'ALL' && S.view) || S.races[0].race_id;
  const runners = betFormRunners();
  if (!BL.form.horse || !runners.find(r => r.horse_name === BL.form.horse)) { BL.form.horse = runners[0] ? runners[0].horse_name : null; BL.form.odds = runners[0] ? runners[0]._market : null; }
  const sel = runners.find(r => r.horse_name === BL.form.horse);
  const odds = Number(BL.form.odds) || (sel && sel._market) || null;
  const stake = stakeFor(odds), win = stake * ((odds || 1) - 1);
  const eff = odds ? 1 + (odds - 1) * (1 - ((S.races.find(r => r.race_id === BL.form.race_id) || {}).commission ?? 0.08)) : null;
  const edge = sel && sel._fair && eff ? eff / sel._fair - 1 : null;
  box.innerHTML = `
    <div class="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-3 items-end">
      <label class="text-[10px] text-gray-500 uppercase tracking-widest">Race
        <select class="syn-input w-full p-2 mt-1" onchange="BL.form.race_id=this.value;BL.form.horse=null;renderBetForm()">${S.races.map(r => `<option value="${r.race_id}" ${r.race_id === BL.form.race_id ? 'selected' : ''}>${esc((S.meeting || {}).track || '')} R${r.race_number}</option>`).join('')}</select></label>
      <label class="text-[10px] text-gray-500 uppercase tracking-widest lg:col-span-2">Horse
        <select class="syn-input w-full p-2 mt-1" onchange="BL.form.horse=this.value;BL.form.odds=null;renderBetForm()">${runners.map(r => `<option value="${esc(r.horse_name)}" ${r.horse_name === BL.form.horse ? 'selected' : ''}>${r.saddlecloth ?? ''}. ${esc(r.horse_name)} · ${money(r._market)} (true ${money(r._fair)})</option>`).join('')}</select></label>
      <label class="text-[10px] text-gray-500 uppercase tracking-widest">Odds taken
        <input type="number" step="0.01" min="1.01" value="${odds ?? ''}" oninput="BL.form.odds=this.value;renderBetSummary()" id="betOdds" class="syn-input w-full p-2 mt-1 font-mono-numbers"></label>
      <label class="text-[10px] text-gray-500 uppercase tracking-widest">Bookmaker
        <input value="${esc(BL.form.bookie || lsGet('edge_bookie') || '')}" oninput="BL.form.bookie=this.value" class="syn-input w-full p-2 mt-1" placeholder="e.g. Betfair"></label>
      <label class="text-[10px] text-gray-500 uppercase tracking-widest">Your name
        <input value="${esc(lsGet('edge_bettor') || '')}" oninput="lsSet('edge_bettor', this.value)" class="syn-input w-full p-2 mt-1" placeholder="who placed it"></label>
    </div>
    <div class="flex flex-wrap items-end gap-3 mt-3">
      <label class="text-[10px] text-gray-500 uppercase tracking-widest flex-1 min-w-[200px]">Note
        <input value="${esc(BL.form.note || '')}" oninput="BL.form.note=this.value" class="syn-input w-full p-2 mt-1" placeholder="why: value flag, map, angle…"></label>
      <div id="betSummary" class="text-sm text-gray-300"></div>
      <button onclick="logBet()" class="btn-orange px-5 py-2.5 rounded font-bold text-xs uppercase">Log bet</button>
    </div>
    <div id="betMsg" class="text-xs mt-2">${BL.msg || ''}</div>`;
  renderBetSummary(edge);
}
function renderBetSummary() {
  const el = document.getElementById('betSummary'); if (!el) return;
  const o = Number(document.getElementById('betOdds').value) || null;
  const sel = betFormRunners().find(r => r.horse_name === BL.form.horse);
  const st = stakeFor(o), win = st * ((o || 1) - 1);
  const eff = o ? 1 + (o - 1) * 0.92 : null;
  const edge = sel && sel._fair && eff ? eff / sel._fair - 1 : null;
  el.innerHTML = o ? `Stake <b class="text-white font-mono-numbers">$${st.toFixed(2)}</b> to win <b class="text-emerald-400 font-mono-numbers">$${win.toFixed(2)}</b>${st >= MAX_STAKE ? ' <span class="text-amber-300">(capped at $75)</span>' : ''}${edge !== null ? ` · edge vs our price <b class="${edge > 0 ? 'text-emerald-400' : 'text-red-400'}">${(edge * 100).toFixed(0)}%</b>` : ''}` : 'Enter the odds';
}

async function logBet() {
  const msg = document.getElementById('betMsg');
  const race = S.races.find(r => r.race_id === BL.form.race_id);
  const r = betFormRunners().find(x => x.horse_name === BL.form.horse);
  const odds = Number(document.getElementById('betOdds').value);
  if (!race || !r || !(odds > 1.01)) { msg.innerHTML = '<span class="text-red-400">Pick a race, a horse and the odds.</span>'; return; }
  const pin = BL.pin || lsGet('edge_bet_pin') || '';
  const eff = 1 + (odds - 1) * (1 - (race.commission ?? 0.08));
  const body = { pin, bettor: lsGet('edge_bettor') || '', meeting_date: race.meeting_date || S.date, track: (S.meeting || {}).track,
    race_id: race.race_id, race_number: race.race_number, horse_name: r.horse_name, saddlecloth: r.saddlecloth, odds_taken: odds,
    fair_price: r._fair ? Math.round(r._fair * 100) / 100 : null, edge_pct: r._fair ? Math.round((eff / r._fair - 1) * 1000) / 10 : null,
    bookmaker: BL.form.bookie || '', note: BL.form.note || '' };
  msg.innerHTML = '<span class="text-gray-400">Logging…</span>';
  try {
    const res = await fetch('/api/bets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const out = await res.json();
    if (res.status === 401) {          // only if a PIN has been switched on in Netlify
      const p = window.prompt('Bet PIN'); if (!p) { msg.innerHTML = ''; return; }
      BL.pin = p; lsSet('edge_bet_pin', p); return logBet();
    }
    if (!res.ok) throw new Error(out.error || res.status);
    if (BL.form.bookie) lsSet('edge_bookie', BL.form.bookie);
    BL.msg = msg.innerHTML = `<span class="text-emerald-400">Logged: ${esc(r.horse_name)} $${out.bet.stake.toFixed(2)} @ ${money(odds)} to win $${out.bet.to_win.toFixed(2)}.</span>`;
    BL.form.note = ''; BL.bets = null; loadBets();
  } catch (e) { msg.innerHTML = `<span class="text-red-400">Not logged: ${esc(e.message)}</span>`; }
}
// Two different things, so two buttons. Cancel removes a bet logged by
// mistake; void keeps a real bet in the ledger but out of the P&L.
function askCancel(id, horse) {
  const cell = document.getElementById('act-' + id); if (!cell) return;
  cell.innerHTML = `<span class="whitespace-nowrap text-[11px]">Remove ${esc(horse)}?
      <button onclick="cancelBet('${esc(id)}')" class="text-red-400 font-bold ml-1">Yes</button>
      <button onclick="loadBets()" class="text-gray-400 ml-1">No</button></span>`;
}
async function cancelBet(id) {
  const pin = BL.pin || lsGet('edge_bet_pin') || '';
  const res = await fetch('/api/bets?remove=' + encodeURIComponent(id), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pin }) });
  const out = await res.json().catch(() => ({}));
  if (res.ok) { BL.bets = null; BL.msg = '<span class="text-gray-400">Bet removed.</span>'; loadBets(); }
  else { const c = document.getElementById('act-' + id); if (c) c.innerHTML = `<span class="text-red-400 text-[11px]">${esc(out.error || res.status)}</span>`; }
}
async function voidBet(id) {
  const pin = BL.pin || lsGet('edge_bet_pin') || '';
  const res = await fetch('/api/bets?void=' + encodeURIComponent(id), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pin }) });
  if (res.ok) { BL.bets = null; loadBets(); }
}

async function loadBets() {
  const box = document.getElementById('betLedger'); if (!box) return;
  renderBetForm();
  if (!BL.bets) {
    box.innerHTML = '<div class="text-gray-400 text-sm">Loading the log…</div>';
    const { data, error } = await sb.from('edge_bets').select('*').order('created_at', { ascending: false }).limit(1000);
    if (error) { box.innerHTML = `<div class="text-amber-300 text-sm">The bet log switches on after the next engine run (it creates the table). ${esc(error.message)}</div>`; return; }
    BL.bets = data || [];
    const ids = [...new Set(BL.bets.map(b => b.race_id))];
    BL.results = {}; BL.races = {};
    for (let i = 0; i < ids.length; i += 100) {
      const [{ data: rs }, { data: ra }] = await Promise.all([
        sb.from('edge_runners').select('race_id,horse_name,finish_pos,result_bsp,result_sp,scratched').in('race_id', ids.slice(i, i + 100)),
        sb.from('edge_races').select('race_id,result_in').in('race_id', ids.slice(i, i + 100))]);
      (rs || []).forEach(r => { BL.results[r.race_id + '|' + r.horse_name] = r; });
      (ra || []).forEach(r => { BL.races[r.race_id] = r; });
    }
  }
  renderLedger();
}
function settle(b) {
  if (b.void) return { status: 'Void', pl: 0 };
  const r = BL.results[b.race_id + '|' + b.horse_name], race = BL.races[b.race_id];
  if (r && r.scratched) return { status: 'Scratched', pl: 0, r };
  if (!race || !race.result_in || !r || !r.finish_pos) return { status: 'Pending', pl: null, r };
  return r.finish_pos === 1 ? { status: 'Won', pl: b.stake * (b.odds_taken - 1), r } : { status: 'Lost', pl: -b.stake, r };
}
function renderLedger() {
  const box = document.getElementById('betLedger');
  const me = lsGet('edge_bettor') || '';
  let list = (BL.bets || []).map(b => ({ b, s: settle(b) }));
  if (BL.filter === 'mine') list = list.filter(x => (x.b.bettor || '') === me);
  if (BL.filter === 'today') list = list.filter(x => x.b.meeting_date === S.date);
  const graded = list.filter(x => x.s.pl !== null && x.s.status !== 'Void' && x.s.status !== 'Scratched');
  const staked = graded.reduce((a, x) => a + x.b.stake, 0), pl = graded.reduce((a, x) => a + x.s.pl, 0);
  const wins = graded.filter(x => x.s.status === 'Won').length;
  const clvs = list.map(x => x.s.r && x.s.r.result_bsp ? x.b.odds_taken / x.s.r.result_bsp - 1 : null).filter(v => v !== null);
  const pending = list.filter(x => x.s.status === 'Pending');
  const exposure = pending.reduce((a, x) => a + x.b.stake, 0);
  const byBettor = {};
  graded.forEach(x => { const k = x.b.bettor || '(no name)'; const o = byBettor[k] = byBettor[k] || { n: 0, w: 0, st: 0, pl: 0 }; o.n++; o.st += x.b.stake; o.pl += x.s.pl; if (x.s.status === 'Won') o.w++; });
  const tile = (l, v, sub = '', tone = 'text-white') => `<div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3"><div class="text-[10px] text-gray-500 uppercase tracking-widest">${l}</div><div class="text-xl font-black font-mono-numbers ${tone}">${v}</div><div class="text-[10px] text-gray-500">${sub}</div></div>`;
  const fbtn = (k, l) => `<button onclick="BL.filter='${k}';renderLedger()" class="rt-btn ${BL.filter === k ? 'active' : ''}" style="font-size:10px;padding:5px 10px">${l}</button>`;
  box.innerHTML = `
    <div class="flex flex-wrap justify-between items-center gap-2 mb-3"><div class="flex gap-2">${fbtn('all', 'All bets')}${fbtn('today', 'This date')}${fbtn('mine', 'Mine')}</div>
      <button onclick="BL.bets=null;loadBets()" class="text-xs text-gray-400 underline">Refresh results</button></div>
    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 mb-4">
      ${tile('Settled bets', graded.length, `${pending.length} pending`)}
      ${tile('Winners', `${wins} (${graded.length ? Math.round(wins / graded.length * 100) : 0}%)`)}
      ${tile('Staked', '$' + staked.toFixed(0))}
      ${tile('Profit / loss', (pl >= 0 ? '+$' : '−$') + Math.abs(pl).toFixed(0), '', pl >= 0 ? 'text-emerald-400' : 'text-red-400')}
      ${tile('ROI', staked ? (pl / staked * 100 >= 0 ? '+' : '') + (pl / staked * 100).toFixed(1) + '%' : '–', '', pl >= 0 ? 'text-emerald-400' : 'text-red-400')}
      ${tile('Avg CLV vs BSP', clvs.length ? ((clvs.reduce((a, c) => a + c, 0) / clvs.length) * 100).toFixed(1) + '%' : '–', 'beating the Betfair SP = real edge')}
      ${tile('Open exposure', '$' + exposure.toFixed(0), 'staked on pending bets')}
    </div>
    ${Object.keys(byBettor).length > 1 ? `<div class="flex flex-wrap gap-2 mb-3">${Object.entries(byBettor).map(([k, o]) => `<span class="px-2.5 py-1 rounded-md bg-[#0d1117] border border-[#1e2638] text-[11px] font-mono-numbers"><b class="text-white font-sans">${esc(k)}</b> ${o.n} bets · ${o.w} won · <span class="${o.pl >= 0 ? 'text-emerald-400' : 'text-red-400'}">${o.pl >= 0 ? '+' : '−'}$${Math.abs(o.pl).toFixed(0)}</span></span>`).join('')}</div>` : ''}
    <div class="overflow-x-auto"><table class="w-full text-left font-mono-numbers text-xs">
      <thead class="bg-[#0d1117] text-gray-500 uppercase text-[10px] tracking-wider"><tr>
        <th class="p-3">Date</th><th class="p-3 font-sans">Race</th><th class="p-3 font-sans">Horse</th><th class="p-3">Odds</th><th class="p-3">Stake</th><th class="p-3">To win</th>
        <th class="p-3">Our price</th><th class="p-3">Edge</th><th class="p-3">BSP</th><th class="p-3">Result</th><th class="p-3">P/L</th><th class="p-3 font-sans">Who / note</th><th class="p-3 font-sans">Remove</th></tr></thead>
      <tbody class="divide-y divide-[#1e2638]">${list.map(({ b, s }) => {
        const clv = s.r && s.r.result_bsp ? b.odds_taken / s.r.result_bsp - 1 : null;
        const tone = s.status === 'Won' ? 'text-emerald-400 font-bold' : s.status === 'Lost' ? 'text-red-400' : 'text-gray-400';
        return `<tr class="${b.void ? 'opacity-40 line-through' : ''}">
          <td class="p-3 whitespace-nowrap">${esc(b.meeting_date || '')}</td><td class="p-3 font-sans whitespace-nowrap">${esc(b.track || '')} R${b.race_number ?? ''}</td>
          <td class="p-3 font-sans text-white font-bold">${b.saddlecloth ?? ''}. ${esc(b.horse_name)}</td>
          <td class="p-3">${money(b.odds_taken)}</td><td class="p-3">$${Number(b.stake).toFixed(2)}</td><td class="p-3">$${Number(b.to_win).toFixed(2)}</td>
          <td class="p-3 text-[#ffa366]">${money(b.fair_price)}</td><td class="p-3 ${b.edge_pct > 0 ? 'text-emerald-400' : 'text-gray-400'}">${b.edge_pct === null || b.edge_pct === undefined ? '–' : (b.edge_pct > 0 ? '+' : '') + b.edge_pct + '%'}</td>
          <td class="p-3">${s.r ? money(s.r.result_bsp) : '–'}${clv !== null ? ` <span class="${clv > 0 ? 'text-emerald-400' : 'text-gray-500'}">${clv > 0 ? '+' : ''}${(clv * 100).toFixed(0)}%</span>` : ''}</td>
          <td class="p-3 ${tone}">${s.status}${s.r && s.r.finish_pos && s.status === 'Lost' ? ` (${s.r.finish_pos})` : ''}</td>
          <td class="p-3 ${s.pl > 0 ? 'text-emerald-400' : s.pl < 0 ? 'text-red-400' : 'text-gray-500'}">${s.pl === null ? '–' : (s.pl >= 0 ? '+' : '−') + '$' + Math.abs(s.pl).toFixed(2)}</td>
          <td class="p-3 font-sans text-[11px] text-gray-400">${esc(b.bettor || '')}${b.bookmaker ? ' · ' + esc(b.bookmaker) : ''}${b.note ? '<br>' + esc(b.note) : ''}</td>
          <td class="p-3" id="act-${esc(b.id)}">${b.void ? '<span class="text-gray-600 text-[11px]">void</span>' : `
            <button onclick='askCancel(${JSON.stringify(b.id)}, ${JSON.stringify(b.horse_name)})' class="border border-red-500/40 text-red-400 hover:bg-red-500/10 rounded px-2 py-1 text-[11px] font-bold whitespace-nowrap">✕ Cancel</button>
            ${s.status === 'Pending' ? '' : `<button onclick="voidBet('${esc(b.id)}')" class="text-gray-600 hover:text-gray-300 text-[10px] ml-1" data-tip="Keep it in the ledger but leave it out of the P&L">void</button>`}`}</td></tr>`; }).join('') ||
        '<tr><td colspan="13" class="p-8 text-center text-gray-500">No bets logged yet.</td></tr>'}</tbody></table></div>
    <p class="text-[10px] text-gray-500 mt-2">Stake = $100 ÷ (odds − 1), never more than $75 (so under $2.34 it wins less than $100). Results settle from the night sync; scratched horses settle at $0. CLV = your odds against the Betfair SP. Logged one by accident? <b class="text-red-400">✕ Cancel</b> removes it completely; <b>void</b> keeps a real bet in the ledger but out of the P&amp;L.</p>`;
}
