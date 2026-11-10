// Blackbook writes (the site reads edge_blackbook directly with the public key).
//   POST /api/blackbook            {horse_name, note, added_by, source}  -> add or update
//   POST /api/blackbook?remove=1   {horse_name}                          -> remove
// Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (already set). BET_PIN optional, as for bets.
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
  // A trailing slash on SUPABASE_URL makes PostgREST reject the path (PGRST125).
  const url = restBase(process.env.SUPABASE_URL);
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY, pin = process.env.BET_PIN;
  if (!url || !key) return json(500, { error: 'SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set in Netlify.' });
  if (event.httpMethod !== 'POST') return json(405, { error: 'POST only' });
  let b; try { b = JSON.parse(event.body || '{}'); } catch (e) { return json(400, { error: 'Bad JSON' }); }
  if (pin && String(b.pin || '') !== String(pin)) return json(401, { error: 'PIN required' });
  const name = String(b.horse_name || '').trim().slice(0, 80);
  if (!name) return json(400, { error: 'Need a horse name' });
  const remove = !!(event.queryStringParameters || {}).remove;

  const head = extra => ({ apikey: key, Authorization: `Bearer ${key}`, 'Content-Type': 'application/json', ...extra });
  const eq = `horse_name=eq.${encodeURIComponent(name)}`;

  if (remove) {
    // Mark it removed; if it was never there, there is nothing to do.
    const r = await fetch(`${url}/rest/v1/edge_blackbook?${eq}`, {
      method: 'PATCH', body: JSON.stringify({ removed: 1 }), headers: head({ Prefer: 'return=representation' }) });
    if (!r.ok) return json(r.status, { error: `Supabase said: ${await r.text()}` });
    return json(200, { ok: true, removed: true });
  }

  const row = { horse_name: name, note: String(b.note || '').slice(0, 300) || null,
                added_by: String(b.added_by || '').slice(0, 40) || null,
                source: String(b.source || '').slice(0, 40) || null,
                created_at: new Date().toISOString(), removed: 0 };
  // Upsert, then fall back to update-then-insert if this PostgREST will not merge.
  let r = await fetch(`${url}/rest/v1/edge_blackbook`, {
    method: 'POST', body: JSON.stringify(row),
    headers: head({ Prefer: 'resolution=merge-duplicates,return=representation' }) });
  if (r.ok) return json(200, { ok: true });
  const first = await r.text();

  const patched = await fetch(`${url}/rest/v1/edge_blackbook?${eq}`, {
    method: 'PATCH', body: JSON.stringify(row), headers: head({ Prefer: 'return=representation' }) });
  if (patched.ok) {
    const rows = await patched.json().catch(() => []);
    if (rows && rows.length) return json(200, { ok: true });
  }
  r = await fetch(`${url}/rest/v1/edge_blackbook`, { method: 'POST', body: JSON.stringify(row), headers: head({ Prefer: 'return=representation' }) });
  if (r.ok) return json(200, { ok: true });
  return json(r.status, { error: `Supabase said: ${await r.text()} (first attempt: ${first}) [host ${url}]` });
};
