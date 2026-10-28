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
