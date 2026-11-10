/* Ask The Edge: the syndicate's analyst, sitting on top of our own numbers.
 *
 * The browser builds a snapshot of what is on screen — our book, the plays and
 * fades, the map, the bias, the stars, the paper record — and sends it with the
 * question. The model is told it has nothing else to go on, so it can't invent
 * a runner or a price that isn't ours.
 */

const ASK = { busy: false, history: [], last: null };

const ASK_PROMPTS = [
  ['Bet of the day', 'What is the best bet on this card, and at what price does it stop being a bet? Give me the stake under our rule.'],
  ['Build me a quaddy', 'Build me a quaddy off the last four races for about $100. Give me the legs, the runners, the lines, the cost, our chance and the fair dividend.'],
  ['Best value here', 'Which runners on this card are the best value against the market, and which are the traps? Be blunt about which you would actually have.'],
  ['Read this race', 'Take the race I have open and give me the proper read: who maps where, what the tempo does, who the ratings favour, and who you would back.'],
  ['Worth following', 'Which horses on this card are worth following for next time, whether they win today or not?'],
  ['How are we going?', 'How is our model actually performing, judging by the paper record and the model report? Be honest about what is proven and what is not.'],
];

function askSnapshot() {
  const m = S.meeting || {};
  const trim = (v, d = 1) => (v === null || v === undefined || isNaN(v)) ? null : +Number(v).toFixed(d);
  // Full detail for the race on screen, the headline numbers for the rest: a
  // whole card of deep form would be mostly noise and would not fit.
  const races = (S.races || []).map(race => {
    const deep = S.view === race.race_id || S.races.length <= 3;
    const rows = (S.runners[race.race_id] || []).filter(r => !r.scratched && !r._scratched)
      .sort((a, b) => (b._p || 0) - (a._p || 0)).slice(0, deep ? 16 : 8);
    return {
      race: race.race_number, race_id: race.race_id, name: race.race_name, distance: race.distance,
      class: race.class_name, par: trim(race.form_par), jump: melbTime(race.jump_time),
      tempo: race.tempo, leaders: race.leaders, result_in: !!race.result_in,
      model: race.model_version, open_on_screen: S.view === race.race_id,
      runners: rows.map(r => ({
        no: r.saddlecloth, horse: r.horse_name, barrier: r.barrier, jockey: r.jockey, trainer: r.trainer,
        our_chance_pct: trim((r._p || 0) * 100), our_price: trim(r._fair, 2), market_price: trim(r._market, 2),
        min_price_we_want: trim(r._mao, 2), edge_pct: trim((r._edge || 0) * 100, 0),
        form_vs_par_lengths: trim(r.form_gap_l), ceiling_lengths: trim(r.ceiling_gap_l),
        form_confidence: r.form_confidence, prep: r.prep_stage, best_prep: r.best_stage,
        maps: r.map_zone, settle_rank: r.settle_rank,
        play: !!r.play_flag, play_why: r.play_reasons || undefined, fade: !!r._fade, value_flag: !!r._value,
        last_start_verdict: r.upgrade_note || undefined,
        jockey_win_pct: r.jockey_win_pct, trainer_win_pct: r.trainer_win_pct,
        class_move: r.class_move || undefined, first_starter: r.first_starter ? true : undefined,
        last_runs: deep ? (parseJSON(r.last_runs, []) || []).slice(0, 4).map(x => ({
          date: x.date, track: x.track, dist: x.dist, going: x.going, pos: x.pos, field: x.field,
          margin: trim(x.margin), rating: trim(x.rating), class: x.class,
          flags: (x.flags || []).map(f => f.text),
        })) : undefined,
        result: race.result_in ? { finish: r.finish_pos, margin: trim(r.margin), sp: trim(r.result_sp, 2), bsp: trim(r.result_bsp, 2), rating: trim(r.result_rating) } : undefined,
      })),
    };
  });
  const names = new Set([...(S.stars || []), ...(S.blackbook || [])].map(x => x.horse_name.toLowerCase()));
  const onCard = [];
  races.forEach(rc => rc.runners.forEach(r => { if (names.has(String(r.horse).toLowerCase())) onCard.push({ race: rc.race, horse: r.horse }); }));
  return {
    today: melbDate(), viewing_date: S.date,
    meeting: { track: m.track, going: m.going, rail: m.rail, state: m.state },
    prices_updated: S.liveAt || null,
    staking_rule: 'to win $100, stake = 100 / (price - 1), capped at $75',
    model_note: 'Prices come from our fitted model re-normalised to a 100% book. Fades are the part proven out of sample; overlays are not proven yet.',
    races,
    stars_or_blackbook_on_this_card: onCard,
    rising_stars: (S.stars || []).slice(0, 12).map(s => ({ horse: s.horse_name, starts: s.career_starts, wins: s.wins, last_vs_par_l: s.vs_par_l, why: s.reasons })),
    blackbook: (S.blackbook || []).map(b => b.horse_name),
    track_bias_panel: (document.getElementById('biasBoard') || {}).innerText || null,
    paper_record: (REC.data || []).length ? (() => {
      const g = REC.data.filter(b => b.done);
      const by = k => { const x = g.filter(b => b.kind === k); const w = x.filter(b => b.win).length;
        return { graded: x.length, winners: w, pl: +x.reduce((a, b) => a + b.pl, 0).toFixed(0) }; };
      return { play: by('play'), value: by('value'), top: by('top'), fade: by('fade') };
    })() : 'not loaded',
  };
}

