// Fresh prices for one meeting: GET /api/refresh-odds?meetingId=hamilton-20261109
// Costs 5 Form King credits per call (it pulls the meeting card). Returns
// { fetchedAt, races: { raceId: { horseName: { avgNow, bestNow, avgOpen,
//   firmOrDrift, scratched } } } } and writes nothing.
// Env: FORMKING_API_KEY (and optional FORMKING_BASE_URL).
const BASE = (process.env.FORMKING_BASE_URL || 'https://api.formking.com.au').replace(/\/+$/, '');

const json = (statusCode, body) => ({
  statusCode,
  headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  body: JSON.stringify(body),
});

exports.handler = async (event) => {
  const key = process.env.FORMKING_API_KEY;
  const meetingId = (event.queryStringParameters || {}).meetingId;
  if (!key) return json(500, { error: 'FORMKING_API_KEY is not set in Netlify.' });
  if (!meetingId || !/^[a-z0-9-]+$/i.test(meetingId)) return json(400, { error: 'meetingId required' });
  try {
    const res = await fetch(`${BASE}/b2c/meetings/${encodeURIComponent(meetingId)}`, {
      headers: { 'x-api-key': key, Accept: 'application/json' },
    });
    if (!res.ok) return json(res.status, { error: `Form King said ${res.status}` });
    const card = await res.json();
    const races = {};
    for (const race of card.races || []) {
      const rid = race.raceId || `${meetingId}_R${race.number}`;
      races[rid] = {};
      for (const e of race.entries || []) {
        const name = (e.horse || {}).name;
        if (!name) continue;
        const o = e.odds || {};
        races[rid][name] = {
          avgNow: o.avgNow ?? null, bestNow: o.bestNow ?? null, avgOpen: o.avgOpen ?? null,
          firmOrDrift: o.firmOrDrift ?? null, scratched: !!e.scratched,
        };
      }
    }
    return json(200, { fetchedAt: new Date().toISOString(), races });
  } catch (err) {
    return json(500, { error: err.message });
  }
};
