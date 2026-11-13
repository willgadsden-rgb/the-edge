// Bet log writes (the site reads edge_bets directly with the public key).
//   POST /api/bets            {pin, bettor, race_id, horse_name, odds_taken, ...} -> logs a bet
//   POST /api/bets?void=ID    {pin}                                           -> voids a bet
// Stake rule: to win $100, capped at $75 (worked out here, not trusted from the browser).
// Env (Netlify > Site configuration > Environment variables):
//   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY   (already set)
//   BET_PIN   optional: if set, a PIN is required to log or void a bet (not set = one click)
const TARGET = 100, MAX_STAKE = 75;
// The REST base, whatever shape the env var is in: a trailing slash or an
// accidental /rest/v1 suffix both make PostgREST reject the path (PGRST125).
const PROJECT = 'https://xquwxvxdoaolggvilqkv.supabase.co';
function restBase(raw) {
  let u = String(raw || '').trim().replace(/\s+/g, '');
  if (!u) return PROJECT;
  if (!/^https?:\/\//.test(u)) u = 'https://' + u;
  try {
    const parsed = new URL(u);
    return parsed.origin;                         // drops any path, query or trailing slash
  } catch (e) {
    return PROJECT;
  }
}
const json = (statusCode, body) => ({ statusCode, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }, body: JSON.stringify(body) });

exports.handler = async (event) => {
  const url = restBase(process.env.SUPABASE_URL), key = process.env.SUPABASE_SERVICE_ROLE_KEY, pin = process.env.BET_PIN;
  if (!url || !key) return json(500, { error: 'SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set in Netlify.' });
  if (event.httpMethod !== 'POST') return json(405, { error: 'POST only' });
  let b; try { b = JSON.parse(event.body || '{}'); } catch (e) { return json(400, { error: 'Bad JSON' }); }
  if (pin && String(b.pin || '') !== String(pin)) return json(401, { error: 'PIN required' });
  const sb = (path, opts = {}) => fetch(`${url}/rest/v1/${path}`, { ...opts, headers: { apikey: key, Authorization: `Bearer ${key}`, 'Content-Type': 'application/json', Prefer: 'return=representation' } });
  const qs = event.queryStringParameters || {};
  if (qs.void) {
    const r = await sb(`edge_bets?id=eq.${encodeURIComponent(qs.void)}`, { method: 'PATCH', body: JSON.stringify({ void: 1 }) });
    return r.ok ? json(200, { ok: true }) : json(r.status, { error: await r.text() });
  }
  // A bet logged by mistake is removed outright - a void row in the ledger is
  // for a bet that was real, not for a wrong tap.
  if (qs.remove) {
    const r = await sb(`edge_bets?id=eq.${encodeURIComponent(qs.remove)}`, { method: 'DELETE' });
    if (!r.ok) return json(r.status, { error: await r.text() });
    const gone = await r.json().catch(() => []);
    return json(200, { ok: true, removed: Array.isArray(gone) ? gone.length : 1 });
  }
  const odds = Number(b.odds_taken);
  if (!b.horse_name || !b.race_id || !(odds > 1.01) || odds > 1001) return json(400, { error: 'Need a horse, a race and odds above $1.01' });
  const stake = Math.round(Math.min(TARGET / (odds - 1), MAX_STAKE) * 100) / 100;
  const row = {
    id: (globalThis.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(36).slice(2),
    created_at: new Date().toISOString(), bettor: String(b.bettor || '').slice(0, 40) || null,
    meeting_date: b.meeting_date || null, track: b.track || null, race_id: String(b.race_id), race_number: Number(b.race_number) || null,
    horse_name: String(b.horse_name).slice(0, 80), saddlecloth: Number(b.saddlecloth) || null,
    odds_taken: odds, stake, to_win: Math.round(stake * (odds - 1) * 100) / 100,
    fair_price: Number(b.fair_price) || null, edge_pct: Number.isFinite(Number(b.edge_pct)) ? Number(b.edge_pct) : null,
    bookmaker: String(b.bookmaker || '').slice(0, 40) || null, note: String(b.note || '').slice(0, 200) || null, void: 0,
  };
  const r = await sb('edge_bets', { method: 'POST', body: JSON.stringify(row) });
  return r.ok ? json(200, { ok: true, bet: row }) : json(r.status, { error: await r.text() });
};
