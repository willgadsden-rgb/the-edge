/* The Edge website — extra features on top of index.html's core.
 *
 *   Angles      tags from the Pattern Lab study (what the history says the market
 *               gets wrong), shown per runner and used by the Plays board.
 *   Plays       best plays and overbet runners across the meeting.
 *   Modifiers   race-reading toggles and your own rules, re-pricing the book.
 *   Horse page  full history from the database: records by stage, going, trip,
 *               track and spacing, a rating chart, every run with stewards notes.
 *   Pattern Lab live angle study (actual vs expected wins from the SP).
 *   Track record every published value flag graded against the result.
 *
 * Uses the globals from index.html (S, sb, esc, num, money, signed, parseJSON,
 * byBook, reprice, renderView, zoneShort, formClass, melbTime).
 */

// ---------------------------------------------------------------- angles
const EXCUSE_RE = /(held up|checked|blocked|crowded|bumped|hampered|steadied|shoe|slow(ly)? (away|to begin)|missed the start|without cover|no clear run|clipped heels|eased|awkwardly)/i;

// Ratio of each angle's A/E to the baseline, older half / recent half, from the
// study on 37,743 runs (Nov 2026). Replaced by the live Pattern Lab numbers once loaded.
const ANGLE_INFO = {
  'Won last start':                         { short: 'Won last', side: 'back', old: 1.06, recent: 1.17 },
  'Led and won last start':                 { short: 'Led & won', side: 'back', old: 1.02, recent: 1.18 },
  'Up 200m+ in trip':                       { short: 'Up in trip', side: 'back', old: 1.05, recent: 1.04 },
  'Priced $3 to $6':                        { short: '$3–$6', side: 'back', old: 1.04, recent: 1.07 },
  'Hard-luck excuse last start (stewards)': { short: 'Hard-luck story', side: 'fade', old: 0.97, recent: 0.79 },
  'Beaten 1L or less last start':           { short: 'Just beaten', side: 'fade', old: 0.98, recent: 0.92 },
  'Down 200m+ in trip':                     { short: 'Down in trip', side: 'fade', old: 0.93, recent: 0.93 },
  'Priced $25+':                            { short: '$25+', side: 'fade', old: 0.92, recent: 0.84 },
};
let LAB_ROWS = null;   // live rows from edge_angle_stats

function anglesFor(r, race) {
  const runs = parseJSON(r.last_runs, []);
  const last = runs[0];
  const out = [];
  const add = name => { const i = ANGLE_INFO[name]; if (i) out.push({ name, ...i }); };
  if (last) {
    if (last.pos === 1 && last.settle === 1) add('Led and won last start');
    else if (last.pos === 1) add('Won last start');
    if (last.dist && race && race.distance) {
      if (race.distance - last.dist >= 200) add('Up 200m+ in trip');
      if (last.dist - race.distance >= 200) add('Down 200m+ in trip');
    }
    if (last.comment && EXCUSE_RE.test(last.comment)) add('Hard-luck excuse last start (stewards)');
    if (last.pos > 1 && last.margin !== null && last.margin !== undefined && Math.abs(last.margin) <= 1) add('Beaten 1L or less last start');
  }
  const px = r._market;
  if (px && px >= 3 && px < 6) add('Priced $3 to $6');
  if (px && px >= 25) add('Priced $25+');
  return out;
}

function angleTip(a) {
  const pct = v => (v >= 1 ? '+' : '') + Math.round((v - 1) * 100) + '%';
  return `${a.name}: winners vs what the starting price expected, against the average runner: ${pct(a.old)} in the older history, ${pct(a.recent)} recently. ` +
         (a.side === 'back' ? 'The market under-rates these.' : 'The market over-rates these.');
}

function angleTags(r, race) {
  return anglesFor(r, race).map(a =>
    `<span class="pill ${a.side === 'back' ? 'sect-green' : 'sect-red'} mr-1" title="${esc(angleTip(a))}">${a.side === 'back' ? '▲' : '▼'} ${esc(a.short)}</span>`).join('');
}

// ---------------------------------------------------------------- modifiers
const MOD_KEY = 'edge_mods_v1';
const MOD_CAP = 6;           // max total modifier points per horse (score scale)
const TOGGLES = [
  { id: 'onpace',   label: 'Track favouring on-pace runners', help: 'Leader / box seat / handy +2, back half and backmarkers −2',
    f: r => ['Leader', "Leader's Back / Box Seat", 'Handy'].includes(r.map_zone) ? 2 : ['Worse Than Midfield', 'Backmarker'].includes(r.map_zone) ? -2 : 0 },
  { id: 'swoop',    label: 'Track favouring swoopers', help: 'Back half and backmarkers +2, leader / box seat / handy −2',
    f: r => ['Worse Than Midfield', 'Backmarker'].includes(r.map_zone) ? 2 : ['Leader', "Leader's Back / Box Seat", 'Handy'].includes(r.map_zone) ? -2 : 0 },
  { id: 'inside',   label: 'Inside draws favoured', help: 'Barriers 1–4 +1.5, barrier 10+ −1.5',
    f: r => r.barrier <= 4 ? 1.5 : r.barrier >= 10 ? -1.5 : 0 },
  { id: 'outside',  label: 'Wide draws favoured (off the fence)', help: 'Barrier 10+ +1.5, barriers 1–4 −1.5',
    f: r => r.barrier >= 10 ? 1.5 : r.barrier <= 4 ? -1.5 : 0 },
  { id: 'collapse', label: 'Speed will collapse', help: 'Leader and speed-duel runners −2, back half and backmarkers +1.5',
    f: r => (r.map_zone === 'Leader' || r.map_tag === 'Contested Duel') ? -2 : ['Worse Than Midfield', 'Backmarker'].includes(r.map_zone) ? 1.5 : 0 },
  { id: 'crawl',    label: 'Slow pace expected', help: 'Leader / box seat +2, back half and backmarkers −2',
    f: r => ['Leader', "Leader's Back / Box Seat"].includes(r.map_zone) ? 2 : ['Worse Than Midfield', 'Backmarker'].includes(r.map_zone) ? -2 : 0 },
  { id: 'nowide',   label: 'Penalise caught wide (3W no cover)', help: '3-wide no cover −1.5',
    f: r => r.map_tag === '3WNC' ? -1.5 : 0 },
  { id: 'fadeluck', label: 'Fade hard-luck stories (Pattern Lab)', help: 'Excuse in the stewards report last start −1.5',
    f: (r, race) => anglesFor(r, race).some(a => a.name.startsWith('Hard-luck')) ? -1.5 : 0 },
  { id: 'winners',  label: 'Back last-start winners (Pattern Lab)', help: 'Won last start +1.5',
    f: (r, race) => anglesFor(r, race).some(a => a.name.includes('won last') || a.name === 'Won last start') ? 1.5 : 0 },
  { id: 'heavy',    label: 'Heavy track: 60kg+ struggles', help: '60kg or more −2.5',
    f: r => (r.weight || 0) >= 60 ? -2.5 : 0 },
];
const RULE_FIELDS = {
  barrier:        { label: 'Barrier', type: 'num', get: r => r.barrier },
  weight:         { label: 'Weight (kg)', type: 'num', get: r => r.weight },
  settle_rank:    { label: 'Map position (1 = leader)', type: 'num', get: r => r.settle_rank },
  map_zone:       { label: 'Map zone', type: 'enum', opts: ['Leader', "Leader's Back / Box Seat", 'Handy', 'Midfield', 'Worse Than Midfield', 'Backmarker'], get: r => r.map_zone },
  map_lane:       { label: 'Lane', type: 'enum', opts: ['Rail (Fence)', 'One-Off', '3-Wide', '4-Wide'], get: r => r.map_lane },
  prep_run:       { label: 'Run this prep', type: 'num', get: r => r.prep_run },
  form_gap_l:     { label: 'Form L (lengths vs par)', type: 'num', get: r => r.form_gap_l },
  days_since_run: { label: 'Days since last run', type: 'num', get: r => r.days_since_run },
  market:         { label: 'Live price', type: 'num', get: r => r._market },
  jockey:         { label: 'Jockey', type: 'text', get: r => r.jockey },
  trainer:        { label: 'Trainer', type: 'text', get: r => r.trainer },
  angle:          { label: 'Has angle', type: 'enum', opts: Object.values(ANGLE_INFO).map(a => a.short), get: (r, race) => anglesFor(r, race).map(a => a.short) },
};

