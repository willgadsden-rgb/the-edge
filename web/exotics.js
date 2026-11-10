/* Exotics: build an exacta, trifecta, first four or quaddy off our own prices.
 *
 * Every number here comes from the same book the cards use. Two honest limits,
 * stated on the page as well as here:
 *   - Placings are worked out with the Harville rule (after the winner is gone,
 *     the rest keep their odds in proportion). It slightly over-rates short
 *     horses running second and third, so treat the chance as a guide.
 *   - We cannot see the tote pool, so there is no real dividend to show. What
 *     we show is OUR fair dividend: 1 / chance of the combination. If the tote
 *     or the fixed-odds exotic pays more than that, the bet is value; if it
 *     pays less, it is not.
 */

const EX = { race: null, sel: [[], [], [], []], mode: 'tri', unit: 1, quadLegs: [], quadSel: {}, budget: 100 };

const exRows = race => (S.runners[race.race_id] || [])
  .filter(r => !r.scratched && !r._scratched && (r._p || 0) > 0)
  .sort((a, b) => (b._p || 0) - (a._p || 0));

// Chance of one exact finishing order, Harville-style.
function orderProb(ps) {
  let left = 1, out = 1;
  for (const p of ps) {
    if (left <= 0 || p <= 0) return 0;
    out *= p / left;
    left -= p;
  }
  return out;
}
// Chance that the selections fill the first `depth` placings in any allowed order.
function comboProb(sel, P, depth) {
  const lists = sel.slice(0, depth);
  if (lists.some(l => !l.length)) return { p: 0, n: 0 };
  let p = 0, n = 0;
  const walk = (i, used, acc) => {
    if (i === depth) { p += orderProb(acc); n++; return; }
    for (const h of lists[i]) {
      if (used.has(h)) continue;
      used.add(h); acc.push(P[h] || 0);
      walk(i + 1, used, acc);
      acc.pop(); used.delete(h);
    }
  };
  walk(0, new Set(), []);
  return { p, n };
}
const DEPTH = { ex: 2, tri: 3, ff: 4 };
const MODE_NAME = { ex: 'Exacta', tri: 'Trifecta', ff: 'First four' };

function exSetMode(m) { EX.mode = m; renderExotics(); }
function exToggle(pos, horse) {
  const l = EX.sel[pos];
  const i = l.indexOf(horse);
  if (i >= 0) l.splice(i, 1); else l.push(horse);
  renderExotics();
}
function exPreset(kind) {
  const race = S.races.find(r => r.race_id === EX.race); if (!race) return;
  const rows = exRows(race), d = DEPTH[EX.mode];
  const names = n => rows.slice(0, n).map(r => r.horse_name);
  EX.sel = [[], [], [], []];
  if (kind === 'box') { const b = names(d + 1); for (let i = 0; i < d; i++) EX.sel[i] = b.slice(); }
  if (kind === 'banker') { EX.sel[0] = names(1); for (let i = 1; i < d; i++) EX.sel[i] = names(Math.min(rows.length, d + 2)).filter(x => x !== rows[0].horse_name); }
  if (kind === 'value') {
    const field = rows.filter(r => (r._p || 0) >= 0.03).map(r => r.horse_name);
    EX.sel[0] = names(2);
    for (let i = 1; i < d; i++) EX.sel[i] = field.slice(0, 8);
  }
  if (kind === 'clear') EX.sel = [[], [], [], []];
  renderExotics();
}

