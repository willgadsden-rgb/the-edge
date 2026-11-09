# The Edge — Quantitative Racing Intelligence

A Streamlit dashboard that rates every runner on an absolute 0–100 scale, prices
the field to a 100% fair book, flags value overlays, animates a tactical speed map
on each track's real shape, and reads how the track plays by rail and wind.

Runs on the live Form King feed only: every number on the card comes from Form King
(nothing is generated from a horse's name). For research; not financial advice.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

The SQLite database (`racing.db`) is generated automatically on first run, so you
don't need to seed anything.

## Live data (Phase 4 — Form King)

The app ships on **mock data** and makes no external calls by default. To run it on
the live Form King feed:

1. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` (gitignored)
   and fill in:
   ```toml
   DATA_SOURCE = "live"
   FORMKING_BASE_URL = "https://api.formking.com.au"
   FORMKING_API_KEY  = "your-secret-key"   # never commit this
   FORMKING_MAX_MEETINGS = 4               # caps credit spend per refresh
   ```
2. Rebuild the card from the sidebar (**Rebuild mock card & ledger**) or rerun
   `python ingest.py`. The current mode is shown in the **Settings** tab.

On **Streamlit Community Cloud**, don't upload `secrets.toml` — paste those keys in
*Manage app → Settings → Secrets*. Only `formking_client.py` touches Form King; the
rating model, pricing, staking and ledger all run unchanged off `racing.db`.

**Credits:** `/meetings/upcoming` is 1 credit; each meeting's full card is 5 credits,
so a refresh costs `1 + 5 × FORMKING_MAX_MEETINGS`. If a live fetch fails (no key,
network, API error) the app logs why and falls back to mock, so it never breaks.

## History database (v2)

`harvest.py` grows a history of every race run it can see. Each meeting card
(5 credits) carries every runner's last 12 runs, so one card adds ~1,000 runs.

- **Where it lives:** Supabase project **VIC FORM**, schema `edge` (the Syndicate OS
  tables in `public` are untouched). It was seeded with the 36,083 past runs the
  Syndicate OS app had already collected (Jan 2020 to Nov 2026).
- **Connect:** set `DATABASE_URL` (Supabase → Connect → Session pooler string) in
  `.streamlit/secrets.toml` or the environment. Without it the harvester writes to a
  local `history.db` (SQLite) instead.
- **Run it:** `python harvest.py` (today's meetings), `--date 2026-11-12`,
  `--file card.json` (no credits), `--dry-run` (list meetings and cost).
- **Automatic:** `.github/workflows/harvest.yml` runs it at ~9am and ~11pm Melbourne
  every day. Add repository secrets `FORMKING_API_KEY`, `FORMKING_BASE_URL` and
  `DATABASE_URL` for it to work.

Tables: `meetings`, `races`, `runs` (one row per horse per race, incl. prep stage,
stewards' comment, SP/BSP, settle/800/400 positions), `horses`, `entries` (today's
runners), `odds_snapshots` (price at every pull), `raw_payloads` (compressed cards,
kept 30 days).

## Deploy for free (so friends can view it)

This is a **Python/Streamlit server app**, so it needs a host that runs Python —
**Netlify and Vercel can't run it** (they're static/serverless only). Use one of:

- **Streamlit Community Cloud** (easiest, free): https://share.streamlit.io
  1. Push this repo to GitHub.
  2. Sign in to share.streamlit.io with GitHub.
  3. **New app** → choose this repo + branch, main file `app.py` → **Deploy**.
  4. Share the resulting `https://<your-app>.streamlit.app` link.
- Or: Render, Railway, Fly.io, or Hugging Face Spaces (Streamlit SDK).

## Project layout

- `app.py` — the dashboard UI (tabs, cards, speed map, settings).
- `rating_engine.py`, `pricing_engine.py`, `staking_engine.py` — model, 100% book, staking.
- `speedmap_engine.py`, `database.py` — tactical settling + per-track geometry.
- `track_play_engine.py`, `weather_engine.py`, `track_rail_profiles.py` — how the track plays.
- `career_profiles.py`, `angle_engine.py`, `prep_engine.py`, `custom_rules.py`, `copilot.py` — form, angles, rules, assistant.
- `history_db.py`, `harvest.py` — the history database and the Form King harvester.
- `field_check.py` — pull one card and list every field the feed carries.
- `system_audit.py` — self-checks (`python system_audit.py`), incl. a no-fabrication check.

## Website (Netlify)

`web/` is the syndicate's website: the original Syndicate design, now reading the
engine's scores and prices from Supabase (`public.edge_meetings`, `edge_races`,
`edge_runners`, read-only to the public key). `harvest.py` publishes them after
every pull (`publish.py`), with no extra Form King credits.

- **Sync Data** starts the GitHub harvest via `web/netlify/functions/sync.js`
  (needs `GITHUB_TOKEN` in Netlify: a fine-grained token on this repo with
  Actions: Read and write).
- **Refresh prices / Auto prices** pull one meeting's odds via
  `web/netlify/functions/refresh-odds.js` (5 credits each; needs `FORMKING_API_KEY`)
  and re-price in the browser with the same blend as `pricing_engine.py`.
- Deploy: link this repo in Netlify with **base directory `web`**.