const Mods = {
  state: { toggles: {}, rules: [] },
  load() { try { const s = JSON.parse(localStorage.getItem(MOD_KEY) || 'null'); if (s && s.rules) this.state = s; } catch (e) {} },
  save() { try { localStorage.setItem(MOD_KEY, JSON.stringify(this.state)); } catch (e) {} },
  togglesFor(mid) { return this.state.toggles[mid] || {}; },
  rulesFor(race) {
    return this.state.rules.filter(x => x.on !== false && (x.scope === 'always' || (x.scope === 'meeting' && x.meeting_id === race.meeting_id) || (x.scope === 'race' && x.race_id === race.race_id)));
  },
  ruleHits(rule, r, race) {
    const f = RULE_FIELDS[rule.field]; if (!f) return false;
    const v = f.get(r, race);
    if (f.type === 'num') {
      const x = parseFloat(rule.value); if (v === null || v === undefined || isNaN(x)) return false;
      return rule.op === '>=' ? v >= x : rule.op === '<=' ? v <= x : Math.abs(v - x) < 1e-9;
    }
    if (f.type === 'text') return String(v || '').toLowerCase().includes(String(rule.value || '').toLowerCase());
    if (Array.isArray(v)) return v.includes(rule.value);
    return v === rule.value;
  },
  breakdown(r, race) {
    const parts = [];
    const tg = this.togglesFor(race.meeting_id);
    TOGGLES.forEach(t => { if (tg[t.id]) { const p = t.f(r, race); if (p) parts.push({ name: t.label, p }); } });
    this.rulesFor(race).forEach(rule => { if (this.ruleHits(rule, r, race)) parts.push({ name: ruleText(rule), p: parseFloat(rule.pts) || 0 }); });
    let total = parts.reduce((s, x) => s + x.p, 0);
    total = Math.max(-MOD_CAP, Math.min(MOD_CAP, total));
    return { total, parts };
  },
  active(race) {
    const tg = this.togglesFor(race.meeting_id);
    return Object.values(tg).some(Boolean) || this.rulesFor(race).length > 0;
  },
  // Model weight for the book: the engine's chance scaled by the modifier on the
  // same softmax scale the engine uses (score / 8), re-normalised by reprice().
  chance(r, race) {
    const base = r.p_model || 0;
    if (!race || !this.active(race)) { r._mod = null; return base; }
    const b = this.breakdown(r, race);
    r._mod = b;
    return base * Math.exp(b.total / 8);
  },
};
Mods.load();
window.EdgeMods = Mods;

function ruleText(rule) {
  const f = RULE_FIELDS[rule.field] || { label: rule.field };
  const op = { '>=': '≥', '<=': '≤', '=': '=' }[rule.op] || (f.type === 'text' ? 'contains' : 'is');
  const scope = { race: 'this race', meeting: 'this meeting', always: 'every meeting' }[rule.scope] || '';
  const pts = parseFloat(rule.pts) || 0;
  return `${f.label} ${op} ${rule.value} → ${pts >= 0 ? '+' : ''}${pts} (${scope})`;
}

function currentRace() { return S.races.find(r => r.race_id === S.view); }