function renderExotics() {
  const box = document.getElementById('exoticsBody'); if (!box) return;
  if (!S.races.length) { box.innerHTML = '<div class="text-gray-400 text-sm">Load a meeting on Live Cards first.</div>'; return; }
  if (!EX.race || !S.races.find(r => r.race_id === EX.race)) EX.race = (S.races.find(r => !r.result_in) || S.races[0]).race_id;
  const race = S.races.find(r => r.race_id === EX.race);
  const rows = exRows(race);
  const P = Object.fromEntries(rows.map(r => [r.horse_name, r._p]));
  const d = DEPTH[EX.mode];
  const { p, n } = comboProb(EX.sel, P, d);
  const cost = n * EX.unit;
  const fair = p > 0 ? 1 / p : null;
  const tile = (l, v, sub = '', tone = 'text-white') => `<div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3"><div class="text-[10px] text-gray-500 uppercase tracking-widest">${l}</div><div class="text-xl font-black font-mono-numbers ${tone}">${v}</div><div class="text-[10px] text-gray-500">${sub}</div></div>`;
  const posName = ['1st', '2nd', '3rd', '4th'];
  const grid = `<div class="overflow-x-auto"><table class="w-full text-xs">
    <thead class="text-gray-500 uppercase text-[10px]"><tr><th class="text-left py-1">Runner</th><th class="px-2">Our chance</th><th class="px-2">Our price</th><th class="px-2">Market</th>
      ${Array.from({ length: d }, (_, i) => `<th class="px-2">${posName[i]}</th>`).join('')}</tr></thead>
    <tbody>${rows.map(r => `<tr class="border-t border-[#1e2638]">
      <td class="py-1.5 font-bold text-white">${r.saddlecloth ?? ''}. ${esc(r.horse_name)}${r.play_flag ? ' <span class="pill sect-green py-0.5">★</span>' : ''}</td>
      <td class="px-2 text-center font-mono-numbers">${num(r._p * 100, 1)}%</td>
      <td class="px-2 text-center font-mono-numbers text-[#ffa366]">${money(r._fair)}</td>
      <td class="px-2 text-center font-mono-numbers">${money(r._market)}</td>
      ${Array.from({ length: d }, (_, i) => `<td class="px-2 text-center"><input type="checkbox" ${EX.sel[i].includes(r.horse_name) ? 'checked' : ''} onchange='exToggle(${i}, ${jsq(r.horse_name)})' class="accent-[#ff6600] w-4 h-4"></td>`).join('')}
    </tr>`).join('')}</tbody></table></div>`;
  box.innerHTML = `
    <div class="flex flex-wrap gap-2 items-center mb-3">
      <select onchange="EX.race=this.value;EX.sel=[[],[],[],[]];renderExotics()" class="syn-input p-2 text-sm">
        ${S.races.map(r => `<option value="${r.race_id}" ${r.race_id === EX.race ? 'selected' : ''}>R${r.race_number} ${esc(r.race_name || '')}${r.result_in ? ' (run)' : ''}</option>`).join('')}
      </select>
      ${Object.entries(MODE_NAME).map(([k, v]) => `<button onclick="exSetMode('${k}')" class="rt-btn ${EX.mode === k ? 'active' : ''}" style="font-size:11px;padding:6px 12px">${v}</button>`).join('')}
      <span class="text-gray-600">|</span>
      <button onclick="exPreset('box')" class="rt-btn" style="font-size:11px;padding:6px 10px">Box our top ${d + 1}</button>
      <button onclick="exPreset('banker')" class="rt-btn" style="font-size:11px;padding:6px 10px">Banker over the rest</button>
      <button onclick="exPreset('value')" class="rt-btn" style="font-size:11px;padding:6px 10px">Two to win, spread under</button>
      <button onclick="exPreset('clear')" class="rt-btn" style="font-size:11px;padding:6px 10px">Clear</button>
      <label class="text-[11px] text-gray-400 ml-auto">Unit $<input type="number" min="0.5" step="0.5" value="${EX.unit}" onchange="EX.unit=Math.max(0.5,+this.value||1);renderExotics()" class="syn-input w-16 p-1 ml-1 text-xs font-mono-numbers"></label>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
      ${tile('Combinations', n.toLocaleString(), `${MODE_NAME[EX.mode]} · $${EX.unit} unit`)}
      ${tile('Cost', '$' + cost.toFixed(2), n ? `$${(cost / Math.max(n, 1)).toFixed(2)} a line` : 'pick your runners')}
      ${tile('Our chance of collecting', p > 0 ? num(p * 100, 1) + '%' : '–', p > 0 ? `about 1 in ${Math.round(1 / p).toLocaleString()}` : '')}
      ${tile('Our fair dividend', fair ? '$' + (fair * EX.unit).toFixed(0) : '–', 'take it only if the pool pays more', 'text-[#ffa366]')}
    </div>
    ${p > 0 ? `<p class="text-[11px] text-gray-400 mb-3">At $${cost.toFixed(2)} this is worth taking if the dividend beats <b class="text-[#ffa366]">$${(fair * EX.unit).toFixed(0)}</b> for your $${EX.unit} unit. Exotic pools pay out about 75-80 cents in the dollar, so you need a real edge in the structure, not just a correct favourite.${
      fair * EX.unit < 15 ? ' <b class="text-amber-300">This structure is very wide</b> — a dividend that small is rare, and the pool take will eat it.' :
      fair * EX.unit > 2000 ? ' <b class="text-amber-300">This is a lottery ticket</b> — fun, but do not call it a bet.' : ''}</p>` : ''}
    ${grid}
    <p class="text-[10px] text-gray-500 mt-3">Placings use the Harville rule — once the winner is out, the others keep their odds in proportion. It slightly flatters short-priced horses running second and third, so read the chance as a guide, not a guarantee. Scratchings are already out of the book.</p>`;
}

