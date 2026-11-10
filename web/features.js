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

// ---------------------------------------------------------------- rated runs vs par
// Lengths per Form King rating point by distance, fitted from same-race pairs in
// the history (model report, Nov 2026). A race's own fitted value is used when
// the engine publishes one.
const LPP = [[950, 0.471], [1250, 0.549], [1550, 0.614], [1900, 0.673], [2400, 0.740]];
function lppFor(d, race) {
  if (race && race.lengths_per_point) return race.lengths_per_point;
  if (!d) return 0.6;
  if (d <= LPP[0][0]) return LPP[0][1];
  for (let i = 1; i < LPP.length; i++) if (d <= LPP[i][0]) { const [x0, y0] = LPP[i - 1], [x1, y1] = LPP[i]; return y0 + (y1 - y0) * (d - x0) / (x1 - x0); }
  return LPP[LPP.length - 1][1];
}
// Lengths a rating sits above (+) or below (-) today's winning par.
function lengthsVsPar(rating, race) {
  if (!rating || !race || !race.form_par) return null;
  return (rating - race.form_par) * lppFor(race.distance, race);
}
const PAR_BAND = 2;   // lengths: within 2L under par = "around the par"
function ratingClass(rating, par, race) {
  if (!rating || !par) return 'text-gray-300';
  const l = (rating - par) * lppFor(race ? race.distance : (S.races.find(x => x.race_id === S.view) || {}).distance, race);
  return l >= 0 ? 'text-emerald-400' : l >= -PAR_BAND ? 'text-amber-300' : 'text-red-400';
}
function formTip(v) {
  if (v === null || v === undefined) return 'No rated runs to judge.';
  const a = Math.abs(v).toFixed(1);
  return v >= 0 ? `Expected to run ${a} lengths better than a typical winner of this class at this level of track: good enough to win.`
    : v >= -PAR_BAND ? `Expected to run ${a} lengths below a typical winner here: around the mark, needs a little improvement or a soft race.`
    : `Expected to run ${a} lengths below a typical winner here: needs big improvement.`;
}
// Last five rated runs as coloured chips (oldest to newest, last start on the right).
function ratedRuns(r, race) {
  const runs = parseJSON(r.last_runs, []).filter(x => x.rating).slice(0, 5).reverse();
  if (!runs.length) return '<span class="text-[10px] text-gray-600">no rated runs</span>';
  return '<span class="inline-flex gap-1 items-center">' + runs.map(x => {
    const l = lengthsVsPar(x.rating, race);
    const cls = l === null ? 'border-[#1e2638] text-gray-300' : l >= 0 ? 'border-emerald-500/60 text-emerald-300 bg-emerald-500/10'
      : l >= -PAR_BAND ? 'border-amber-500/60 text-amber-300 bg-amber-500/10' : 'border-red-500/50 text-red-300 bg-red-500/10';
    const tip = `${x.date || ''} ${x.track || ''} ${x.dist ?? ''}m · ${x.pos ?? '?'}/${x.field ?? '?'} · rating ${num(x.rating, 1)}` +
      (l === null ? '' : ` · ${l >= 0 ? '+' : ''}${l.toFixed(1)}L vs today's par ${num(race.form_par, 1)}`);
    return `<span class="px-1.5 py-0.5 rounded border text-[10px] font-mono-numbers font-bold ${cls}" data-tip="${esc(tip)}">${Math.round(x.rating)}${x.pos === 1 ? '<sup>w</sup>' : ''}</span>`;
  }).join('') + '</span>';
}

// ---------------------------------------------------------------- average + going suitability
function avgRating(r, n = 5) {
  const xs = parseJSON(r.last_runs, []).map(x => x.rating).filter(v => v).slice(0, n);
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
}
function avgBadge(r) {
  const a = avgRating(r);
  return a === null ? '' : ` <span class="text-gray-400 font-normal text-[11px] font-mono-numbers" title="Average Form King rating of its last ${Math.min(5, parseJSON(r.last_runs, []).filter(x => x.rating).length)} rated runs">(${a.toFixed(1)})</span>`;
}