function askRender() {
  const box = document.getElementById('askBody'); if (!box) return;
  const bubble = (m) => `<div class="${m.role === 'user' ? 'bg-[#0d1117] border-[#1e2638]' : 'bg-[#11151d] border-[#ff6600]/30'} border rounded-xl p-4">
      <div class="text-[10px] uppercase tracking-widest mb-1 ${m.role === 'user' ? 'text-gray-500' : 'text-[#ff6600]'}">${m.role === 'user' ? 'You' : 'The Edge'}</div>
      <div class="text-sm text-gray-200 leading-relaxed whitespace-pre-wrap">${askFormat(m.content)}</div></div>`;
  box.innerHTML = `
    <div class="flex flex-wrap gap-2 mb-4">${ASK_PROMPTS.map(([label, q]) =>
      `<button onclick='askSend(${jsq(q)})' class="rt-btn" style="font-size:11px;padding:6px 12px">${label}</button>`).join('')}
      ${ASK.history.length ? `<button onclick="ASK.history=[];askRender()" class="rt-btn" style="font-size:11px;padding:6px 12px">Clear</button>` : ''}</div>
    <div class="space-y-3 mb-4">${ASK.history.map(bubble).join('') || `<div class="text-sm text-gray-500">Ask anything about the meeting on screen — the card, a race, a horse, a quaddy, our record. It only sees our own numbers for the meeting you have loaded, so load the day you want to talk about first.</div>`}</div>
    ${ASK.busy ? '<div class="text-sm text-gray-400">Thinking…</div>' : `
    <div class="flex gap-2">
      <input id="askInput" class="syn-input flex-1 p-3 text-sm" placeholder="Ask about this card…" onkeydown="if(event.key==='Enter'){askSend(this.value)}">
      <button onclick="askSend(document.getElementById('askInput').value)" class="btn-orange px-5 py-2 rounded font-bold text-xs uppercase">Ask</button>
    </div>`}
    <p class="text-[10px] text-gray-500 mt-3">It answers from the snapshot on your screen and nothing else — no live market, no form guide, no current promotions. It will not promise you a winner, and neither will we.</p>`;
  const i = document.getElementById('askInput'); if (i && !ASK.busy) i.focus();
}
// Light formatting: bold, bullets and headings, nothing that can inject markup.
function askFormat(t) {
  return esc(t)
    .replace(/^### (.*)$/gm, '<b class="text-white">$1</b>')
    .replace(/^## (.*)$/gm, '<b class="text-white">$1</b>')
    .replace(/\*\*(.+?)\*\*/g, '<b class="text-white">$1</b>')
    .replace(/^[-*] /gm, '• ');
}

async function askSend(question) {
  question = String(question || '').trim();
  if (!question || ASK.busy) return;
  const el = document.getElementById('askInput'); if (el) el.value = '';
  ASK.history.push({ role: 'user', content: question });
  ASK.busy = true; askRender();
  try {
    const res = await fetch('/api/ask', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, context: JSON.stringify(askSnapshot()), history: ASK.history.slice(0, -1) }),
    });
    const body = await res.json();
    ASK.history.push({ role: 'assistant', content: res.ok ? body.answer : '⚠️ ' + (body.error || res.status) });
  } catch (e) {
    ASK.history.push({ role: 'assistant', content: '⚠️ Could not reach the assistant: ' + e.message });
  }
  ASK.busy = false; askRender();
}