// ---------------------------------------------------------------- quaddy
function quadDefault() {
  const live = S.races.filter(r => !r.result_in);
  const pool = live.length >= 4 ? live : S.races;
  EX.quadLegs = pool.slice(-4).map(r => r.race_id);
  EX.quadSel = {};
  EX.quadLegs.forEach(id => { const race = S.races.find(x => x.race_id === id); EX.quadSel[id] = exRows(race).slice(0, 2).map(r => r.horse_name); });
}
function quadToggle(raceId, horse) {
  const l = EX.quadSel[raceId] || (EX.quadSel[raceId] = []);
  const i = l.indexOf(horse);
  if (i >= 0) l.splice(i, 1); else l.push(horse);
  renderQuaddy();
}
// Spend the budget where it buys the most chance: add the next runner whose
// chance per dollar of extra cost is highest, until the budget is used.
function quadAuto() {
  const unit = EX.unit, budget = EX.budget;
  EX.quadLegs.forEach(id => { const race = S.races.find(x => x.race_id === id); EX.quadSel[id] = exRows(race).slice(0, 1).map(r => r.horse_name); });
  const chance = () => EX.quadLegs.reduce((a, id) => a * legP(id), 1);
  const lines = () => EX.quadLegs.reduce((a, id) => a * Math.max(1, (EX.quadSel[id] || []).length), 1);
  for (let guard = 0; guard < 60; guard++) {
    let best = null;
    EX.quadLegs.forEach(id => {
      const race = S.races.find(x => x.race_id === id);
      const next = exRows(race).find(r => !(EX.quadSel[id] || []).includes(r.horse_name));
      if (!next) return;
      const before = chance(), beforeCost = lines() * unit;
      EX.quadSel[id].push(next.horse_name);
      const gain = chance() - before, cost = lines() * unit - beforeCost;
      EX.quadSel[id].pop();
      if (cost > 0 && lines() * unit + cost <= budget) {
        const score = gain / cost;
        if (!best || score > best.score) best = { id, horse: next.horse_name, score };
      }
    });
    if (!best) break;
    EX.quadSel[best.id].push(best.horse);
  }
  renderQuaddy();
}
function legP(raceId) {
  const race = S.races.find(x => x.race_id === raceId); if (!race) return 0;
  const rows = exRows(race);
  const sel = EX.quadSel[raceId] || [];
  return rows.filter(r => sel.includes(r.horse_name)).reduce((a, r) => a + (r._p || 0), 0);
}
function renderQuaddy() {
  const box = document.getElementById('quaddyBody'); if (!box) return;
  if (!S.races.length) { box.innerHTML = '<div class="text-gray-400 text-sm">Load a meeting on Live Cards first.</div>'; return; }
  if (!EX.quadLegs.length || EX.quadLegs.some(id => !S.races.find(r => r.race_id === id))) quadDefault();
  const lines = EX.quadLegs.reduce((a, id) => a * Math.max(1, (EX.quadSel[id] || []).length), 1);
  const cost = lines * EX.unit;
  const p = EX.quadLegs.reduce((a, id) => a * legP(id), 1);
  const fair = p > 0 ? 1 / p : null;
  const tile = (l, v, sub = '', tone = 'text-white') => `<div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3"><div class="text-[10px] text-gray-500 uppercase tracking-widest">${l}</div><div class="text-xl font-black font-mono-numbers ${tone}">${v}</div><div class="text-[10px] text-gray-500">${sub}</div></div>`;
  box.innerHTML = `
    <div class="flex flex-wrap gap-2 items-center mb-3">
      <span class="text-[11px] text-gray-400">Legs</span>
      ${S.races.map(r => `<button onclick="(function(){const i=EX.quadLegs.indexOf('${r.race_id}');if(i>=0)EX.quadLegs.splice(i,1);else if(EX.quadLegs.length<6)EX.quadLegs.push('${r.race_id}');EX.quadLegs.sort((a,b)=>S.races.findIndex(x=>x.race_id===a)-S.races.findIndex(x=>x.race_id===b));renderQuaddy();})()" class="rt-btn ${EX.quadLegs.includes(r.race_id) ? 'active' : ''}" style="font-size:11px;padding:5px 9px">R${r.race_number}</button>`).join('')}
      <label class="text-[11px] text-gray-400 ml-auto">Budget $<input type="number" min="1" step="1" value="${EX.budget}" onchange="EX.budget=Math.max(1,+this.value||50);renderQuaddy()" class="syn-input w-20 p-1 ml-1 text-xs font-mono-numbers"></label>
      <button onclick="quadAuto()" class="rt-btn active" style="font-size:11px;padding:6px 12px">Spend it for me</button>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
      ${tile('Lines', lines.toLocaleString(), `${EX.quadLegs.length} legs · $${EX.unit} unit`)}
      ${tile('Cost', '$' + cost.toFixed(2), cost > EX.budget ? 'over your budget' : 'within budget', cost > EX.budget ? 'text-red-400' : 'text-white')}
      ${tile('Our chance', p > 0 ? num(p * 100, 2) + '%' : '–', p > 0 ? `about 1 in ${Math.round(1 / p).toLocaleString()}` : '')}
      ${tile('Our fair dividend', fair ? '$' + (fair * EX.unit).toFixed(0) : '–', 'worth playing if the pool pays more', 'text-[#ffa366]')}
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
      ${EX.quadLegs.map(id => {
        const race = S.races.find(x => x.race_id === id); const rows = exRows(race);
        const lp = legP(id);
        return `<div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3">
          <div class="flex justify-between items-baseline mb-1"><b class="text-white">R${race.race_number}</b><span class="text-[11px] font-mono-numbers ${lp >= 0.6 ? 'text-emerald-400' : 'text-gray-400'}">${num(lp * 100, 0)}% covered</span></div>
          <div class="text-[10px] text-gray-500 mb-2">${race.distance}m ${esc(race.class_name || '')}</div>
          ${rows.map(r => `<label class="flex items-center gap-2 py-1 text-xs cursor-pointer">
            <input type="checkbox" ${(EX.quadSel[id] || []).includes(r.horse_name) ? 'checked' : ''} onchange='quadToggle(${jsq(id)}, ${jsq(r.horse_name)})' class="accent-[#ff6600] w-4 h-4">
            <span class="text-white font-bold flex-1">${r.saddlecloth ?? ''}. ${esc(r.horse_name)}</span>
            <span class="font-mono-numbers text-gray-400">${num(r._p * 100, 0)}%</span>
            <span class="font-mono-numbers text-gray-500">${money(r._market)}</span></label>`).join('')}
        </div>`; }).join('')}
    </div>
    <p class="text-[10px] text-gray-500 mt-3">"Spend it for me" adds the runner that buys the most chance per extra dollar, until your budget is gone — so it widens the open legs and leaves the strong ones alone. Our chance multiplies the legs together, which assumes the races are independent; a wet track or a bias can tie them together, so treat it as a guide.</p>`;
}