// Form King's going records: good + dead = dry (Good 1-4), slow = soft (5-7),
// heavy (8-10), synthetic.
const BAND_KEYS = { Good: ['good', 'dead', 'fast', 'firm'], Soft: ['slow', 'soft'], Heavy: ['heavy'], Synthetic: ['synthetic'] };
const BAND_LABEL = { Good: 'Dry', Soft: 'Soft', Heavy: 'Heavy', Synthetic: 'Synthetic' };
function parseRec(x) {
  const m = String(x || '').match(/^(\d+):(\d+)-(\d+)-(\d+)/);
  return m ? { n: +m[1], w: +m[2], s: +m[3], t: +m[4] } : null;
}
function goingRecords(r) {
  const g = parseJSON(r.going_form, null);
  const runs = parseJSON(r.last_runs, []);
  const out = {};
  Object.entries(BAND_KEYS).forEach(([band, keys]) => {
    const rec = { n: 0, w: 0, p: 0, ratings: [] };
    let any = false;
    if (g) keys.forEach(k => { const q = parseRec(g[k]); if (q) { any = true; rec.n += q.n; rec.w += q.w; rec.p += q.w + q.s + q.t; } });
    runs.forEach(x => { if (x.rating && GOING_OF(x.going) === band) rec.ratings.push(x.rating); });
    if (!any) {   // no Form King record published yet: count the runs we hold
      runs.forEach(x => { if (GOING_OF(x.going) === band && x.pos) { rec.n++; if (x.pos === 1) rec.w++; if (x.pos <= 3) rec.p++; } });
    }
    rec.avg = rec.ratings.length ? rec.ratings.reduce((a, b) => a + b, 0) / rec.ratings.length : null;
    out[band] = rec;
  });
  return out;
}
function bandVerdict(rec, overallAvg) {
  if (!rec || !rec.n) return { v: 'unraced', cls: 'border-[#1e2638] text-gray-400' };
  const wp = rec.w / rec.n, pp = rec.p / rec.n;
  const lift = rec.avg !== null && overallAvg !== null && rec.ratings.length >= 2 ? rec.avg - overallAvg : 0;
  if (wp >= 0.25 || (rec.n >= 2 && pp >= 0.5) || lift >= 2) return { v: 'suited', cls: 'sect-green' };
  if (rec.n >= 3 && rec.w === 0 && pp < 0.25 || lift <= -2.5) return { v: 'poor', cls: 'sect-red' };
  return { v: 'fair', cls: 'sect-yellow' };
}
function goingTag(r, race) {
  const band = GOING_OF((S.meeting || {}).going);
  if (!BAND_KEYS[band]) return '';
  const recs = goingRecords(r), rec = recs[band], ov = avgRating(r, 8);
  const v = bandVerdict(rec, ov);
  const label = BAND_LABEL[band];
  const txt = v.v === 'unraced' ? `${label}?` : v.v === 'suited' ? `✓ ${label}` : v.v === 'poor' ? `✗ ${label}` : `~ ${label}`;
  const tip = v.v === 'unraced' ? `Never raced on a ${label.toLowerCase()} track.` :
    `${label} record ${rec.n}: ${rec.w} wins, ${rec.p} placings (${Math.round(rec.p / rec.n * 100)}% placed)` +
    (rec.avg !== null ? `; average rating ${rec.avg.toFixed(1)} on ${label.toLowerCase()} vs ${ov !== null ? ov.toFixed(1) : '–'} overall` : '') + `. Today: ${(S.meeting || {}).going || ''}.`;
  return `<span class="pill ${v.cls} mr-1" title="${esc(tip)}">${txt}</span>`;
}
function goingDetail(r, race) {
  const recs = goingRecords(r), ov = avgRating(r, 8);
  const today = GOING_OF((S.meeting || {}).going);
  const cells = Object.keys(BAND_KEYS).map(b => {
    const rec = recs[b], v = bandVerdict(rec, ov);
    return `<div class="px-3 py-2 rounded-lg border ${b === today ? 'border-[#ff6600]/60' : 'border-[#1e2638]'} bg-[#0d1117] text-xs">
      <div class="text-[10px] uppercase tracking-widest ${b === today ? 'text-[#ff6600]' : 'text-gray-500'}">${BAND_LABEL[b]}${b === today ? ' · today' : ''}</div>
      <div class="font-mono-numbers text-white mt-0.5">${rec.n ? `${rec.n}: ${rec.w}-${rec.p - rec.w} <span class="text-gray-500">(${Math.round(rec.p / rec.n * 100)}% placed)</span>` : '<span class="text-gray-500">unraced</span>'}</div>
      <div class="text-[10px] mt-0.5"><span class="pill ${v.cls}">${v.v.toUpperCase()}</span>${rec.avg !== null ? ` <span class="text-gray-400">avg ${rec.avg.toFixed(1)}</span>` : ''}</div></div>`;
  }).join('');
  const wet = ['Soft', 'Heavy'].map(b => recs[b]).filter(x => x.n >= 2), dry = recs.Good;
  const pct = x => x.n ? x.p / x.n : 0;
  let pref = '';
  if (wet.length && dry.n >= 2) {
    const wp = Math.max(...wet.map(pct)), dp = pct(dry);
    if (wp - dp >= 0.2) pref = '<span class="pill sect-green">WET TRACKER</span> places more often on soft/heavy';
    else if (dp - wp >= 0.2) pref = '<span class="pill sect-yellow">DRY TRACKER</span> places more often on dry tracks';
  }
  return `<div class="mt-3 text-[10px] text-gray-500 uppercase tracking-widest">Track condition record</div>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-2 mt-1">${cells}</div>
    ${pref ? `<div class="text-[11px] text-gray-300 mt-2">${pref}</div>` : ''}`;
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
      <td class="py-2 font-sans ${hit ? 'text-[#ff6600] font-bold' : 'text-gray-300'}">${esc(k)}${hit ? ' ◀ today' : ''}</td>
      <td class="text-center">${xs.length}</td><td class="text-center">${w}-${p - w}</td>
      <td class="text-center ${w / xs.length >= 0.25 ? 'text-emerald-400 font-bold' : ''}">${Math.round(w / xs.length * 100)}%</td>
      <td class="text-center">${Math.round(p / xs.length * 100)}%</td>
      <td class="text-center text-white">${num(avg, 1)}</td><td class="text-center">${num(rat.length ? Math.max(...rat) : null, 1)}</td></tr>`;
  }).join('');
  return `<div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-4">
    <h4 class="text-[11px] font-bold text-gray-400 uppercase tracking-widest mb-2">${title}</h4>
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
    svg += `<circle cx="${X(i)}" cy="${Y(x.wfa_rating)}" r="4.5" fill="${c}" stroke="#090c10" stroke-width="1.5"/><circle cx="${X(i)}" cy="${Y(x.wfa_rating)}" r="10" fill="transparent" data-tip="${esc(`${x.race_date} ${x.track} ${x.distance}m · ${x.finish_pos}/${x.field_size ?? ''} · rating ${num(x.wfa_rating, 1)} · ${STAGE_OF(x.race_in_prep)}`)}"/>`;
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
        <div class="mt-2">${typeof bbButton === 'function' ? bbButton(name) : ''}</div>
      </div>
      <button onclick="closeHorse()" class="text-gray-400 hover:text-white text-2xl font-bold px-2" title="Close">×</button>
    </div>
    ${today}
    ${source === 'card' ? '<div class="text-[11px] text-amber-300 mt-2">Showing the last runs from today\'s card. Full history appears after the next engine run.</div>' : ''}
    <div class="mt-6 bg-[#0d1117] border border-[#1e2638] rounded-lg p-4">${ratingChart(runs, race && race.form_par)}</div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-5 mt-6">
      ${recordTable('Preparation stage', runs, x => STAGE_OF(x.race_in_prep), todayStage, stageOrder)}
      ${recordTable('Track condition', runs, x => GOING_OF(x.going), todayGoing, goingOrder)}
      ${recordTable('Distance', runs, x => DIST_OF(x.distance), todayDist, distOrder)}
      ${recordTable('Days between runs', runs, x => SPACE_OF(x.days_since_prev), todaySpace, spaceOrder)}
      ${recordTable('Tracks', runs, x => x.track || '–', todayTrack, null)}
      ${recordTable('Jockeys', runs, x => x.jockey || '–', r ? r.jockey : null, null)}
    </div>
    <h3 class="text-white font-black text-lg mt-8 mb-3">Every run</h3>
    <div class="overflow-x-auto"><table class="w-full text-[11px] font-mono-numbers">
      <thead class="text-gray-500 uppercase text-[10px]"><tr>
        <th class="text-left py-1">Date</th><th class="text-left">Track</th><th>Dist</th><th class="text-left">Going</th><th>Stage</th><th>Bar</th><th>Wt</th>
        <th>Fin</th><th>Margin</th><th>Settled</th><th>800</th><th>400</th><th>Rating</th><th>SP</th><th class="text-left">Jockey</th><th class="text-left">Stewards</th></tr></thead>
      <tbody>${runs.map(x => `
        <tr class="border-t border-[#1e2638]">
          <td class="py-2 pr-2 whitespace-nowrap">${esc(x.race_date || '')}</td>
          <td class="font-sans">${x.race_id ? `<button class="hover:text-[#ff6600] underline decoration-dotted decoration-gray-600 underline-offset-4" data-tip="Open this race in full" onclick='openPastRace(${jsq(x.race_id)}, ${jsq(name)})'>${esc(x.track || '')}</button>` : esc(x.track || '')}</td>
          <td class="text-center">${x.distance ?? ''}</td>
          <td>${esc(x.going || '')}</td><td class="text-center">${STAGE_OF(x.race_in_prep)}</td><td class="text-center">${x.barrier ?? ''}</td><td class="text-center">${num(x.weight, 1)}</td>
          <td class="text-center ${x.finish_pos === 1 ? 'text-emerald-400 font-bold' : ''}">${x.finish_pos ?? ''}${x.field_size ? '/' + x.field_size : ''}</td>
          <td class="text-center">${x.margin === null || x.margin === undefined ? '' : x.finish_pos === 1 ? signed(x.margin, 1) : num(Math.abs(x.margin), 1)}</td>
          <td class="text-center">${x.settle_pos ?? ''}</td><td class="text-center">${x.pos_800 ?? ''}</td><td class="text-center">${x.pos_400 ?? ''}</td>
          <td class="text-center font-bold ${race ? ratingClass(x.wfa_rating, race.form_par, race) : 'text-white'}">${num(x.wfa_rating, 1)}</td><td class="text-center">${money(x.sp)}</td>
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

async function modelCard() {
  let p = null;
  try { const { data, error } = await sb.rpc('edge_model_report', { p_name: 'v2' }); if (!error && data && data[0]) p = JSON.parse(data[0].params_json); } catch (e) {}
  const el = document.getElementById('modelCard'); if (!el) return;
  if (!p) { el.innerHTML = '<div class="text-sm text-gray-400">Model v2 hasn\'t been fitted yet.</div>'; return; }
  const o = p.overlays || {}, b = p.all_in_band || {}, u = p.unders || {};
  const DESC = { mkt: 'Market price', gap_l: 'Form L (rating vs par)', no_form: 'No rated runs', rel: 'Depth of form', last_l: 'Last start vs par',
    best3_l: 'Best of last 3 vs par', trend: 'Ratings trend', won_last: 'Won last start', close_last: 'Just beaten last start', excuse_last: 'Excuse last start',
    up_trip: 'Up 200m+ in trip', down_trip: 'Down 200m+ in trip', first_up: '1st-up', second_up: '2nd-up', third_up: '3rd-up', log_days: 'Days since last run',
    going_suit: 'Suited by today\'s going', unraced_going: 'Unraced on today\'s going', early: 'Settles back (vs leads)', barrier_frac: 'Wide barrier' };
  const imp = Object.entries(p.importance_per_sd || {}).filter(([k]) => k !== 'mkt').sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const mx = Math.max(0.01, ...imp.map(([, v]) => Math.abs(v)));
  const tile = (l, v, sub, tone = 'text-white') => `<div class="bg-[#0d1117] border border-[#1e2638] rounded-lg p-3"><div class="text-[10px] text-gray-500 uppercase tracking-widest">${l}</div><div class="text-xl font-black font-mono-numbers ${tone}">${v}</div><div class="text-[10px] text-gray-500">${sub}</div></div>`;
  el.innerHTML = `
    <div class="flex flex-wrap items-center gap-2 mb-3"><h3 class="text-white font-black text-lg">Model v2: fitted on results</h3>
      <span class="pill ${p.use_for_pricing || p.validated ? 'sect-green' : 'sect-yellow'} py-1">${p.use_for_pricing || p.validated ? 'PRICING THE CARDS' : 'NOT PRICING: 70/30 BLEND STILL USED'}</span>
      <span class="pill ${p.overlays_proven || p.validated ? 'sect-green' : 'sect-yellow'} py-1">${p.overlays_proven || p.validated ? 'OVERLAYS PROVEN' : 'OVERLAYS NOT PROVEN YET'}</span>
      <span class="pill ${p.fades_proven ? 'sect-green' : 'sect-yellow'} py-1">${p.fades_proven ? 'FADES PROVEN' : 'FADES NOT PROVEN'}</span>
      <span class="text-[11px] text-gray-500">fitted ${esc((p.fitted_at || '').slice(0, 10))} on ${Number(p.n_all).toLocaleString()} runs</span></div>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
      ${tile('Better than the market?', `${p.logloss_gain_pct >= 0 ? '+' : ''}${p.logloss_gain_pct}%`, 'log-loss on races it never saw', p.logloss_gain_pct > 0 ? 'text-emerald-400' : 'text-red-400')}
      ${tile('Its overlays', o.n ? `A/E ${o.ae}` : '–', o.n ? `${o.n} bets · ${o.strike}% strike · ROI ${o.roi_sp}% at SP` : '', (p.overlay_ae_vs_base || 0) >= 1.03 ? 'text-emerald-400' : 'text-white')}
      ${tile('Every runner $2.20-$18', b.n ? `A/E ${b.ae}` : '–', b.n ? `${b.n} runs · ROI ${b.roi_sp}% at SP` : '')}
      ${tile('Its unders (fades)', u.n ? `A/E ${u.ae}` : '–', u.n ? `${u.n} runs · ROI ${u.roi_sp}% at SP` : '', (u.ae || 1) < (b.ae || 0) ? 'text-emerald-400' : 'text-white')}
    </div>
    <div class="text-[10px] text-gray-500 uppercase tracking-widest mb-1">What it learned (beyond the price): green = more winners than the price expects, red = fewer</div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1">${imp.map(([k, v]) => `
      <div class="flex items-center gap-2 text-xs"><span class="w-44 text-gray-300">${esc(DESC[k] || k)}</span>
        <div class="flex-1 h-2 bg-[#0d1117] rounded relative"><div class="absolute top-0 h-2 rounded ${v >= 0 ? 'bg-emerald-500 left-1/2' : 'bg-red-500 right-1/2'}" style="width:${Math.abs(v) / mx * 50}%"></div></div>
        <span class="w-12 text-right font-mono-numbers ${v >= 0 ? 'text-emerald-400' : 'text-red-400'}">${v >= 0 ? '+' : ''}${v.toFixed(2)}</span></div>`).join('')}</div>
    <p class="text-[10px] text-gray-500 mt-2">Trained on runs before ${esc(p.split)}, tested on the ${Number(p.n_test).toLocaleString()} runs after. It prices the cards once it is more accurate than the market on that unseen data (lower log-loss on 2,000+ runs). Overlays count as proven when they win 3%+ more than their price says on 100+ bets; fades when they win 10%+ less on 200+. Market weight ${Number(p.market_coef).toFixed(2)} (1.00 = takes the price at face value). Refits every Monday.</p>`;
}

// ---------------------------------------------------------------- meeting review extras
function renderReviewSummary() {
  const box = document.getElementById('reviewSummary'); if (!box) return;
  const done = S.races.filter(r => r.result_in);
  if (!done.length) { box.innerHTML = meetingStatusBar() || '<div class="text-sm text-gray-500">Nothing run yet at this meeting.</div>'; return; }
  let n = 0, wins = 0, staked = 0, pl = 0, topW = 0, topExp = 0;
  const follow = [];
  done.forEach(race => {
    const rows = S.runners[race.race_id] || [];
    const book = rows.slice().filter(r => r.p_blend).sort((a, b) => b.p_blend - a.p_blend);
    if (book[0]) { topExp += book[0].p_blend; if (book[0].finish_pos === 1) topW++; }
    rows.forEach(r => {
      if (r.value_flag && r.market_price > 1 && r.finish_pos) {
        const st = Math.min(100 / (r.market_price - 1), 75); n++; staked += st;
        if (r.finish_pos === 1) { wins++; pl += st * (r.market_price - 1); } else pl -= st;
      }
      if (r.finish_pos > 1 && r.result_rating && race.form_par && r.result_rating >= race.form_par) {
        follow.push({ race, r, why: `ran ${num(r.result_rating, 1)}, at or above the winning par ${num(race.form_par, 1)}` });
      } else if (r.finish_pos > 1 && r.finish_pos <= 4 && !r.result_rating && r.margin !== null && Math.abs(r.margin) <= 1.5 && (r.result_bsp || 0) >= 6) {
        follow.push({ race, r, why: `beaten ${num(Math.abs(r.margin), 1)}L at $${num(r.result_bsp, 2)} on Betfair (ratings land in a day or two)` });
      }
    });
  });
  box.innerHTML = meetingStatusBar() + `
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
        <div class="text-[10px] text-gray-500 mt-2">Beaten runners that ran to a winning rating (or, until ratings land, roughies beaten 1.5L or less). Watch their price next start: the Pattern Lab shows the market over-bets eye-catching losers, so only back them when we have value.</div>
      </div>
    </div>`;
}

// ---------------------------------------------------------------- wire up
window.addEventListener('keydown', e => { if (e.key === 'Escape') closeHorse(); });


// ---------------------------------------------------------------- instant tooltips
// Anything with data-tip shows its text straight away on hover (the browser's own
// title tooltip waits about a second).
(function () {
  const tip = document.createElement('div');
  tip.style.cssText = 'position:fixed;z-index:80;pointer-events:none;display:none;max-width:320px;background:#0d1117;border:1px solid #ff6600;color:#e6edf3;font:600 11px/1.4 "Plus Jakarta Sans",sans-serif;padding:6px 9px;border-radius:8px;box-shadow:0 6px 24px rgba(0,0,0,.5)';
  const place = e => {
    const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
    let x = e.clientX + pad, y = e.clientY + pad;
    if (x + w > innerWidth - 8) x = e.clientX - w - pad;
    if (y + h > innerHeight - 8) y = e.clientY - h - pad;
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  };
  document.addEventListener('mouseover', e => {
    const el = e.target.closest && e.target.closest('[data-tip]');
    if (!el) { tip.style.display = 'none'; return; }
    tip.textContent = el.getAttribute('data-tip');
    tip.style.display = 'block'; place(e);
  });
  document.addEventListener('mousemove', e => { if (tip.style.display === 'block') place(e); });
  document.addEventListener('scroll', () => { tip.style.display = 'none'; }, true);
  window.addEventListener('DOMContentLoaded', () => document.body.appendChild(tip));
  if (document.body) document.body.appendChild(tip);
})();


// ---------------------------------------------------------------- meeting review: ALL
// A snapshot of every meeting on the selected date: winners, the market, our
// book, the best runs and horses to follow.
const REV = { date: null, data: null, loading: false };

async function loadReviewDay(date) {
  const { data: meets } = await sb.from('edge_meetings').select('*').eq('meeting_date', date);
  const mids = (meets || []).map(m => m.meeting_id);
  let races = [], runners = [];
  if (mids.length) {
    const r1 = await sb.from('edge_races').select('*').in('meeting_id', mids).order('race_number');
    races = r1.data || [];
    const ids = races.map(r => r.race_id);
    for (let i = 0; i < ids.length; i += 60) {
      const r2 = await sb.from('edge_runners').select('*').in('race_id', ids.slice(i, i + 60));
      runners = runners.concat(r2.data || []);
    }
  }
  let hist = [];
  try {
    const { data, error } = await sb.rpc('edge_race_runs', { p_race_ids: races.map(r => r.race_id) });
    if (!error) hist = data || [];
  } catch (e) {}
  return { meets: meets || [], races, runners, hist };
}

async function renderReviewAll() {
  const box = document.getElementById('reviewAllView');
  if (REV.date !== S.date || !REV.data) {
    if (REV.loading) return;
    REV.loading = true;
    box.innerHTML = '<div class="bg-[#11151d] border border-[#1e2638] rounded-xl p-8 text-gray-400">Pulling every meeting for this date…</div>';
    try { REV.data = await loadReviewDay(S.date); REV.date = S.date; } finally { REV.loading = false; }
  }
  const { meets, races, runners, hist } = REV.data;
  const M = Object.fromEntries(meets.map(m => [m.meeting_id, m]));
  const H = {}; hist.forEach(h => { H[h.race_id + '|' + h.horse_name] = h; });
  const byRace = {}; runners.forEach(r => { if (!r.scratched) (byRace[r.race_id] = byRace[r.race_id] || []).push(r); });
  const done = races.filter(r => r.result_in);
  if (!done.length) {
    box.innerHTML = `<div class="bg-[#11151d] border border-[#1e2638] rounded-xl p-8 text-gray-400">No results yet for ${esc(S.date)}. They land with the night sync (about 11:30pm), or press Sync Data after the last race.</div>`;
    return;
  }
  const tag = race => `${esc((M[race.meeting_id] || {}).track || '')} R${race.race_number}`;
  const rated = (race, r) => { const h = H[race.race_id + '|' + r.horse_name] || {}; return r.result_rating || h.wfa_rating || null; };
  // ---- per race facts
  let favWins = 0, topWins = 0, topExp = 0, vN = 0, vW = 0, vSt = 0, vPl = 0;
  const winners = [], bestRuns = [], movers = [], follow = [], upsets = [], beatenFavs = [];
  done.forEach(race => {
    const rows = (byRace[race.race_id] || []).filter(r => r.finish_pos);
    if (!rows.length) return;
    const win = rows.find(r => r.finish_pos === 1);
    const spFav = rows.filter(r => r.result_sp).sort((a, b) => a.result_sp - b.result_sp)[0];
    const book = rows.filter(r => r.p_blend).sort((a, b) => b.p_blend - a.p_blend);
    const top = book[0];
    if (spFav && spFav.finish_pos === 1) favWins++;
    if (top) { topExp += top.p_blend; if (top.finish_pos === 1) topWins++; }
    rows.forEach(r => {
      if (r.value_flag && r.market_price > 1) { const st = Math.min(100 / (r.market_price - 1), 75); vN++; vSt += st; if (r.finish_pos === 1) { vW++; vPl += st * (r.market_price - 1); } else vPl -= st; }
      const rt = rated(race, r);
      if (rt) bestRuns.push({ race, r, rt, l: lengthsVsPar(rt, race) });
      const h = H[race.race_id + '|' + r.horse_name] || {};
      const from = h.pos_800 || h.settle_pos;
      if (from && r.finish_pos && from - r.finish_pos >= 4) movers.push({ race, r, from, gain: from - r.finish_pos, at: h.pos_800 ? '800m' : 'settling' });
      const m = r.margin !== null && r.margin !== undefined ? Math.abs(r.margin) : null;
      const reasons = [];
      if (r.finish_pos > 1 && rt && race.form_par && rt >= race.form_par) reasons.push(`ran ${num(rt, 1)}, at or above the winning par`);
      if (r.finish_pos > 1 && r.finish_pos <= 4 && m !== null && m <= 1.5 && (r.result_bsp || r.result_sp || 0) >= 6) reasons.push(`beaten ${num(m, 1)}L at ${money(r.result_bsp || r.result_sp)}`);
      if (from && r.finish_pos > 1 && from - r.finish_pos >= 5 && m !== null && m <= 3) reasons.push(`made ${from - r.finish_pos} spots from the ${h.pos_800 ? '800m' : 'settle'}`);
      if (h.stewards_comment && EXCUSE_RE.test(h.stewards_comment) && r.finish_pos > 1 && m !== null && m <= 4) reasons.push('had an excuse (stewards)');
      if (reasons.length) follow.push({ race, r, reasons, score: reasons.length * 10 - (m || 0) });
    });
    if (win) {
      winners.push({ race, win, spFav, top, ourRank: book.indexOf(win) + 1 });
      if ((win.result_bsp || win.result_sp || 0) >= 15) upsets.push({ race, r: win });
    }
    if (spFav && spFav.finish_pos > 1) beatenFavs.push({ race, r: spFav });
  });
  bestRuns.sort((a, b) => (b.l ?? -99) - (a.l ?? -99) || b.rt - a.rt);
  movers.sort((a, b) => b.gain - a.gain);
  follow.sort((a, b) => b.score - a.score);
  upsets.sort((a, b) => (b.r.result_bsp || b.r.result_sp) - (a.r.result_bsp || a.r.result_sp));
  const n = done.length;
  const tile = (label, val, sub = '', tone = 'text-white') => `<div class="bg-[#11151d] border border-[#1e2638] rounded-xl p-4"><div class="text-[10px] text-gray-500 uppercase tracking-widest">${label}</div><div class="text-2xl font-black font-mono-numbers ${tone} mt-1">${val}</div><div class="text-[11px] text-gray-500">${sub}</div></div>`;
  const card = (title, sub, body) => `<div class="bg-[#11151d] border border-[#1e2638] rounded-xl p-5 shadow-2xl"><h3 class="text-white font-black text-lg">${title}</h3>${sub ? `<p class="text-[11px] text-gray-500 mb-2">${sub}</p>` : ''}${body}</div>`;
  const horseBtn = r => `<button class="text-white font-bold hover:text-[#ff6600]" onclick='openHorse(${JSON.stringify(r.horse_name).replace(/'/g, "&#39;")})'>${esc(r.horse_name)}</button>`;
  const winRows = winners.map(w => `
    <tr class="border-t border-[#1e2638]">
      <td class="py-2 pr-3 text-[#ff6600] font-bold whitespace-nowrap">${tag(w.race)}</td>
      <td class="pr-3 text-gray-400 whitespace-nowrap">${w.race.distance}m ${esc(w.race.class_name || '')}</td>
      <td class="pr-3">${horseBtn(w.win)}</td>
      <td class="px-2 text-right">${money(w.win.result_sp)}</td><td class="px-2 text-right">${money(w.win.result_bsp)}</td>
      <td class="px-2 text-right text-[#ffa366]">${money(w.win.fair_price)}</td>
      <td class="px-2 text-center ${w.ourRank === 1 ? 'text-emerald-400 font-bold' : w.ourRank <= 3 ? 'text-amber-300' : 'text-gray-400'}">${w.ourRank > 0 ? ordinalTxt(w.ourRank) : '–'}</td>
      <td class="px-2 text-right">${num(w.win.margin, 1)}L</td>
      <td class="pl-3 text-gray-300 whitespace-nowrap">${w.spFav ? `${esc(w.spFav.horse_name)} <span class="text-gray-500">${money(w.spFav.result_sp)} → ${ordinalTxt(w.spFav.finish_pos)}</span>` : '–'}</td>
    </tr>`).join('');
  const hasRatings = bestRuns.length > 0, hasInRun = hist.some(h => h.pos_800 || h.settle_pos);
  box.innerHTML = `
    <div class="flex flex-wrap items-end justify-between gap-2">
      <div><h2 class="text-white font-black text-2xl uppercase tracking-widest">Day review: ${esc(S.date)}</h2>
        <div class="text-[11px] text-gray-500">${meets.map(m => esc(m.track)).join(' · ')} · ${n} of ${races.length} races resulted</div></div>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      ${tile('Favourites won', `${favWins}/${n}`, `${Math.round(favWins / n * 100)}% (normal is about 33%)`)}
      ${tile('Our top pick won', `${topWins}/${n}`, `expected ${num(topExp, 1)} from our prices`, topWins >= topExp ? 'text-emerald-400' : 'text-white')}
      ${tile('Value flags won', `${vW}/${vN}`, vN ? `${vPl >= 0 ? '+' : '−'}$${num(Math.abs(vPl), 0)} on $${num(vSt, 0)} staked` : 'no flags on the day', vPl > 0 ? 'text-emerald-400' : vPl < 0 ? 'text-red-400' : 'text-white')}
      ${tile('Average winning SP', money(winners.reduce((a, w) => a + (w.win.result_sp || 0), 0) / Math.max(1, winners.length)), 'starting price')}
      ${tile('$15+ winners', upsets.length, upsets.length ? upsets.map(u => esc(u.r.horse_name)).slice(0, 2).join(', ') : '')}
      ${tile('Beaten favourites', beatenFavs.length, `${n - favWins} races`)}
    </div>
    ${card('Every winner', 'Our price and where our book had the winner (1st = our top pick). Favourite = shortest starting price.', `
      <div class="overflow-x-auto"><table class="w-full font-mono-numbers text-xs">
        <thead class="text-gray-500 uppercase text-[10px]"><tr><th class="text-left py-2">Race</th><th class="text-left">Trip / class</th><th class="text-left font-sans">Winner</th><th class="text-right px-2">SP</th><th class="text-right px-2">BSP</th><th class="text-right px-2">Our price</th><th class="px-2">Our rank</th><th class="text-right px-2">Margin</th><th class="text-left pl-3">Favourite</th></tr></thead>
        <tbody>${winRows}</tbody></table></div>`)}
    <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
      ${card('Highest-rated runs', 'Form King rating for the run, in lengths against the winning par for that race.', hasRatings ? bestRuns.slice(0, 10).map(x => `
        <div class="flex flex-wrap justify-between gap-2 py-2 border-t border-[#1e2638] text-xs"><span>${horseBtn(x.r)} <span class="text-gray-500">${tag(x.race)} · ${ordinalTxt(x.r.finish_pos)}</span></span>
          <span class="font-mono-numbers"><b class="${x.l !== null && x.l >= 0 ? 'text-emerald-400' : x.l !== null && x.l >= -2 ? 'text-amber-300' : 'text-red-400'}">${num(x.rt, 1)}</b> <span class="text-gray-500">${x.l === null ? '' : (x.l >= 0 ? '+' : '') + x.l.toFixed(1) + 'L vs par'}</span></span></div>`).join('')
        : '<div class="text-sm text-gray-400 py-2">Ratings for these runs aren\'t in yet. Form King adds the rating (and the stewards report and in-run positions) to a horse\'s record after the meeting; we pick them up as each runner\'s next card is pulled, so this fills in over the following days.</div>')}
      ${card('Made the most ground', 'Positions gained from the 800m (or from where it settled) to the finish.', hasInRun && movers.length ? movers.slice(0, 10).map(x => `
        <div class="flex flex-wrap justify-between gap-2 py-2 border-t border-[#1e2638] text-xs"><span>${horseBtn(x.r)} <span class="text-gray-500">${tag(x.race)}</span></span>
          <span class="font-mono-numbers text-gray-300">${ordinalTxt(x.from)} at the ${x.at} → <b class="text-white">${ordinalTxt(x.r.finish_pos)}</b> <span class="text-emerald-400">(+${x.gain})</span></span></div>`).join('')
        : '<div class="text-sm text-gray-400 py-2">In-run positions come with the rating, a few days after the meeting. Until then this stays empty.</div>')}
    </div>
    ${card('Horses to follow', 'From everything we hold on the day: ran to a winning rating but beaten, roughies beaten narrowly, big ground made, and excuses. The Pattern Lab shows the market over-bets eye-catching losers, so follow the price, not just the horse.', follow.length ? `
      <div class="grid grid-cols-1 md:grid-cols-2 gap-x-6">${follow.slice(0, 16).map(x => `
        <div class="py-2 border-t border-[#1e2638] text-xs">${horseBtn(x.r)} <span class="text-gray-500">${tag(x.race)} · ${ordinalTxt(x.r.finish_pos)}</span>
          <div class="text-gray-300 mt-0.5">${x.reasons.map(esc).join(' · ')}</div></div>`).join('')}</div>` : '<div class="text-sm text-gray-400 py-2">Nobody stands out yet. More appear as ratings and in-run data land.</div>')}
    <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
      ${card('Upsets', 'Winners at $15+ starting price.', upsets.map(x => `<div class="py-2 border-t border-[#1e2638] text-xs">${horseBtn(x.r)} <span class="text-gray-500">${tag(x.race)}</span> <span class="font-mono-numbers text-white">${money(x.r.result_sp)}</span> <span class="text-gray-500">(BSP ${money(x.r.result_bsp)}, our price ${money(x.r.fair_price)})</span></div>`).join('') || '<div class="text-sm text-gray-500 py-2">None.</div>')}
      ${card('Beaten favourites', '', beatenFavs.map(x => `<div class="py-2 border-t border-[#1e2638] text-xs">${horseBtn(x.r)} <span class="text-gray-500">${tag(x.race)}</span> <span class="font-mono-numbers">${money(x.r.result_sp)} → ${ordinalTxt(x.r.finish_pos)}, ${num(Math.abs(x.r.margin ?? 0), 1)}L</span></div>`).join('') || '<div class="text-sm text-gray-500 py-2">Every favourite won.</div>')}
    </div>
    <div class="bg-[#0d1117] border border-[#1e2638] rounded-xl p-4 text-[11px] text-gray-400">
      <b class="text-gray-300">Sectionals (last 200/400/600/800m):</b> Form King doesn't supply individual sectional times, only the overall race time, so they can't be shown honestly from this feed. Racing.com publishes them per race; I can bring those in if you want them (see the note in chat).
    </div>`;
}
function ordinalTxt(n) { return !n ? '–' : n + (['th', 'st', 'nd', 'rd'][(n % 100 > 10 && n % 100 < 14) ? 0 : (n % 10 < 4 ? n % 10 : 0)]); }


// ---------------------------------------------------------------- through the preparation
// Average / best rating at each stage of a preparation, from the full history
// when loaded (falls back to the runs on the card).
const PREP_HIST = {};
function prepStageBlock(r, race) {
  const id = 'prep_' + String(r.horse_name).replace(/[^a-z0-9]/gi, '_');
  const full = PREP_HIST[r.horse_name];
  if (!full) {
    sb.rpc('edge_horse_runs', { p_name: r.horse_name }).then(({ data }) => {
      PREP_HIST[r.horse_name] = (data && data.length) ? data.map(x => ({ prep: x.race_in_prep, rating: x.wfa_rating, pos: x.finish_pos }))
        : parseJSON(r.last_runs, []).map(x => ({ prep: x.prep, rating: x.rating, pos: x.pos }));
      const el = document.getElementById(id); if (el) el.outerHTML = prepStageBlock(r, race);
    }).catch(() => {});
  }
  const runs = full || parseJSON(r.last_runs, []).map(x => ({ prep: x.prep, rating: x.rating, pos: x.pos }));
  const stages = [1, 2, 3, 4, 5];
  const st = {};
  stages.forEach(k => st[k] = { n: 0, w: 0, p: 0, rs: [] });
  runs.forEach(x => { if (!x.prep) return; const k = Math.min(x.prep, 5); const o = st[k]; o.n++; if (x.pos === 1) o.w++; if (x.pos && x.pos <= 3) o.p++; if (x.rating) o.rs.push(x.rating); });
  const avg = k => st[k].rs.length ? st[k].rs.reduce((a, b) => a + b, 0) / st[k].rs.length : null;
  const today = Math.min(r.prep_run || 0, 5);
  const withAvg = stages.filter(k => avg(k) !== null && st[k].rs.length >= 1);
  const peak = withAvg.length ? withAvg.reduce((a, b) => avg(b) > avg(a) ? b : a) : null;
  const lbl = k => k === 5 ? '5th-up+' : STAGE_OF(k);
  const cells = stages.map(k => {
    const a = avg(k), l = a !== null ? lengthsVsPar(a, race) : null;
    const tone = l === null ? 'text-gray-300' : l >= 0 ? 'text-emerald-400' : l >= -PAR_BAND ? 'text-amber-300' : 'text-red-400';
    return `<div class="rounded-lg p-3 border ${k === today ? 'border-[#ff6600] bg-[#ff6600]/10' : 'border-[#1e2638] bg-[#0d1117]'}">
      <div class="flex justify-between items-center"><span class="text-[10px] uppercase tracking-widest ${k === today ? 'text-[#ff6600] font-bold' : 'text-gray-500'}">${lbl(k)}${k === today ? ' · today' : ''}</span>${k === peak && withAvg.length > 1 ? '<span class="pill sect-green">PEAK</span>' : ''}</div>
      <div class="text-xl font-black font-mono-numbers mt-1 ${tone}">${a === null ? '–' : a.toFixed(1)}</div>
      <div class="text-[10px] text-gray-400 font-mono-numbers">${l === null ? '' : (l >= 0 ? '+' : '−') + Math.abs(l).toFixed(1) + 'L vs par · '}best ${st[k].rs.length ? Math.max(...st[k].rs).toFixed(1) : '–'}</div>
      <div class="text-[10px] text-gray-500 font-mono-numbers">${st[k].n ? `${st[k].n} runs: ${st[k].w}-${st[k].p - st[k].w}` : 'no runs'}</div></div>`;
  }).join('');
  let read = '';
  if (peak && today && withAvg.length > 1) {
    const ta = avg(today), pa = avg(peak);
    if (today === peak) read = `<span class="text-emerald-400 font-bold">Today is its peak stage.</span>`;
    else if (ta !== null) { const l = (pa - ta) * lppFor(race && race.distance, race); read = `Peaks ${lbl(peak)}; today (${lbl(today)}) it averages ${l.toFixed(1)}L below that.`; }
    else read = `Peaks ${lbl(peak)}; no runs yet at today's stage.`;
  }
  return `<div id="${id}"><div class="grid grid-cols-2 md:grid-cols-5 gap-2">${cells}</div>
    <div class="text-[11px] text-gray-300 mt-2">${read} <span class="text-gray-500">${full ? `From ${runs.length} runs in the database.` : 'From the runs on the card; full history loading…'}</span></div></div>`;
}
