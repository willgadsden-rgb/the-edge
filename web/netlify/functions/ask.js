// The syndicate's form analyst: answers questions about the card in front of us.
//   POST /api/ask   {question, context, history} -> {answer}
// The browser assembles the context from what is already on screen (our book,
// plays, fades, bias, stars) and this function asks Claude about it. The model
// only ever sees what we send: it cannot look anything up, so it cannot invent
// a runner or a price that is not in our own data.
//
// Env (Netlify > Site configuration > Environment variables):
//   ANTHROPIC_API_KEY   required - get one at console.anthropic.com
//   EDGE_ASK_MODEL      optional - defaults to a current Claude model
const MODEL = process.env.EDGE_ASK_MODEL || 'claude-sonnet-4-5-20250929';
const MAX_CONTEXT = 120000;          // characters of card data, plenty for a full meeting
const json = (statusCode, body) => ({ statusCode, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }, body: JSON.stringify(body) });

const SYSTEM = `You are the form analyst for The Edge, a Victorian racing syndicate's own software. You are talking to the syndicate, not the public.

What you are given
- A JSON snapshot of the meeting currently open: our model's chance and fair price for every runner, the live market price, the edge, form figures in lengths against the class par, the speed map, our play and fade flags, last-start upgrades, track bias, rising stars and blackbook horses, and our paper-bet record.
- You have no other source. You cannot see a form guide, a live market, today's weather or any promotion. If something is not in the snapshot, say you do not have it rather than guessing.

How to answer
- Direct and concise, plain Australian racing English, no hedging padding. Lead with the answer.
- Always name a runner with its number and the race, and quote our price against the market price.
- Give your reasoning in a line or two: the numbers that drive it, not a lecture.
- When asked for a bet of the day, pick from runners in the snapshot and say what price it stops being a bet at (our minimum acceptable odds field) and the stake under the syndicate rule: to win $100, stake = 100 / (price - 1), capped at $75.
- For a quaddy or exotic, work from the chances in the snapshot, say how many lines and what it costs at the unit given, and what the fair dividend is (1 / combined chance). Point out that the pool has to beat that for the bet to be worth taking.
- Be honest about the model's standing: it beats the market on what to avoid more reliably than on what to back, and the paper record is the test, not proof. Never promise a winner, never call anything a lock, and never claim a system or an edge the data in the snapshot does not show.
- On bookmaker bonuses and promotions: you have no live offers. You can explain the kinds that are worth using and how they change a bet's value, but do not state that any particular offer exists right now.
- If the question is not about racing or this card, answer briefly and helpfully anyway.
- If someone sounds like they are chasing losses or betting more than they meant to, say so plainly once, and point to Gambler's Help on 1800 858 858.`;

exports.handler = async (event) => {
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) return json(503, { error: 'The assistant needs an Anthropic API key. In Netlify: Site configuration > Environment variables > add ANTHROPIC_API_KEY, then redeploy.' });
  if (event.httpMethod !== 'POST') return json(405, { error: 'POST only' });
  let b; try { b = JSON.parse(event.body || '{}'); } catch (e) { return json(400, { error: 'Bad JSON' }); }
  const question = String(b.question || '').slice(0, 4000).trim();
  if (!question) return json(400, { error: 'Ask something.' });
  const context = typeof b.context === 'string' ? b.context.slice(0, MAX_CONTEXT) : JSON.stringify(b.context || {}).slice(0, MAX_CONTEXT);
  const history = Array.isArray(b.history) ? b.history.slice(-8).filter(m => m && m.role && m.content)
    .map(m => ({ role: m.role === 'assistant' ? 'assistant' : 'user', content: String(m.content).slice(0, 6000) })) : [];

  const messages = history.concat([{
    role: 'user',
    content: `Here is the snapshot of what is on our screen right now:\n\n<card_data>\n${context}\n</card_data>\n\n${question}`,
  }]);

  try {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01' },
      body: JSON.stringify({ model: MODEL, max_tokens: 1600, system: SYSTEM, messages }),
    });
    const body = await res.json();
    if (!res.ok) return json(res.status, { error: (body.error && body.error.message) || 'The assistant could not be reached.' });
    const answer = (body.content || []).filter(p => p.type === 'text').map(p => p.text).join('\n').trim();
    return json(200, { answer: answer || 'No answer came back.', model: body.model, usage: body.usage });
  } catch (e) {
    return json(502, { error: 'The assistant could not be reached: ' + e.message });
  }
};