function renderMods() {
  const race = currentRace(); const box = document.getElementById('modsPanel');
  if (!race || !box) return;
  const tg = Mods.togglesFor(race.meeting_id);
  const rules = Mods.state.rules.filter(x => x.scope === 'always' || x.meeting_id === race.meeting_id);
  const fieldOpts = Object.entries(RULE_FIELDS).map(([k, f]) => `<option value="${k}">${esc(f.label)}</option>`).join('');
  box.innerHTML = `
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div>
        <h4 class="text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">Read the race (this meeting)</h4>
        <div class="space-y-2">${TOGGLES.map(t => `
          <label class="flex items-start gap-3 cursor-pointer p-2 bg-[#090c10] border border-[#1e2638] rounded hover:border-gray-600">
            <input type="checkbox" class="mt-0.5 w-4 h-4 accent-[#ff6600]" ${tg[t.id] ? 'checked' : ''} onchange="setToggle('${t.id}', this.checked)">
            <span><span class="text-sm text-white font-medium">${esc(t.label)}</span><br><span class="text-[11px] text-gray-500">${esc(t.help)}</span></span>
          </label>`).join('')}</div>
      </div>
      <div>
        <h4 class="text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">Your rules</h4>
        <div class="grid grid-cols-2 gap-2 mb-2">
          <select id="ruleField" class="syn-input p-2 text-xs col-span-2" onchange="ruleFieldChanged()">${fieldOpts}</select>
          <select id="ruleOp" class="syn-input p-2 text-xs"></select>
          <span id="ruleValueWrap"></span>
          <input id="rulePts" type="number" step="0.5" value="1.5" class="syn-input p-2 text-xs" title="Points on the score scale (+2 is roughly a 28% better chance)">
          <select id="ruleScope" class="syn-input p-2 text-xs">
            <option value="race">This race</option><option value="meeting" selected>This meeting</option><option value="always">Every meeting</option>
          </select>
          <button onclick="addRule()" class="col-span-2 btn-orange py-2 rounded font-bold text-xs uppercase">Add rule</button>
        </div>
        <div class="space-y-2">${rules.map(x => `
          <div class="flex items-center gap-2 p-2 bg-[#090c10] border border-[#1e2638] rounded">
            <input type="checkbox" class="w-4 h-4 accent-[#ff6600]" ${x.on !== false ? 'checked' : ''} onchange="setRuleOn('${x.id}', this.checked)">
            <span class="text-xs text-white flex-1">${esc(ruleText(x))}</span>
            <button onclick="deleteRule('${x.id}')" class="text-red-400 font-bold px-2" title="Delete rule">×</button>
          </div>`).join('') || '<div class="text-[11px] text-gray-500">No rules yet. Example: Jockey contains "Zahra" → +1.5.</div>'}</div>
        <p class="text-[11px] text-gray-500 mt-3">Points go on the engine score before pricing (capped at ±${MOD_CAP} a horse); True Odds, Edge and value flags re-calculate at once and the book still adds to 100%. Saved on this device only.</p>
        <button onclick="clearMods()" class="mt-2 text-[11px] text-gray-400 underline">Turn everything off for this meeting</button>
      </div>
    </div>`;
  ruleFieldChanged();
}

function ruleFieldChanged() {
  const f = RULE_FIELDS[document.getElementById('ruleField').value];
  const ops = f.type === 'num' ? [['>=', '≥ at least'], ['<=', '≤ at most'], ['=', '= exactly']] : f.type === 'text' ? [['contains', 'contains']] : [['is', 'is']];
  document.getElementById('ruleOp').innerHTML = ops.map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
  document.getElementById('ruleValueWrap').innerHTML = f.type === 'enum'
    ? `<select id="ruleValue" class="syn-input p-2 text-xs w-full">${f.opts.map(o => `<option>${esc(o)}</option>`).join('')}</select>`
    : `<input id="ruleValue" ${f.type === 'num' ? 'type="number" step="any"' : ''} class="syn-input p-2 text-xs w-full" placeholder="value">`;
}

function afterModChange() { Mods.save(); S.races.forEach(reprice); renderView(); renderMods(); }
function setToggle(id, on) { const race = currentRace(); const t = Mods.state.toggles[race.meeting_id] = Mods.state.toggles[race.meeting_id] || {}; t[id] = on; afterModChange(); }
function addRule() {
  const race = currentRace();
  const rule = { id: 'r' + Date.now(), field: document.getElementById('ruleField').value, op: document.getElementById('ruleOp').value,
                 value: document.getElementById('ruleValue').value.trim(), pts: document.getElementById('rulePts').value,
                 scope: document.getElementById('ruleScope').value, race_id: race.race_id, meeting_id: race.meeting_id, on: true };
  if (!rule.value || isNaN(parseFloat(rule.pts))) return;
  Mods.state.rules.push(rule); afterModChange();
}
function setRuleOn(id, on) { const x = Mods.state.rules.find(r => r.id === id); if (x) x.on = on; afterModChange(); }
function deleteRule(id) { Mods.state.rules = Mods.state.rules.filter(r => r.id !== id); afterModChange(); }
function clearMods() {
  const race = currentRace(); delete Mods.state.toggles[race.meeting_id];
  Mods.state.rules.forEach(x => { if (x.meeting_id === race.meeting_id && x.scope !== 'always') x.on = false; });
  afterModChange();
}
function toggleModsPanel() {
  const p = document.getElementById('modsPanel'); p.classList.toggle('hidden');
  if (!p.classList.contains('hidden')) renderMods();
}
function modBadge(r) {
  if (!r._mod || !r._mod.parts.length) return '';
  const t = r._mod.total;
  const tip = r._mod.parts.map(x => `${x.p >= 0 ? '+' : ''}${x.p} ${x.name}`).join('\n');
  return ` <span class="${t >= 0 ? 'text-emerald-400' : 'text-red-400'}" title="${esc(tip)}">${t >= 0 ? '+' : ''}${num(t, 1)}</span>`;
}

