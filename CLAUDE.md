# The Edge — Quantitative Racing Intelligence

> Platform: **The Edge** (internal engine codename: PIE — Punting Intelligence Engine)

## Core Architecture
- Language: Python 3.11+
- Database: SQLite (file: `racing.db`)
- Mode: **STRICT LIVE-ONLY** (Form King, Victorian Pro tier). All mock/synthetic
  generators and fallbacks are removed — `formking_client.py` is the sole data
  source and **never fabricates runners**. Ingestion is resilient per meeting:
  if an individual meeting's live fetch fails (e.g. a Form King 500 or timeout)
  it is **skipped** and recorded in `formking_client.SKIPPED_MEETINGS`, the rest
  of the card still renders, and the app shows a non-fatal ⚠️ notice listing the
  skipped meetings. The hard `🔴 Live Form King Feed Error` is shown only when
  the whole feed is unavailable (the upcoming list fails, or zero meetings load).
  The API key is read from `.streamlit/secrets.toml` / Streamlit Cloud secrets
  only — never hard-coded or committed. Race timing uses
  `ZoneInfo('Australia/Melbourne')`.

- No fabricated inputs: nothing on the card may be generated from a horse's name,
  a hash or a random number. Missing data shows as "-" (system_audit enforces it).
- History database: `history_db.py` / `harvest.py`, Postgres schema `edge` in the
  Supabase VIC FORM project via `DATABASE_URL` (SQLite `history.db` fallback).

## Core Rules & Schema Standards
1. Database tables:
   - `meetings`: track_id, track_name, rail_position, condition, track_variant
   - `races`: race_id, meeting_id, race_number, distance, class_name, pace_pressure_index
   - `race_entries`: entry_id, race_id, horse_name, barrier, weight, prep_run_num, wfa_rating, speed_rating, score_0_to_100, fair_odds, market_odds
   - `horse_prep_profiles`: horse_name, prep_stage, starts, wins, avg_score
   - `bets_ledger`: bet_id, entry_id, taken_price, fair_price, bsp, clv_percent, profit_units
2. Math & Pricing Rules:
   - Model score is normalized to an absolute 0–100 scale (50 = Provincial BM64, 70 = Metro Saturday).
   - Market pricing must sum strictly to 100% fair probability (Sum(P_i) = 1.0; Fair Price = 1 / P_i).
   - Dynamic scratching re-normalization must be supported: P_new = P_old / (1 - Sum(P_scratched)).
3. Staking (Target-Profit model):
   - "To-Win $100" target-profit staking: Stake $ = 100 / (market_odds - 1.0).
   - Stakes, profit/loss and the P&L ledger are denominated in AUD **dollars** (not units).
     The `bets_ledger.profit_units` column holds dollar P&L; the operational `stake_dollars`
     column holds the dollar stake.
   - Minimum Acceptable Odds (MAO) gating still applies: MAO = fair_odds * (1 + min_edge).
