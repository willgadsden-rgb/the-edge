// Blackbook writes (the site reads edge_blackbook directly with the public key).
//   POST /api/blackbook            {horse_name, note, added_by, source}  -> add or update
//   POST /api/blackbook?remove=1   {horse_name}                          -> remove
// Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (already set). BET_PIN optional, as for bets.
const json = (statusCode, body) => ({ statusCode, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }, body: JSON.stringify(body) });

exports.handler = async (event) => {
  const url = process.env.SUPABASE_URL, key = process.env.SUPABASE_SERVICE_ROLE_KEY, pin = process.env.BET_PIN;
  if (!url || !key) return json(500, { error: 'SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set in Netlify.' });
  if (event.httpMethod !== 'POST') return json(405, { error: 'POST only' });
  let b; try { b = JSON.parse(event.body || '{}'); } catch (e) { return json(400, { error: 'Bad JSON' }); }
  if (pin && String(b.pin || '') !== String(pin)) return json(401, { error: 'PIN required' });
  const name = String(b.horse_name || '').trim().slice(0, 80);
  if (!name) return json(400, { error: 'Need a horse name' });
  const remove = (event.queryStringParameters || {}).remove;
  const row = remove ? { horse_name: name, removed: 1 }
    : { horse_name: name, note: String(b.note || '').slice(0, 300) || null, added_by: String(b.added_by || '').slice(0, 40) || null,
        source: String(b.source || '').slice(0, 40) || null, created_at: new Date().toISOString(), removed: 0 };
  const r = await fetch(`${url}/rest/v1/edge_blackbook?on_conflict=horse_name`, {
    method: 'POST', body: JSON.stringify(row),
    headers: { apikey: key, Authorization: `Bearer ${key}`, 'Content-Type': 'application/json', Prefer: 'resolution=merge-duplicates,return=representation' } });
  return r.ok ? json(200, { ok: true }) : json(r.status, { error: await r.text() });
};