// ---------------------------------------------------------------- plays board
function renderPlays() {
  const box = document.getElementById('playsBoard'); if (!box) return;
  const best = [], over = [];
  S.races.forEach(race => {
    if (race.result_in) return;
    const rows = (S.runners[race.race_id] || []).filter(r => !r._scratched);
    const book = byBook(rows);
    rows.forEach(r => {
      const ang = anglesFor(r, race);
      const backs = ang.filter(a => a.side === 'back'), fades = ang.filter(a => a.side === 'fade');
      const top = book[0] === r;
      const goodMap = ['Leader', "Leader's Back / Box Seat", 'Handy'].includes(r.map_zone) && r.map_tag !== '3WNC';
      const reasons = [];
      if (r._value) reasons.push(`<span class="text-emerald-400 font-bold">value ${signed(r._edge * 100, 0, '%')}</span>`);
      if (top) reasons.push('top of our book');
      if (r.form_gap_l !== null && r.form_gap_l >= 0) reasons.push(`form ${signed(r.form_gap_l, 1, 'L')}`);
      if (goodMap) reasons.push(`maps ${esc(zoneShort(r.map_zone).toLowerCase())}`);
      if (r.best_stage && r.best_stage === r.prep_stage) reasons.push('best stage ★');
      if (r._value || (backs.length && !fades.length && ((r._edge ?? -1) >= 0.10 || (top && (r._edge ?? -1) > 0)))) {
        best.push({ race, r, ang, reasons, score: (r._value ? 100 : 0) + (r._edge || 0) * 100 + backs.length * 5 - fades.length * 8 });
      }
      if (r._market && r._fair && (r._edge ?? 0) <= -0.15 && fades.length > backs.length && r._market <= 6) {
        over.push({ race, r, ang });
      }
    });
  });
  best.sort((a, b) => b.score - a.score);
  over.sort((a, b) => (a.r._edge || 0) - (b.r._edge || 0));
  const row = (x, cls) => `
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 border-t border-[#1e2638] cursor-pointer hover:bg-white/[.02]" onclick="selectView('${x.race.race_id}')">
      <span class="text-[#ff6600] font-black w-8">R${x.race.race_number}</span>
      <span class="text-white font-bold min-w-[140px]">${x.r.saddlecloth ?? ''}. ${esc(x.r.horse_name)}</span>
      <span class="font-mono-numbers text-xs"><span class="text-[#ffa366]">${money(x.r._fair)}</span> vs <span class="text-white">${money(x.r._market)}</span></span>
      <span class="text-[11px] text-gray-400">${(x.reasons || []).join(' · ')}</span>
      <span>${x.ang.map(a => `<span class="pill ${a.side === 'back' ? 'sect-green' : 'sect-red'} mr-1" title="${esc(angleTip(a))}">${a.side === 'back' ? '▲' : '▼'} ${esc(a.short)}</span>`).join('')}</span>
    </div>`;
  box.innerHTML = `
    <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
      <div class="bg-[#11151d] p-5 rounded-xl border border-emerald-500/30">
        <h3 class="text-white font-black text-lg">Best plays</h3>
        <p class="text-[11px] text-gray-500 mb-2">Value flags first, then runners with a ▲ angle, no ▼, and either 10%+ edge or top of our book with an edge.</p>
        ${best.slice(0, 8).map(x => row(x)).join('') || '<div class="text-gray-500 text-sm py-2">Nothing qualifies yet. Refresh prices closer to the jump; edges move.</div>'}
      </div>
      <div class="bg-[#11151d] p-5 rounded-xl border border-red-500/30">
        <h3 class="text-white font-black text-lg">Overbet: think twice</h3>
        <p class="text-[11px] text-gray-500 mb-2">$6 or shorter, 15%+ under our price, and more ▼ angles than ▲. The market historically over-rates these. Lay candidates, or just leave them alone.</p>
        ${over.slice(0, 8).map(x => row(x)).join('') || '<div class="text-gray-500 text-sm py-2">No overbet runners on this card.</div>'}
      </div>
    </div>`;
}

// ---------------------------------------------------------------- horse page
const STAGE_OF = p => !p ? '–' : p >= 5 ? '5th-up+' : ['', '1st-up', '2nd-up', '3rd-up', '4th-up'][p];
const GOING_OF = g => { const w = String(g || '').split(' ')[0].toLowerCase(); return ['firm', 'good', 'dead'].includes(w) ? 'Good' : ['soft', 'slow'].includes(w) ? 'Soft' : w === 'heavy' ? 'Heavy' : w.startsWith('synth') ? 'Synthetic' : (w ? w[0].toUpperCase() + w.slice(1) : '–'); };
const DIST_OF = d => !d ? '–' : d <= 1100 ? '≤1100m' : d <= 1300 ? '1101–1300m' : d <= 1600 ? '1301–1600m' : d <= 2000 ? '1601–2000m' : '2001m+';
const SPACE_OF = n => n === null || n === undefined ? '–' : n <= 14 ? '≤14 days' : n <= 28 ? '15–28 days' : n <= 60 ? '29–60 days' : 'Spell (61+)';

function recordTable(title, runs, keyFn, todayKey, order) {
  const g = {};
  runs.forEach(x => { const k = keyFn(x); if (k === '–') return; (g[k] = g[k] || []).push(x); });
  let keys = Object.keys(g);
  keys.sort(order ? (a, b) => order.indexOf(a) - order.indexOf(b) : (a, b) => g[b].length - g[a].length);
  if (!order) keys = keys.slice(0, 6);
  const rows = keys.map(k => {
    const xs = g[k], w = xs.filter(x => x.finish_pos === 1).length, p = xs.filter(x => x.finish_pos && x.finish_pos <= 3).length;
    const rat = xs.map(x => x.wfa_rating).filter(v => v);
    const avg = rat.length ? rat.reduce((a, b) => a + b, 0) / rat.length : null;
    const hit = k === todayKey;
    return `<tr class="border-t border-[#1e2638] ${hit ? 'bg-[#ff6600]/10' : ''}">
      <td class="py-1.5 font-sans ${hit ? 'text-[#ff6600] font-bold' : 'text-gray-300'}">${esc(k)}${hit ? ' ◀ today' : ''}</td>
      <td class="text-center">${xs.length}</td><td class="text-center">${w}-${p - w}</td>
      <td class="text-center ${w / xs.length >= 0.25 ? 'text-emerald-400 font-bold' : ''}">${Math.round(w / xs.length * 100)}%</td>
      <td class="text-center">${Math.round(p / xs.length * 100)}%</td>
      <td class="text-center text-white">${num(avg, 1)}</td><td class="text-center">${num(rat.length ? Math.max(...rat) : null, 1)}</td></tr>`;
  }).join('');
  return `<div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3">
    <h4 class="text-[11px] font-bold text-gray-400 uppercase tracking-widest mb-1">${title}</h4>
    <table class="w-full font-mono-numbers text-[11px]"><thead class="text-gray-500 text-[10px] uppercase"><tr>
      <th class="text-left">&nbsp;</th><th>Runs</th><th>W-P</th><th>Win</th><th>Place</th><th>Avg rtg</th><th>Best</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="7" class="text-gray-500 py-1">–</td></tr>'}</tbody></table></div>`;
}

