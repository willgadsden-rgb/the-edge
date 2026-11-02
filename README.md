# The Edge — Quantitative Racing Intelligence

A Streamlit dashboard that rates every runner on an absolute 0–100 scale, prices
the field to a 100% fair book, flags value overlays, animates a tactical speed map
on each track's real shape, and reads how the track plays by rail and wind.

**Mock data only** — no real odds, bets, or outbound API calls. For research and
education; not financial advice.

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
- `system_audit.py` — 26 self-checks (`python system_audit.py`).
