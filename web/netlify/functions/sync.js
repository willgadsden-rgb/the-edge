// Sync: start the engine on GitHub (harvest Form King -> score -> publish to
// Supabase), or report how the latest run is going.
//   POST /api/sync?date=YYYY-MM-DD   -> starts the "Harvest Form King" workflow
//   GET  /api/sync                   -> status of the latest run
// Env (Netlify > Site configuration > Environment variables):
//   GITHUB_TOKEN  fine-grained token for willgadsden-rgb/the-edge with
//                 "Actions: Read and write" permission
//   GITHUB_REPO   optional, defaults to willgadsden-rgb/the-edge
const REPO = process.env.GITHUB_REPO || 'willgadsden-rgb/the-edge';
const WORKFLOW = 'harvest.yml';

const json = (statusCode, body) => ({
  statusCode,
  headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  body: JSON.stringify(body),
});

exports.handler = async (event) => {
  const token = process.env.GITHUB_TOKEN;
  if (!token) return json(500, { error: 'GITHUB_TOKEN is not set in Netlify.' });
  const gh = (path, opts = {}) => fetch(`https://api.github.com/repos/${REPO}${path}`, {
    ...opts,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'Content-Type': 'application/json',
    },
  });

  try {
    if (event.httpMethod === 'POST') {
      const date = (event.queryStringParameters || {}).date || '';
      if (date && !/^\d{4}-\d{2}-\d{2}$/.test(date)) return json(400, { error: 'date must be YYYY-MM-DD' });
      const res = await gh(`/actions/workflows/${WORKFLOW}/dispatches`, {
        method: 'POST',
        body: JSON.stringify({ ref: 'main', inputs: { date } }),
      });
      if (res.status !== 204) return json(res.status, { error: `GitHub said ${res.status}: ${await res.text()}` });
      return json(200, { started: true, date: date || 'today' });
    }
    const res = await gh(`/actions/workflows/${WORKFLOW}/runs?per_page=1`);
    if (!res.ok) return json(res.status, { error: `GitHub said ${res.status}` });
    const run = ((await res.json()).workflow_runs || [])[0];
    if (!run) return json(200, { status: 'none' });
    return json(200, {
      status: run.status, conclusion: run.conclusion, started: run.run_started_at,
      updated: run.updated_at, event: run.event, url: run.html_url,
    });
  } catch (err) {
    return json(500, { error: err.message });
  }
};