function ratingChart(runs, par) {
  const xs = runs.filter(x => x.wfa_rating).slice(0, 24).reverse();
  if (xs.length < 2) return '<div class="text-[11px] text-gray-500">Not enough rated runs to chart.</div>';
  const W = 720, H = 180, pl = 36, pr = 12, pt = 14, pb = 22;
  const vals = xs.map(x => x.wfa_rating).concat(par ? [par] : []);
  const lo = Math.floor(Math.min(...vals) - 2), hi = Math.ceil(Math.max(...vals) + 2);
  const X = i => pl + i * (W - pl - pr) / (xs.length - 1), Y = v => pt + (hi - v) / (hi - lo) * (H - pt - pb);
  const path = xs.map((x, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(x.wfa_rating).toFixed(1)}`).join(' ');
  const ticks = [lo, Math.round((lo + hi) / 2), hi];
  let svg = `<svg viewBox="0 0 ${W} ${H}" class="w-full" style="max-height:200px">`;
  ticks.forEach(t => { svg += `<line x1="${pl}" x2="${W - pr}" y1="${Y(t)}" y2="${Y(t)}" stroke="#1e2638"/><text x="${pl - 6}" y="${Y(t) + 3}" fill="#6b7280" font-size="10" text-anchor="end">${t}</text>`; });
  if (par) svg += `<line x1="${pl}" x2="${W - pr}" y1="${Y(par)}" y2="${Y(par)}" stroke="#ff6600" stroke-dasharray="4 4" opacity=".7"/><text x="${W - pr}" y="${Y(par) - 4}" fill="#ff6600" font-size="10" text-anchor="end">today's par ${num(par, 1)}</text>`;
  svg += `<path d="${path}" fill="none" stroke="#ffa366" stroke-width="2"/>`;
  xs.forEach((x, i) => {
    const c = x.finish_pos === 1 ? '#10b981' : x.finish_pos <= 3 ? '#f59e0b' : '#6b7280';
    svg += `<circle cx="${X(i)}" cy="${Y(x.wfa_rating)}" r="4.5" fill="${c}" stroke="#090c10" stroke-width="1.5"><title>${esc(x.race_date)} ${esc(x.track)} ${x.distance}m · ${x.finish_pos}/${x.field_size ?? ''} · rating ${num(x.wfa_rating, 1)} · ${STAGE_OF(x.race_in_prep)}</title></circle>`;
    if (x.race_in_prep === 1) svg += `<text x="${X(i)}" y="${H - 6}" fill="#6b7280" font-size="9" text-anchor="middle">1u</text>`;
  });
  return svg + '</svg><div class="text-[10px] text-gray-500">Form King rating per run, oldest to newest · green won · amber placed · "1u" marks a first-up run (new preparation).</div>';
}

function runsFromCard(r) {
  return parseJSON(r.last_runs, []).map(x => ({
    race_date: x.date, track: x.track, distance: x.dist, going: x.going, finish_pos: x.pos, field_size: x.field,
    margin: x.margin, settle_pos: x.settle, sp: x.sp, bsp: x.bsp, wfa_rating: x.rating, race_in_prep: x.prep,
    jockey: x.jockey, stewards_comment: x.comment, days_since_prev: null }));
}

function findInCard(name) {
  for (const race of S.races) {
    const r = (S.runners[race.race_id] || []).find(x => x.horse_name.toLowerCase() === String(name).toLowerCase());
    if (r) return { race, r };
  }
  return null;
}

async function openHorse(name) {
  const ov = document.getElementById('horseOverlay'), body = document.getElementById('horseBody');
  ov.classList.remove('hidden'); document.body.style.overflow = 'hidden';
  body.innerHTML = `<div class="p-10 text-center text-gray-400">Loading ${esc(name)}…</div>`;
  const ctx = findInCard(name);
  let runs = null, source = 'database';
  try {
    const { data, error } = await sb.rpc('edge_horse_runs', { p_name: name });
    if (error) throw error;
    runs = data || [];
  } catch (e) { runs = null; }
  if (!runs || !runs.length) { runs = ctx ? runsFromCard(ctx.r) : []; source = 'card'; }
  renderHorse(name, runs, ctx, source);
}
function closeHorse() { document.getElementById('horseOverlay').classList.add('hidden'); document.body.style.overflow = ''; }

function renderHorse(name, runs, ctx, source) {
  const r = ctx && ctx.r, race = ctx && ctx.race;
  const w = runs.filter(x => x.finish_pos === 1).length, p = runs.filter(x => x.finish_pos && x.finish_pos <= 3).length;
  const todayStage = r ? r.prep_stage : null;
  const todayGoing = r ? GOING_OF(S.meeting && S.meeting.going) : null;
  const todayDist = race ? DIST_OF(race.distance) : null;
  const todayTrack = r ? (S.meeting && S.meeting.track) : null;
  const todaySpace = r ? SPACE_OF(r.days_since_run) : null;
  const facts = r ? [r.age ? `${r.age}yo ${esc(r.sex || '')}` : '', r.sire ? `by ${esc(r.sire)}` : '', r.trainer ? `trainer ${esc(r.trainer)}` : '', r.career ? `career ${esc(r.career)}` : ''].filter(Boolean).join(' · ') : '';
  const today = r ? `
    <div class="bg-[#0d1117] border border-[#ff6600]/40 rounded-lg p-3 text-xs flex flex-wrap gap-x-5 gap-y-1 items-center">
      <span class="text-[#ff6600] font-black">TODAY R${race.race_number}</span>
      <span>${race.distance}m ${esc(race.class_name)}</span><span>barrier ${r.barrier ?? '–'}</span><span>${num(r.weight, 1)}kg ${esc(r.jockey || '')}</span>
      <span>${esc(r.prep_stage || '')}${r.best_stage === r.prep_stage && r.best_stage ? ' ★' : ''}</span>
      <span>maps ${esc(zoneShort(r.map_zone).toLowerCase() || '–')}${r.map_lane ? ', ' + esc(r.map_lane.toLowerCase()) : ''}</span>
      <span class="${formClass(r.form_gap_l)}">form ${signed(r.form_gap_l, 1, 'L')}</span>
      <span>true <b class="text-[#ffa366]">${money(r._fair)}</b> · live <b class="text-white">${money(r._market)}</b></span>
      <span>${angleTags(r, race)}</span>
    </div>` : '';
  const stageOrder = ['1st-up', '2nd-up', '3rd-up', '4th-up', '5th-up+'];
  const goingOrder = ['Good', 'Soft', 'Heavy', 'Synthetic'];
  const distOrder = ['≤1100m', '1101–1300m', '1301–1600m', '1601–2000m', '2001m+'];
  const spaceOrder = ['≤14 days', '15–28 days', '29–60 days', 'Spell (61+)'];
  document.getElementById('horseBody').innerHTML = `
    <div class="flex justify-between items-start gap-3 mb-3">
      <div>
        <h2 class="text-white font-black text-2xl">${esc(name)}</h2>
        <div class="text-[11px] text-gray-400">${facts}</div>
        <div class="text-xs text-gray-300 mt-1 font-mono-numbers">${runs.length} runs on file · ${w} wins · ${p - w} placings · ${runs.length ? Math.round(w / runs.length * 100) : 0}% win · ${runs.length ? Math.round(p / runs.length * 100) : 0}% place</div>
      </div>
      <button onclick="closeHorse()" class="text-gray-400 hover:text-white text-2xl font-bold px-2" title="Close">×</button>
    </div>
    ${today}
    ${source === 'card' ? '<div class="text-[11px] text-amber-300 mt-2">Showing the last runs from today\'s card. Full history appears after the next engine run.</div>' : ''}
    <div class="mt-4 bg-[#0d1117] border border-[#1e2638] rounded-lg p-3">${ratingChart(runs, race && race.form_par)}</div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
      ${recordTable('Preparation stage', runs, x => STAGE_OF(x.race_in_prep), todayStage, stageOrder)}
      ${recordTable('Track condition', runs, x => GOING_OF(x.going), todayGoing, goingOrder)}
      ${recordTable('Distance', runs, x => DIST_OF(x.distance), todayDist, distOrder)}
      ${recordTable('Days between runs', runs, x => SPACE_OF(x.days_since_prev), todaySpace, spaceOrder)}
      ${recordTable('Tracks', runs, x => x.track || '–', todayTrack, null)}
      ${recordTable('Jockeys', runs, x => x.jockey || '–', r ? r.jockey : null, null)}
    </div>
    <h3 class="text-white font-black text-lg mt-5 mb-2">Every run</h3>
    <div class="overflow-x-auto"><table class="w-full text-[11px] font-mono-numbers">
      <thead class="text-gray-500 uppercase text-[10px]"><tr>
        <th class="text-left py-1">Date</th><th class="text-left">Track</th><th>Dist</th><th class="text-left">Going</th><th>Stage</th><th>Bar</th><th>Wt</th>
        <th>Fin</th><th>Margin</th><th>Settled</th><th>800</th><th>400</th><th>Rating</th><th>SP</th><th class="text-left">Jockey</th><th class="text-left">Stewards</th></tr></thead>
      <tbody>${runs.map(x => `
        <tr class="border-t border-[#1e2638]">
          <td class="py-1 whitespace-nowrap">${esc(x.race_date || '')}</td><td class="font-sans">${esc(x.track || '')}</td><td class="text-center">${x.distance ?? ''}</td>
          <td>${esc(x.going || '')}</td><td class="text-center">${STAGE_OF(x.race_in_prep)}</td><td class="text-center">${x.barrier ?? ''}</td><td class="text-center">${num(x.weight, 1)}</td>
          <td class="text-center ${x.finish_pos === 1 ? 'text-emerald-400 font-bold' : ''}">${x.finish_pos ?? ''}${x.field_size ? '/' + x.field_size : ''}</td>
          <td class="text-center">${x.margin === null || x.margin === undefined ? '' : x.finish_pos === 1 ? signed(x.margin, 1) : num(Math.abs(x.margin), 1)}</td>
          <td class="text-center">${x.settle_pos ?? ''}</td><td class="text-center">${x.pos_800 ?? ''}</td><td class="text-center">${x.pos_400 ?? ''}</td>
          <td class="text-center text-white">${num(x.wfa_rating, 1)}</td><td class="text-center">${money(x.sp)}</td>
          <td class="font-sans whitespace-nowrap">${esc(x.jockey || '')}</td>
          <td class="font-sans ${x.stewards_comment ? 'text-amber-300' : 'text-gray-600'}">${esc(x.stewards_comment || '')}</td>
        </tr>`).join('') || '<tr><td colspan="16" class="py-3 text-gray-500">No runs on file.</td></tr>'}</tbody>
    </table></div>`;
}

// search tab
let _searchT = null;
function horseSearchInput(v) {
  clearTimeout(_searchT);
  _searchT = setTimeout(() => horseSearch(v.trim()), 250);
}
async function horseSearch(q) {
  const box = document.getElementById('horseResults');
  if (q.length < 2) { box.innerHTML = '<div class="text-gray-500 text-sm">Type at least two letters.</div>'; return; }
  const today = [];
  S.races.forEach(race => (S.runners[race.race_id] || []).forEach(r => { if (r.horse_name.toLowerCase().includes(q.toLowerCase())) today.push({ race, r }); }));
  let db = [];
  try { const { data, error } = await sb.rpc('edge_horse_search', { q }); if (!error) db = data || []; } catch (e) {}
  const seen = new Set(today.map(x => x.r.horse_name));
  const item = (name, sub) => `<button onclick='openHorse(${JSON.stringify(name).replace(/'/g, "&#39;")})' class="w-full text-left p-3 bg-[#11151d] border border-[#1e2638] rounded-lg hover:border-[#ff6600]/60">
      <div class="text-white font-bold">${esc(name)}</div><div class="text-[11px] text-gray-500">${sub}</div></button>`;
  box.innerHTML =
    (today.length ? `<div class="text-[11px] text-[#ff6600] font-bold uppercase tracking-widest">Running today</div>` + today.map(x => item(x.r.horse_name, `R${x.race.race_number} ${esc(S.meeting.track || '')} · ${money(x.r._fair)} true`)).join('') : '') +
    (db.filter(x => !seen.has(x.horse_name)).length ? `<div class="text-[11px] text-gray-400 font-bold uppercase tracking-widest mt-3">In the database</div>` +
      db.filter(x => !seen.has(x.horse_name)).map(x => item(x.horse_name, `${x.runs} runs · last ${esc(x.last_run || '')}`)).join('') : '') ||
    '<div class="text-gray-500 text-sm">No horse found.</div>';
}

// ---------------------------------------------------------------- pattern lab
async function loadLab() {
  const box = document.getElementById('labBody');
  box.innerHTML = '<div class="p-6 text-gray-400 text-sm">Running the study on the history database…</div>';
  let rows = null;
  try { const { data, error } = await sb.rpc('edge_angle_stats'); if (error) throw error; rows = data; } catch (e) { rows = null; }
  if (rows && rows.length) {
    LAB_ROWS = rows;
    const base = rows.find(x => x.side === '');
    rows.forEach(x => { const i = ANGLE_INFO[x.angle]; if (i && base && base.ae_old && base.ae_recent && x.ae_old && x.ae_recent) { i.old = x.ae_old / base.ae_old; i.recent = x.ae_recent / base.ae_recent; } });
  }
  renderLab(rows);
}
function renderLab(rows) {
  const box = document.getElementById('labBody');
  const live = !!(rows && rows.length);
  const base = live ? rows.find(x => x.side === '') : null;
  const list = Object.entries(ANGLE_INFO).map(([name, i]) => {
    const lr = live ? rows.find(x => x.angle === name) : null;
    return { name, i, n: lr ? (Number(lr.n_old) + Number(lr.n_recent)) : null, strike: lr ? lr.strike : null, roi: lr ? lr.roi_sp : null };
  });
  if (live) rows.filter(x => !ANGLE_INFO[x.angle] && x.side !== '').forEach(x => list.push({ name: x.angle, i: { side: x.side, old: base && x.ae_old ? x.ae_old / base.ae_old : null, recent: base && x.ae_recent ? x.ae_recent / base.ae_recent : null }, n: Number(x.n_old) + Number(x.n_recent), strike: x.strike, roi: x.roi_sp }));
  const pct = v => v === null || v === undefined ? '–' : (v >= 1 ? '+' : '') + Math.round((v - 1) * 100) + '%';
  const verdict = i => (i.old >= 1.03 && i.recent >= 1.03) ? '<span class="pill sect-green">PROVEN: market under-rates</span>'
    : (i.old <= 0.97 && i.recent <= 0.97) ? '<span class="pill sect-red">PROVEN: market over-rates</span>' : '<span class="pill sect-yellow">NOT PROVEN</span>';
  box.innerHTML = `
    <p class="text-sm text-gray-300 mb-3">Each angle compares <b class="text-white">actual winners</b> with the winners the starting price expected (A/E), against the average runner. An angle counts only when it holds up in <b class="text-white">both</b> the older and the recent half of the history. That's how a syndicate avoids betting on luck.</p>
    <div class="overflow-x-auto"><table class="w-full text-left font-mono-numbers text-xs">
      <thead class="bg-[#0d1117] text-gray-500 uppercase text-[10px] tracking-wider"><tr>
        <th class="p-3 font-sans">Angle</th><th class="p-3">Older history</th><th class="p-3">Recent</th><th class="p-3">Runs</th><th class="p-3">Strike</th><th class="p-3" title="Level-stakes return at SP, before survivorship correction">ROI at SP</th><th class="p-3">Verdict</th></tr></thead>
      <tbody class="divide-y divide-[#1e2638]">${list.map(x => `
        <tr><td class="p-3 font-sans text-white font-bold">${esc(x.name)}</td>
          <td class="p-3 ${x.i.old >= 1 ? 'text-emerald-400' : 'text-red-400'}">${pct(x.i.old)}</td>
          <td class="p-3 ${x.i.recent >= 1 ? 'text-emerald-400' : 'text-red-400'}">${pct(x.i.recent)}</td>
          <td class="p-3">${x.n ?? '–'}</td><td class="p-3">${x.strike === null || x.strike === undefined ? '–' : x.strike + '%'}</td>
          <td class="p-3 text-gray-400">${x.roi === null || x.roi === undefined ? '–' : x.roi + '%'}</td><td class="p-3">${verdict(x.i)}</td></tr>`).join('')}</tbody>
    </table></div>
    <div class="text-[11px] text-gray-500 mt-3 space-y-1">
      <p>${live ? `Live from the database: ${base ? (Number(base.n_old) + Number(base.n_recent)).toLocaleString() : ''} runs, split at 1 May 2026.` : 'Live study not available yet (it switches on after the next engine run). Showing the study from 9 Nov 2026: 37,743 runs.'}</p>
      <p>The history only holds horses that are still racing, which flatters every raw ROI. That's why the verdict uses each angle's ratio to the average runner, not the ROI column. ▲ and ▼ tags on the cards come from this table.</p>
    </div>`;
}

// ---------------------------------------------------------------- track record
async function loadRecord() {
  const box = document.getElementById('recordBody');
  box.innerHTML = '<div class="p-6 text-gray-400 text-sm">Grading every flag…</div>';
  const { data: flags, error } = await sb.from('edge_runners').select('race_id,horse_name,saddlecloth,market_price,fair_price,edge_pct,finish_pos,result_bsp,result_sp,stake').eq('value_flag', 1).limit(2000);
  if (error) { box.innerHTML = `<div class="p-6 text-red-400 text-sm">Could not read the database: ${esc(error.message)}</div>`; return; }
  const ids = [...new Set((flags || []).map(f => f.race_id))];
  let races = [];
  for (let i = 0; i < ids.length; i += 150) {
    const { data } = await sb.from('edge_races').select('race_id,meeting_id,meeting_date,race_number,distance,class_name,result_in').in('race_id', ids.slice(i, i + 150));
    races = races.concat(data || []);
  }
  const mids = [...new Set(races.map(r => r.meeting_id))];
  const { data: meets } = mids.length ? await sb.from('edge_meetings').select('meeting_id,track').in('meeting_id', mids) : { data: [] };
  const R = Object.fromEntries(races.map(r => [r.race_id, r])), M = Object.fromEntries((meets || []).map(m => [m.meeting_id, m]));
  const graded = (flags || []).filter(f => R[f.race_id] && R[f.race_id].result_in && f.finish_pos && f.market_price > 1)
    .map(f => { const stake = 100 / (f.market_price - 1); const win = f.finish_pos === 1;
      return { ...f, race: R[f.race_id], track: (M[R[f.race_id].meeting_id] || {}).track, stake, pl: win ? 100 : -stake, win,
               clv: f.result_bsp ? f.market_price / f.result_bsp - 1 : null }; })
    .sort((a, b) => (b.race.meeting_date || '').localeCompare(a.race.meeting_date || '') || a.race.race_number - b.race.race_number);
  const pending = (flags || []).length - graded.length;
  const n = graded.length, wins = graded.filter(g => g.win).length;
  const staked = graded.reduce((s, g) => s + g.stake, 0), pl = graded.reduce((s, g) => s + g.pl, 0);
  const clvs = graded.map(g => g.clv).filter(v => v !== null);
  const expW = graded.reduce((s, g) => s + (g.fair_price ? 1 / g.fair_price : 0), 0);
  const tile = (label, val, tone = 'text-white', tip = '') => `<div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3" title="${esc(tip)}"><div class="text-[10px] text-gray-500 uppercase tracking-widest">${label}</div><div class="text-xl font-black font-mono-numbers ${tone}">${val}</div></div>`;
  box.innerHTML = `
    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 mb-4">
      ${tile('Bets graded', n)}${tile('Winners', `${wins} (${n ? Math.round(wins / n * 100) : 0}%)`)}
      ${tile('Expected winners', num(expW, 1), 'text-[#ffa366]', 'What our true odds said these flags should win. Actual above expected = the model is finding real edges.')}
      ${tile('Staked', '$' + Math.round(staked).toLocaleString())}
      ${tile('Profit / loss', (pl >= 0 ? '+$' : '−$') + Math.abs(Math.round(pl)).toLocaleString(), pl >= 0 ? 'text-emerald-400' : 'text-red-400')}
      ${tile('ROI', staked ? signed(pl / staked * 100, 1, '%') : '–', pl >= 0 ? 'text-emerald-400' : 'text-red-400')}
      ${tile('Avg CLV vs BSP', clvs.length ? signed(clvs.reduce((a, b) => a + b, 0) / clvs.length * 100, 1, '%') : '–', 'text-white', 'Our price against the Betfair starting price. Beating BSP over time is the best early sign of a real edge, long before profit is reliable.')}
    </div>
    <p class="text-[11px] text-gray-500 mb-3">To-win-$100 staking at the price published before the race (stake = 100 ÷ (price − 1)). ${pending > 0 ? pending + ' flags are still waiting on results.' : ''} Flags are frozen once a race result arrives, so this can't be rewritten after the fact.</p>
    <div class="overflow-x-auto"><table class="w-full text-left font-mono-numbers text-xs">
      <thead class="bg-[#0d1117] text-gray-500 uppercase text-[10px] tracking-wider"><tr>
        <th class="p-3">Date</th><th class="p-3 font-sans">Race</th><th class="p-3 font-sans">Horse</th><th class="p-3">Taken</th><th class="p-3">True</th><th class="p-3">BSP</th><th class="p-3">CLV</th><th class="p-3">Fin</th><th class="p-3">Stake</th><th class="p-3">P/L</th></tr></thead>
      <tbody class="divide-y divide-[#1e2638]">${graded.map(g => `
        <tr><td class="p-3">${esc(g.race.meeting_date || '')}</td><td class="p-3 font-sans">${esc(g.track || '')} R${g.race.race_number}</td>
          <td class="p-3 font-sans text-white font-bold">${esc(g.horse_name)}</td><td class="p-3">${money(g.market_price)}</td><td class="p-3 text-[#ffa366]">${money(g.fair_price)}</td>
          <td class="p-3">${money(g.result_bsp)}</td><td class="p-3 ${g.clv > 0 ? 'text-emerald-400' : 'text-gray-400'}">${g.clv === null ? '–' : signed(g.clv * 100, 0, '%')}</td>
          <td class="p-3 ${g.win ? 'text-emerald-400 font-bold' : ''}">${g.finish_pos}</td><td class="p-3">$${num(g.stake, 2)}</td>
          <td class="p-3 ${g.pl >= 0 ? 'text-emerald-400' : 'text-red-400'}">${g.pl >= 0 ? '+' : '−'}$${num(Math.abs(g.pl), 2)}</td></tr>`).join('') ||
        '<tr><td colspan="10" class="p-8 text-center text-gray-500">No graded flags yet. Results arrive with the night sync; the record builds from here.</td></tr>'}</tbody>
    </table></div>`;
}

// ---------------------------------------------------------------- meeting review extras
function renderReviewSummary() {
  const box = document.getElementById('reviewSummary'); if (!box) return;
  const done = S.races.filter(r => r.result_in);
  if (!done.length) { box.innerHTML = ''; return; }
  let n = 0, wins = 0, staked = 0, pl = 0, topW = 0, topExp = 0;
  const follow = [];
  done.forEach(race => {
    const rows = S.runners[race.race_id] || [];
    const book = rows.slice().filter(r => r.p_blend).sort((a, b) => b.p_blend - a.p_blend);
    if (book[0]) { topExp += book[0].p_blend; if (book[0].finish_pos === 1) topW++; }
    rows.forEach(r => {
      if (r.value_flag && r.market_price > 1 && r.finish_pos) {
        const st = 100 / (r.market_price - 1); n++; staked += st;
        if (r.finish_pos === 1) { wins++; pl += 100; } else pl -= st;
      }
      if (r.finish_pos > 1 && r.result_rating && race.form_par && r.result_rating >= race.form_par) {
        follow.push({ race, r, why: `ran ${num(r.result_rating, 1)}, at or above the winning par ${num(race.form_par, 1)}` });
      }
    });
  });
  box.innerHTML = `
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-4">
        <div class="text-[10px] text-gray-500 uppercase tracking-widest mb-1">Value flags this meeting</div>
        <div class="text-white font-black text-xl font-mono-numbers">${n} bets · ${wins} won</div>
        <div class="font-mono-numbers text-sm ${pl >= 0 ? 'text-emerald-400' : 'text-red-400'}">${pl >= 0 ? '+' : '−'}$${num(Math.abs(pl), 0)} on $${num(staked, 0)} staked</div>
      </div>
      <div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-4">
        <div class="text-[10px] text-gray-500 uppercase tracking-widest mb-1">Top of our book</div>
        <div class="text-white font-black text-xl font-mono-numbers">${topW} of ${done.length} won</div>
        <div class="text-sm text-gray-400 font-mono-numbers">expected ${num(topExp, 1)} from our prices</div>
      </div>
      <div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-4">
        <div class="text-[10px] text-gray-500 uppercase tracking-widest mb-1">Horses to follow</div>
        ${follow.slice(0, 6).map(x => `<div class="text-xs"><button class="text-white font-bold hover:text-[#ff6600]" onclick='openHorse(${JSON.stringify(x.r.horse_name).replace(/'/g, "&#39;")})'>${esc(x.r.horse_name)}</button> <span class="text-gray-500">R${x.race.race_number}, ${x.r.finish_pos}th: ${x.why}</span></div>`).join('') || '<div class="text-xs text-gray-500">No beaten runner reached the winning standard.</div>'}
        <div class="text-[10px] text-gray-500 mt-2">Beaten runners that ran to a winning rating. Watch their price next start: the Pattern Lab shows the market over-bets eye-catching losers, so only back them when we have value.</div>
      </div>
    </div>`;
}

// ---------------------------------------------------------------- wire up
window.addEventListener('keydown', e => { if (e.key === 'Escape') closeHorse(); });
