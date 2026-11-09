"""The Edge — Quantitative Racing Intelligence (Streamlit + Plotly dashboard).

Tabs:
    1. Race Cards & Overlays   - cards, projected vs par, situational angles,
                                 manual adjustments, live market, AI co-pilot
    2. Realistic Speed Map     - true track geometry
    3. Suggested Bets & Tracker - qualified suggestions + settled audit ledger
    4. AI Database Assistant    - natural-language -> read-only SQL

Mock data only (see CLAUDE.md). Launch with:  streamlit run app.py
"""

import contextlib
import datetime
import io
import json
import math
from zoneinfo import ZoneInfo

# All race timing is anchored to the Australian racing clock.
MELBOURNE = ZoneInfo("Australia/Melbourne")

# Visible build marker so the running commit can be confirmed at a glance (no
# API credits needed). Bump this string whenever we need to verify a deploy.
BUILD_TAG = "build-15"

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import formking_client
import ingest
import run_model
import ledger_tracker
import career_profiles
import live_market_engine as lme
import angle_engine
import copilot
import triggers_engine
import speedmap_engine
import custom_rules
import intraday_engine
import weather_engine
import track_rail_profiles
import track_play_engine
import exotics_engine
import silks_engine
import sync_formking
from database import get_connection, geometry_for, par_for, init_db, ensure_schema
from pricing_engine import (fair_book_from_scores, effective_odds, commission_for_state,
                            calculate_blended_fair_prices)

# Bayesian market shrinkage: how much to anchor the model book to the live
# de-vigged market (0 = pure model, 1 = pure market). 0.70 kills phantom overlays.
DEFAULT_MARKET_WEIGHT = 0.70
from staking_engine import (calculate_stake, calculate_mao, is_void, TARGET_PROFIT,
                            STAKE_CONSUMER, STAKE_SYNDICATE, DEFAULT_BANKROLL)
from rating_engine import (calculate_0_to_100_score,
                           trajectory_trend, calculate_projected_score, classify_trajectory,
                           clamp_modifier)
from prep_engine import profile_runner

OVERLAY_EDGE = 0.20
SUGGEST_EDGE = 0.15
SUGGEST_PAR_WINDOW = 1.5
SUGGEST_ODDS_MIN, SUGGEST_ODDS_MAX = 2.20, 18.00
SUGGEST_TREND_MIN = -1.0
DEMO_SEED = 24
BRAND = "The Edge"
TAGLINE = "Quantitative Racing Intelligence"

BIAS_OPTIONS = ["Fair Track", "Leader Advantage", "Swooper / Outside Advantage"]
BIAS_MAP = {
    "Fair Track": angle_engine.TRACK_BIAS_FAIR,
    "Leader Advantage": angle_engine.TRACK_BIAS_LEADER,
    "Swooper / Outside Advantage": angle_engine.TRACK_BIAS_SWOOPER,
}

st.set_page_config(page_title="The Edge — Racing Intelligence", page_icon="🏇", layout="wide")

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@500;700&display=swap');
      :root{
        --bg:#0f1115; --surf:#171a21; --surf2:#1e222c; --line:#2a2f3b;
        --txt:#e8eaf0; --dim:#8b93a3; --faint:#5f6676;
        --orange:#ff6a1a; --orange-2:#ff8a3d; --orange-soft:rgba(255,106,26,.13);
        --orange-line:rgba(255,106,26,.42); --red:#ef5350; --red-soft:rgba(239,83,80,.13);
        --red-line:rgba(239,83,80,.42); --blue:#9ec7ff;
        --mono:'JetBrains Mono',ui-monospace,monospace; --disp:'Space Grotesk',Inter,sans-serif;
      }
      html, body, .stApp, [class*="css"] { font-family:'Inter',system-ui,sans-serif; }
      .stApp { background:
        radial-gradient(1100px 480px at 88% -8%, rgba(255,106,26,.08), transparent 60%),
        var(--bg); }
      .block-container { padding-top:3.2rem; max-width:1520px; }

      /* ---- Masthead ---- */
      .pie-title { font-family:var(--disp); font-size:1.72rem; font-weight:700; margin:0; color:var(--txt);
                   letter-spacing:.01em; display:flex; align-items:center; gap:11px; }
      .pie-title::before{ content:""; width:6px; height:30px; border-radius:3px;
                   background:linear-gradient(180deg,var(--orange),var(--orange-2)); box-shadow:0 0 16px var(--orange-line); }
      .pie-tag { font-family:var(--mono); color:var(--orange-2); font-size:.72rem; margin:.3rem 0 .8rem 17px;
                 font-weight:600; letter-spacing:.24em; text-transform:uppercase; }

      /* ---- Condition strip ---- */
      .cond-strip { display:flex; flex-wrap:wrap; gap:7px; margin:4px 0 12px; align-items:center; }
      .cond-chip { background:var(--surf2); color:var(--dim); padding:4px 11px; border-radius:8px;
                   font-size:.78rem; font-weight:600; border:1px solid var(--line); }
      .cond-chip b{ color:var(--txt); }
      .cond-ppi  { background:var(--orange); color:#140a03; border-color:var(--orange); font-weight:800; }
      .cond-par  { background:var(--orange-soft); color:var(--orange-2); border-color:var(--orange-line); font-weight:700; }
      .pace-chip { color:#ffb37a; } .wind-chip { color:var(--blue); }

      /* ---- Runner card head ---- */
      .rc-name { font-family:var(--disp); font-size:1.14rem; font-weight:700; color:var(--txt); }
      .rc-cloth{ display:inline-flex; width:27px; height:27px; border-radius:7px; vertical-align:middle;
                 background:linear-gradient(180deg,var(--orange),var(--orange-2)); color:#140a03;
                 align-items:center; justify-content:center; font-weight:800; font-size:.85rem; margin-right:7px;
                 box-shadow:0 0 11px var(--orange-line); }
      .silk { width:42px; height:42px; vertical-align:middle; margin-right:9px;
              border:1px solid var(--line); border-radius:9px; background:var(--surf2); }
      .rc-sub  { color:var(--dim); font-size:.84rem; margin-top:3px; }
      .rc-proj { font-family:var(--mono); font-size:.86rem; font-weight:700; margin-top:4px; }
      .proj-up { color:var(--orange-2); } .proj-dn { color:var(--red); }
      .rc-prep { display:inline-block; margin-top:7px; padding:3px 9px; border-radius:7px; background:var(--surf2);
                 color:var(--dim); border:1px solid var(--line); font-size:.72rem; font-weight:700; letter-spacing:.02em; }
      .rc-peak { background:var(--orange-soft); color:var(--orange-2); border-color:var(--orange-line); }
      .rc-taper{ background:var(--red-soft); color:#ff9a8f; border-color:var(--red-line); }

      /* ---- Signal chips: orange = positive, red = negative, grey = neutral ---- */
      .ang-row { display:flex; flex-wrap:wrap; gap:5px; margin:7px 0 2px; }
      .ang { font-size:.71rem; font-weight:700; padding:3px 9px; border-radius:7px;
             background:var(--surf2); color:var(--dim); border:1px solid var(--line); }
      .ang-pos, .cust, .env-pos { background:var(--orange-soft); color:var(--orange-2); border-color:var(--orange-line); }
      .ang-neg, .cust-neg, .env-neg { background:var(--red-soft); color:#ff9a8f; border-color:var(--red-line); }
      /* #3 native-trigger chips */
      .trig { font-size:.71rem; font-weight:700; padding:3px 9px; border-radius:7px; border:1px solid var(--line); }
      .trig-steam { background:var(--red-soft); color:#ff9a8f; border-color:var(--red-line); }
      .trig-claim { background:var(--surf2); color:var(--txt); }
      .prior-chip { background:var(--orange-soft); color:var(--orange-2); border-color:var(--orange-line); font-weight:700; }
      .intraday-banner { background:var(--orange-soft); color:var(--orange-2); border:1px solid var(--orange-line);
                         font-weight:700; padding:9px 13px; border-radius:10px; margin:7px 0; font-size:.88rem; }
      .tac { font-size:.77rem; color:var(--dim); margin-top:5px; }
      .tac b { color:var(--txt); }
      .tac-tax { color:var(--red); font-weight:700; } .tac-box { color:var(--orange-2); font-weight:700; }
      .ruleitem { font-size:.85rem; color:var(--dim); }

      /* ---- Guide & legend ---- */
      .leg-row { display:flex; gap:14px; align-items:center; padding:9px 0; border-bottom:1px solid var(--line); }
      .leg-badge { min-width:180px; max-width:180px; display:flex; align-items:center; gap:4px; flex-wrap:wrap; }
      .leg-text { font-size:.9rem; color:var(--dim); line-height:1.45; }
      .leg-text b { color:var(--txt); }
      .guide-hero { background:linear-gradient(120deg,#15171d 0%,#1b1e26 52%,rgba(255,106,26,.24) 150%);
                    border:1px solid var(--line); color:var(--txt); border-radius:16px; padding:20px 22px; margin:4px 0 16px;
                    position:relative; overflow:hidden; }
      .guide-hero::after{ content:""; position:absolute; right:-44px; top:-44px; width:190px; height:190px;
                    border-radius:50%; background:radial-gradient(circle,var(--orange-soft),transparent 70%); }
      .guide-hero h2 { font-family:var(--disp); margin:0 0 6px; font-size:1.45rem; }
      .guide-step { background:var(--surf); border:1px solid var(--line); border-left:3px solid var(--orange);
                    border-radius:10px; padding:11px 15px; margin:7px 0; color:var(--dim); }
      .guide-step b { color:var(--txt); }
      .guide-note { background:var(--orange-soft); border:1px solid var(--orange-line); border-radius:12px;
                    padding:13px 15px; color:var(--orange-2); font-size:.9rem; }
      .tip-bar { background:var(--surf); border:1px solid var(--line); border-left:3px solid var(--orange);
                 border-radius:10px; padding:9px 14px; color:var(--dim); font-size:.88rem; margin:2px 0 10px; }
      .tip-bar b { color:var(--txt); }

      /* ---- Home-screen meeting cards ---- */
      .meet-card { padding:2px 2px 4px; }
      .meet-track { font-family:var(--disp); font-size:1.2rem; font-weight:700; color:var(--txt); }
      .meet-meta { font-family:var(--mono); color:var(--orange-2); font-size:.76rem; letter-spacing:.04em;
                   margin:3px 0 9px; }
      .meet-chips { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:9px; }
      .meet-head { font-family:var(--disp); color:var(--dim); font-size:.95rem; margin:2px 0 10px; }
      .meet-head b { color:var(--txt); }
      .play-row { color:var(--dim); font-size:.86rem; margin:4px 0; line-height:1.45; }
      .play-row b { color:var(--txt); }

      /* ---- Signals & Tools side box ---- */
      .side-hdr { font-family:var(--disp); font-size:.92rem; font-weight:700; color:var(--txt);
                  margin:0 0 6px; }
      .side-overlay { background:var(--orange-soft); border:1px solid var(--orange-line); border-radius:9px;
                      padding:8px 11px; color:var(--orange-2); font-size:.82rem; line-height:1.5; margin-bottom:6px; }
      .side-overlay b { color:var(--orange); }

      /* ---- Horizontal speed strip ---- */
      .strip-wrap { display:flex; background:linear-gradient(180deg,#14161c,#0c0e13); border:1px solid var(--line);
                    border-radius:14px; padding:10px 6px 6px; gap:0; }
      .strip-col { flex:1; position:relative; height:330px; border-right:1px dashed rgba(255,255,255,.07); }
      .strip-col:last-child { border-right:none; }
      .runner-strip { position:absolute; left:5px; right:5px; height:52px;
                      background:linear-gradient(180deg,var(--surf2),var(--surf)); border:1px solid var(--line);
                      border-left:4px solid var(--orange); border-radius:8px;
                      display:flex; align-items:center; gap:6px; padding:3px 6px; box-shadow:0 2px 7px rgba(0,0,0,.45); }
      .runner-strip img { width:30px; height:30px; border:1px solid var(--line); border-radius:6px; background:var(--surf2); }
      .rs-num { font-family:var(--disp); font-weight:800; color:var(--orange-2); font-size:.9rem; }
      .rs-name { font-weight:700; color:var(--txt); font-size:.72rem; line-height:1.05; }
      .rs-mps { color:var(--dim); font-size:.64rem; font-weight:600; }
      .strip-axis { display:flex; margin-top:6px; }
      .strip-axis div { flex:1; text-align:center; font-family:var(--mono); font-weight:700; font-size:.68rem; color:var(--dim);
                        background:var(--surf); padding:6px 2px; border-right:1px solid var(--line); }
      .strip-axis div:first-child { border-radius:7px 0 0 7px; } .strip-axis div:last-child { border-radius:0 7px 7px 0; border-right:none; }

      /* ---- Price tiles & edge ---- */
      .price-wrap { display:flex; gap:9px; justify-content:flex-end; align-items:flex-start; }
      .tile { border-radius:12px; padding:8px 13px; text-align:center; min-width:98px; border:1px solid var(--line); }
      .tile .lbl { font-family:var(--mono); font-size:.57rem; letter-spacing:.12em; opacity:.9; font-weight:600; }
      .tile .val { font-family:var(--disp); font-size:1.22rem; font-weight:700; line-height:1.15; margin-top:1px; }
      .tile-mine { background:linear-gradient(180deg,rgba(255,106,26,.2),rgba(255,106,26,.06)); color:var(--orange-2);
                   border-color:var(--orange-line); box-shadow:0 0 20px rgba(255,106,26,.11) inset; }
      .tile-mkt { background:var(--surf2); color:var(--txt); }
      .edge-badge{ display:block; margin-top:6px; text-align:center; font-family:var(--mono); font-size:.67rem;
                   font-weight:700; padding:4px 7px; border-radius:7px; letter-spacing:.03em; }
      .edge-pos { background:var(--orange); color:#140a03; box-shadow:0 0 15px var(--orange-line); }
      .edge-neg { background:var(--surf2); color:var(--dim); border:1px solid var(--line); }
      .edge-gone{ background:var(--red-soft); color:#ff9a8f; border:1px solid var(--red-line); }
      .fluc-line { text-align:right; font-size:.76rem; color:var(--dim); margin-top:6px; font-family:var(--mono); }
      .senti { font-size:.7rem; font-weight:700; padding:2px 8px; border-radius:10px; margin-left:5px; border:1px solid var(--line); }
      .senti-steamer { background:var(--orange-soft); color:var(--orange-2); border-color:var(--orange-line); }
      .senti-drifter { background:var(--surf2); color:var(--blue); } .senti-stable { background:var(--surf2); color:var(--dim); }

      /* ---- Form boxes ---- */
      .form-row { display:flex; gap:5px; align-items:center; margin:9px 0 2px; }
      .form-lab { color:var(--dim); font-size:.72rem; margin-right:4px; font-weight:600; }
      .form-hdr { font-family:var(--mono); color:var(--dim); font-size:.67rem; font-weight:600; margin:9px 0 0;
                  letter-spacing:.08em; text-transform:uppercase; }
      .form-l { width:42px; display:inline-block; text-align:center; font-size:.56rem; color:var(--faint); font-weight:600; }
      .form-box { width:42px; height:46px; border-radius:7px; display:flex; flex-direction:column; align-items:center;
                  justify-content:center; font-family:var(--disp); font-weight:700; }
      .fb-rt { font-size:.86rem; font-weight:700; line-height:1; }
      .fb-pos { font-size:.52rem; font-weight:700; line-height:1; margin-top:3px; padding:1px 3px; border-radius:3px;
                background:rgba(0,0,0,.4); color:#fff; }
      .fp-win { color:#ffd766; } .fp-plc { color:#e8eaf0; } .fp-out { color:#cbd5e1; opacity:.9; }
      .fb-hi { background:linear-gradient(180deg,#1faa5e,#148048); color:#eafff3; border:1px solid rgba(34,197,94,.45); }
      .fb-mid { background:rgba(245,158,11,.16); color:#fbbf24; border:1px solid rgba(245,158,11,.4); }
      .fb-lo { background:rgba(239,83,80,.16); color:#ff9a8f; border:1px solid var(--red-line); }
      .form-note { font-size:.7rem; color:var(--dim); margin:5px 0 2px; line-height:1.35; }
      .form-note b { color:var(--txt); }
      .trend-up { color:#34d27f; font-weight:700; margin-left:5px; }
      .trend-dn { color:var(--red); font-weight:700; margin-left:5px; }
      .trend-fl { color:var(--dim); font-weight:700; margin-left:5px; }

      /* ---- Exec strip & drawer ---- */
      .exec-strip { display:flex; flex-wrap:wrap; gap:18px; margin-top:9px; padding-top:8px;
                    border-top:1px solid var(--line); font-size:.85rem; color:var(--dim); }
      .exec-strip b { color:var(--orange-2); }
      .scr-flag { color:var(--red); font-weight:700; letter-spacing:.04em; }
      .bio-grid { display:flex; flex-wrap:wrap; gap:6px 18px; font-size:.85rem; color:var(--dim); margin:2px 0 8px; }
      .bio-grid b { color:var(--txt); }
      .pedi { font-size:.82rem; color:var(--dim); margin:2px 0 6px; line-height:1.55; }
      .pedi b { color:var(--txt); }
      .grid-hdr { font-family:var(--mono); font-size:.64rem; font-weight:600; color:var(--faint);
                  letter-spacing:.1em; margin:9px 0 4px; text-transform:uppercase; }
      .chip-grid { display:flex; flex-wrap:wrap; gap:6px; margin:2px 0 6px; }
      .rec-chip { border:1px solid var(--line); background:var(--surf2); border-radius:8px; padding:3px 9px; font-size:.72rem; }
      .rec-chip .rl { color:var(--orange-2); font-weight:700; margin-right:5px; }
      .rec-chip .rv { color:var(--txt); font-weight:600; }
      .rec-chip.hot { background:var(--orange); border-color:var(--orange); }
      .rec-chip.hot .rl, .rec-chip.hot .rv { color:#140a03; }
      .fact-chip { background:var(--surf2); color:var(--txt); border:1px solid var(--line); border-radius:8px;
                   padding:4px 11px; font-size:.72rem; font-weight:600; }
      .fact-chip.alt { background:var(--orange-soft); color:var(--orange-2); border-color:var(--orange-line); }
      .fact-chip .fl { color:var(--dim); margin-right:5px; font-weight:500; }
      .hot-badge { display:inline-block; background:var(--orange); color:#140a03; font-weight:800; font-size:.8rem;
                   padding:4px 11px; border-radius:8px; margin:4px 0; }
      .dist-hi { display:inline-block; background:var(--orange-soft); color:var(--orange-2); border:1px solid var(--orange-line);
                 font-weight:700; padding:4px 11px; border-radius:8px; }

      /* ---- Streamlit chrome: cards, tabs, buttons ---- */
      [data-testid="stVerticalBlockBorderWrapper"]:has(> div > div > [data-testid="stVerticalBlock"]) { }
      div[data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"] {
        border-radius:14px; }
      .stTabs [data-baseweb="tab-list"] { gap:2px; border-bottom:1px solid var(--line); }
      .stTabs [data-baseweb="tab"] { font-weight:600; color:var(--dim); padding:7px 15px; }
      .stTabs [aria-selected="true"] { color:var(--orange-2) !important; }
      .stTabs [data-baseweb="tab-highlight"] { background:var(--orange) !important; }
      .stButton>button { border-radius:9px; border:1px solid var(--line); background:var(--surf2);
                         color:var(--txt); font-weight:600; transition:all .12s ease; }
      .stButton>button:hover { border-color:var(--orange-line); color:var(--orange-2); }
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------------------------------------------------------
# Data preparation
# -----------------------------------------------------------------------------
def _has_data():
    try:
        conn = get_connection()
        try:
            races = conn.execute("SELECT COUNT(*) FROM races").fetchone()[0]
            scored = conn.execute(
                "SELECT COUNT(*) FROM race_entries WHERE score_0_to_100 IS NOT NULL").fetchone()[0]
            bets = conn.execute("SELECT COUNT(*) FROM bets_ledger").fetchone()[0]
            return races > 0 and scored > 0 and bets > 0
        finally:
            conn.close()
    except Exception:
        return False


def rebuild_data():
    """Rebuild the card from the live Form King feed. Raises on a feed failure
    (callers surface st.error). No simulated bets or results are seeded — the
    user ledger starts empty and settles only from live results."""
    with contextlib.redirect_stdout(io.StringIO()):
        ingest.main()           # strict live-only; raises on a feed error
        run_model.main()        # score + 100% fair pricing
        ledger_tracker.log_recommended_bets()  # model value picks (no fake $/results)
    conn = get_connection()
    try:
        lme.seed_if_empty(conn)
        silks_engine.assign_saddlecloths_and_silks(conn)
        # Pull any real results that have landed in the feed for races run today
        # (from pastEvents), then settle pending bets + CLV from them. No-ops when
        # nothing has run yet — strict live-only, never fabricated.
        try:
            sync_formking.ingest_live_results(conn)
            sync_formking.settle_pending_bets(conn)
        except Exception:
            pass
    finally:
        conn.close()


def build_env(meeting, race, entries, commission_rate, stake_mode, bankroll, apply_intraday):
    """Assemble the meeting-level environment context for scoring a race."""
    wind = weather_engine.classify_wind(
        weather_engine.wind_for(meeting["track_name"], meeting["meeting_date"]),
        meeting["track_name"])
    tier, tier_badge = race_tempo(entries, race)
    gutter = False
    intraday = {"gutter_detected": False}
    if apply_intraday:
        conn = get_connection()
        try:
            intraday = intraday_engine.analyze_intraday(conn, meeting["meeting_id"], race["race_number"])
        finally:
            conn.close()
        gutter = intraday["gutter_detected"]
    return {"wind": wind, "tempo_tier": tier, "tempo_badge": tier_badge,
            "gutter": gutter, "intraday": intraday, "commission_rate": commission_rate,
            "stake_mode": stake_mode, "bankroll": bankroll}


def race_tempo(entries, race):
    tm = speedmap_engine.build_tactical_map(entries)["runners"]
    n_leaders = sum(1 for v in tm.values() if v["is_leader_group"])
    return speedmap_engine.classify_tempo(n_leaders, race["pace_pressure_index"])


def ensure_data(force=False):
    if force or not _has_data():
        try:
            rebuild_data()
        except Exception as exc:
            # Strict live-only: no mock fallback. Surface the feed error and halt
            # rather than render fabricated runners.
            formking_client.LAST_FETCH_ERROR = str(exc)
            st.error("🔴 Live Form King Feed Error: {}".format(exc))
            st.caption("The dashboard runs strictly on live Form King data — no mock fallback. "
                       "Check the API key and credits in Settings → Secrets, then Rebuild.")
            st.stop()
    conn = get_connection()
    try:
        lme.seed_if_empty(conn)
    finally:
        conn.close()


def load_meeting():
    conn = get_connection()
    try:
        meeting = conn.execute("SELECT * FROM meetings ORDER BY meeting_id LIMIT 1").fetchone()
        races = conn.execute(
            "SELECT * FROM races WHERE meeting_id = ? ORDER BY race_number",
            (meeting["meeting_id"],)).fetchall()
        return meeting, races
    finally:
        conn.close()


def load_meetings():
    """All meetings for the home-screen list, each with a race_count."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT m.*, (SELECT COUNT(*) FROM races r WHERE r.meeting_id = m.meeting_id) AS race_count "
            "FROM meetings m ORDER BY m.meeting_id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def load_races(meeting_id):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM races WHERE meeting_id = ? ORDER BY race_number",
            (meeting_id,)).fetchall()
    finally:
        conn.close()


def load_entries(race_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT e.*, COALESCE(p.prep_stage, '') AS prep_stage
            FROM race_entries e
            LEFT JOIN horse_prep_profiles p ON p.horse_name = e.horse_name
            WHERE e.race_id = ? ORDER BY e.fair_odds
            """, (race_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def scratched_for(race_id, entries):
    return [e["horse_name"] for e in entries
            if st.session_state.get("scr_{}_{}".format(race_id, e["entry_id"]), False)]


# -----------------------------------------------------------------------------
# Interactive syndicate bet ledger (user_bets)
# -----------------------------------------------------------------------------
def log_user_bet(bet):
    """Insert one operator bet into user_bets (status PENDING)."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO user_bets
                 (meeting_id, race_id, track_name, race_number, runner_id, horse_name,
                  saddlecloth, bet_mode, target_win, stake, odds_taken, fair_odds, edge_at_bet)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(bet["meeting_id"]), str(bet["race_id"]), bet["track_name"], bet["race_number"],
             str(bet["runner_id"]), bet["horse_name"], bet["saddlecloth"], bet["bet_mode"],
             bet["target_win"], bet["stake"], bet["odds_taken"], bet["fair_odds"], bet["edge_at_bet"]))
        conn.commit()
    finally:
        conn.close()


def load_user_bets():
    conn = get_connection()
    try:
        return [dict(x) for x in conn.execute(
            "SELECT * FROM user_bets ORDER BY placed_at DESC, bet_id DESC").fetchall()]
    finally:
        conn.close()


def cancel_user_bet(bet_id):
    """Remove a still-pending bet (settled bets are immutable)."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM user_bets WHERE bet_id=? AND status='PENDING'", (bet_id,))
        conn.commit()
    finally:
        conn.close()


def ledger_metrics(bets):
    """Active outlay, settled P&L, ROI% and strike rate for the bet ledger."""
    pending = [b for b in bets if b["status"] == "PENDING"]
    settled = [b for b in bets if b["status"] in ("WON", "LOST")]
    active_outlay = sum((b["stake"] or 0.0) for b in pending)
    settled_pnl = sum((b["net_pnl"] or 0.0) for b in settled)
    settled_outlay = sum((b["stake"] or 0.0) for b in settled)
    roi = (settled_pnl / settled_outlay * 100.0) if settled_outlay else 0.0
    won = [b for b in settled if b["status"] == "WON"]
    strike = (len(won) / len(settled) * 100.0) if settled else 0.0
    return {"active_outlay": active_outlay, "settled_pnl": settled_pnl, "roi": roi,
            "strike": strike, "n_settled": len(settled), "n_pending": len(pending)}


def race_markets(race_id):
    conn = get_connection()
    try:
        return lme.summaries_for_race(conn, race_id)
    finally:
        conn.close()


def _rowget(row, key, default=None):
    """Read a column from a sqlite3.Row that may predate a migration (returns
    default instead of raising when the column isn't present)."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def evaluate_race(entries, scratched_names, race, meeting, markets, track_bias,
                  rule_mgr=None, env=None):
    """Full per-runner evaluation: situational angles, tactical settling, custom
    rules AND environment modifiers (intraday drift, wind, pace tempo) feed the
    projected score; fair prices come from a softmax over active projected scores
    (always re-normalised to 100%). Value edge & MAO use net-of-commission odds."""
    env = env or {}
    rate = env.get("commission_rate", 0.08)
    stake_mode = env.get("stake_mode", STAKE_CONSUMER)
    bankroll = env.get("bankroll", DEFAULT_BANKROLL)
    gutter = env.get("gutter", False)
    wind = env.get("wind")
    tempo_tier = env.get("tempo_tier")

    scratched = set(scratched_names)
    par = par_for(race["class_name"])
    cond = (meeting["condition"] or "Good").split()[0]
    settling = angle_engine.settling_positions(entries)
    geom = geometry_for(meeting["track_name"], race["distance"])
    tmap = speedmap_engine.build_tactical_map(entries, geom)["runners"]

    # Race-level pace read (#3): each runner's recent speed figure from its last-5
    # track speeds, then lone-leader / pace-duel signals across the field.
    def _runs(e):
        try:
            return json.loads(e["last5_json"] or "[]")
        except Exception:
            return []
    speed_by_name = {e["horse_name"]: triggers_engine.speed_figure(_runs(e)) for e in entries}
    pace_sig = triggers_engine.pace_signals(speed_by_name)

    computed = {}
    for e in entries:
        # Last 5 ACTUAL runs from Form King (barrier trials excluded at ingestion);
        # feed the real past ratings/positions into the 3-layer rating engine so
        # the displayed score matches the form shown on the card.
        real_runs = _runs(e)
        # Every past run on file (up to 12) and the real runner profile.
        try:
            all_runs = json.loads(_rowget(e, "runs_json") or "[]") or real_runs
        except Exception:
            all_runs = real_runs
        try:
            fk = json.loads(_rowget(e, "fk_json") or "{}")
        except Exception:
            fk = {}
        # Apprentice claim (#3): a claim lightens the carried weight, worth
        # +0.38 pts/kg through the base rating (never clamped as a situational).
        claim = _rowget(e, "apprentice_claim") or 0.0
        eff_weight = max(float(e["weight"]) - float(claim), 40.0)
        base = calculate_0_to_100_score(
            e["wfa_rating"], eff_weight, race["distance"], race["class_name"],
            last_ratings=[rr.get("rating") for rr in real_runs],   # newest first
            barrier=e["barrier"],
            last_positions=[rr.get("pos") for rr in real_runs])
        prep = profile_runner(e["horse_name"], e["prep_run_num"], base, all_runs)
        pos = settling.get(e["horse_name"], 99)
        angles = angle_engine.calculate_angles(e, race, meeting, pos, track_bias)
        ap = angle_engine.angle_points(angles)
        tac = tmap.get(e["horse_name"], {})
        rctx = {"name": e["horse_name"], "lane": tac.get("lane"), "barrier": e["barrier"],
                "settle_zone": tac.get("zone"), "tactical_tag": tac.get("tag"),
                "weight": e["weight"], "prep_stage": e.get("prep_stage", ""),
                "prep_run_num": e["prep_run_num"]}
        custom_pts, custom_badges = (rule_mgr.evaluate_runner_rules(rctx, race["race_id"])
                                     if rule_mgr else (0.0, []))

        # Environment modifiers (intraday drift, wind, pace tempo).
        env_pts, env_badges = 0.0, []
        ip, ib = intraday_engine.intraday_modifier(tac.get("lane"), gutter)
        if ib:
            env_pts += ip; env_badges.append(ib)
        if wind:
            wp, wb = weather_engine.wind_modifier(wind, rctx)
            if wb:
                env_pts += wp; env_badges.append(wb)
        if tempo_tier:
            tp, tb = speedmap_engine.tempo_modifier(tempo_tier, tac.get("zone"))
            if tb:
                env_pts += tp; env_badges.append(tb)

        # --- #3 Form King native triggers -------------------------------------
        triggers = []
        # Apprentice claim: weight relief is already in `base`; show the chip.
        _cb = triggers_engine.apprentice_badge(claim)
        if _cb:
            triggers.append(_cb)
        # Late steam plunge from the price flucs (market info, no score change).
        try:
            _flucs = json.loads(_rowget(e, "flucs_json") or "null")
        except Exception:
            _flucs = None
        _steam = triggers_engine.steam_signal(_flucs, _rowget(e, "firm_or_drift"))
        if _steam["is_steaming"]:
            _pct = "" if _steam["pct"] is None else " ({:+.0f}%)".format(_steam["pct"] * 100)
            triggers.append({"label": "🚨 SMART MONEY / STEAM{}".format(_pct), "cls": "steam"})
        # Pace: uncontested leader (+) or pace duel (-), from the race-level read.
        _pp, _pn = pace_sig.get(e["horse_name"], (0.0, None))
        if _pn:
            env_pts += _pp
            env_badges.append({"name": _pn, "points": _pp})
        # Proven wet-tracker on a Soft/Heavy day, from the horse's own wet form.
        _wp, _wn = triggers_engine.wet_form_signal(real_runs, cond)
        if _wn:
            env_pts += _wp
            env_badges.append({"name": _wn, "points": _wp})
        # Pre-race historical prior (#1): small barrier nudge from how this track
        # plays on today's going. The header chip explains it; fold it in quietly.
        _bp = 0.0
        if hasattr(track_rail_profiles, "barrier_prior_adjustment"):
            try:
                _bp = track_rail_profiles.barrier_prior_adjustment(e["barrier"], env.get("hist_bias"))
            except Exception:
                _bp = 0.0
        if _bp:
            env_pts += _bp
            env_badges.append({"name": "Track Prior (barrier)", "points": _bp})

        manual = float(st.session_state.get("adj_{}_{}".format(race["race_id"], e["entry_id"]), 0.0) or 0.0)
        # Situational modifiers (angles + bias + tempo + wind + intraday) are hard-capped
        # to +/-2.5; deliberate custom-rule biases and the manual override are not.
        projected = calculate_projected_score(
            e["horse_name"], base, e["prep_run_num"], cond, race["distance"],
            situational_points=ap + env_pts, manual_override_points=manual,
            unclamped_points=custom_pts, prep_adjustment=prep["prep_adjustment"])
        # The form pills and trend come from the real runs parsed above; a
        # debutant (0 starts) has none.
        is_debut = (e.get("career_starts") == 0)
        # Ratings oldest -> newest for the pills/trend (real_runs is newest first).
        traj = [rr["rating"] for rr in reversed(real_runs) if rr.get("rating") is not None]
        hist = angle_engine.real_history(e, race["distance"])
        computed[e["entry_id"]] = dict(
            base=base, pos=pos, angles=angles, ap=ap,
            custom_badges=custom_badges, env_badges=env_badges, triggers=triggers,
            manual=manual, projected=projected, traj=traj, is_debut=is_debut,
            real_runs=real_runs, runs_all=all_runs, fk=fk, prep_tag=prep["tag"],
            trend=(0.0 if (is_debut or not traj) else trajectory_trend(traj)), tactical=tac,
            form_delta=round(prep["prep_adjustment"], 1),
            # Condition / distance suitability are not added to the score until
            # they are fitted against results; the real records show in DETAILS.
            cond_delta=0.0,
            dist_delta=0.0,
            angles_clamped=clamp_modifier(ap + env_pts),
            dls=hist["days_since"], prep_run=e["prep_run_num"])

    # Market-anchored (Bayesian-shrunk) book: blend the model with the de-vigged
    # live market so prices are grounded in consensus and phantom overlays shrink.
    market_weight = float(st.session_state.get("market_weight", DEFAULT_MARKET_WEIGHT))
    blend_runners = []
    for e in entries:
        if e["horse_name"] in scratched:
            continue
        summ = markets.get(e["entry_id"])
        live = summ["current"] if summ else e["market_odds"]
        blend_runners.append({
            "id": e["entry_id"],
            "score": computed[e["entry_id"]]["projected"],
            "market_odds": live,
            "effective_odds": effective_odds(live, rate) if live else None,
        })
    book = calculate_blended_fair_prices(blend_runners, market_weight=market_weight)

    rows = []
    for e in entries:
        c = computed[e["entry_id"]]
        is_scr = e["horse_name"] in scratched
        tac = c["tactical"]
        common = {**e, "base": c["base"], "settling": c["pos"], "angles": c["angles"],
                  "angle_points": c["ap"], "custom_badges": c["custom_badges"],
                  "env_badges": c["env_badges"], "triggers": c["triggers"],
                  "manual": c["manual"], "projected": c["projected"],
                  "par": par, "par_delta": round(c["projected"] - par, 1), "cond": cond,
                  "traj": c["traj"], "trend": c["trend"], "is_debut": c["is_debut"],
                  "real_runs": c["real_runs"], "runs_all": c["runs_all"], "fk": c["fk"],
                  "prep_tag": c["prep_tag"],
                  "lane": tac.get("lane"), "lane_name": tac.get("lane_name", "-"),
                  "settle_zone": tac.get("zone", "-"),
                  "tactical_tag": tac.get("tag", "-"), "tactical_blurb": tac.get("tag_blurb", "-"),
                  "early_speed": tac.get("early_speed"), "es_live": tac.get("es_live", False),
                  "form_delta": c["form_delta"], "cond_delta": c["cond_delta"],
                  "dist_delta": c["dist_delta"], "angles_clamped": c["angles_clamped"],
                  "dls": c["dls"], "prep_run": c["prep_run"]}
        if is_scr or e["entry_id"] not in book or book[e["entry_id"]]["my_price"] is None:
            rows.append({**common, "disp_fair": None, "market": None, "opening": None,
                         "edge": None, "overlay": False, "value_gone": False, "stake_dollars": 0.0,
                         "mao": None, "fluc_string": None, "sentiment": None,
                         "sentiment_label": None, "scratched": is_scr})
            continue
        fair = book[e["entry_id"]]["my_price"]          # market-anchored "my price"
        model_prob = book[e["entry_id"]]["p_blended"]   # blended prob for Kelly staking
        summ = markets.get(e["entry_id"])
        live = summ["current"] if summ else e["market_odds"]
        opening = summ["opening"] if summ else e["market_odds"]
        # Judge value on net-of-commission effective odds to kill false overlays.
        live_eff = effective_odds(live, rate)
        edge = live_eff / fair - 1.0
        void = is_void(live_eff, fair)
        stake = calculate_stake(live_eff, stake_mode, model_prob=model_prob, bankroll=bankroll)
        overlay = edge >= OVERLAY_EDGE and stake["bet"] and not void
        value_gone = (effective_odds(opening, rate) / fair - 1.0 >= OVERLAY_EDGE) and void
        rows.append({**common, "disp_fair": fair, "market": live, "opening": opening,
                     "market_eff": live_eff, "edge": edge, "overlay": overlay,
                     "value_gone": value_gone, "stake_dollars": stake["dollars"],
                     "stake_mode": stake.get("mode"), "mao": calculate_mao(fair),
                     "fluc_string": summ["fluc_string"] if summ else None,
                     "sentiment": summ["sentiment"] if summ else None,
                     "sentiment_label": summ["sentiment_label"] if summ else None,
                     "scratched": False})
    rows.sort(key=lambda r: (r["scratched"], r["disp_fair"] if r["disp_fair"] else 9e9))
    return rows


def is_suggested(r):
    return (not r["scratched"] and r["disp_fair"] is not None
            and r["edge"] >= SUGGEST_EDGE and r["market"] >= r["mao"]
            and abs(r["par_delta"]) <= SUGGEST_PAR_WINDOW
            and SUGGEST_ODDS_MIN <= r["market"] <= SUGGEST_ODDS_MAX
            and r["trend"] > SUGGEST_TREND_MIN)


def saddlecloths(entries):
    ordered = sorted(entries, key=lambda e: (-e["weight"], e["horse_name"]))
    return {e["horse_name"]: i for i, e in enumerate(ordered, start=1)}


def current_bias():
    return BIAS_MAP[st.session_state.get("bias_pill", BIAS_OPTIONS[0]) or BIAS_OPTIONS[0]]


def rule_manager():
    if "rule_mgr" not in st.session_state:
        st.session_state["rule_mgr"] = custom_rules.RuleManager()
    return st.session_state["rule_mgr"]


# -----------------------------------------------------------------------------
# Tab 2 helpers: expanded realistic speed map
# -----------------------------------------------------------------------------
def _early_speed(entry):
    """Early speed on the map's 30-95 scale from REAL in-run positions
    (0-10 figure x 6.5 + 30); a runner with no in-run data sits at neutral."""
    es10 = angle_engine.early_speed_of(entry)
    return 30.0 + 6.5 * (es10 if es10 is not None else 5.0)


LANE_W = 46.0          # vertical separation between lanes
MAX_LANES = 6          # lanes fan out to 6 wide off the corner
W_OUT = MAX_LANES * LANE_W
LEAD_SPACING = 46.0    # longitudinal separation between running pods
SETTLE_DIST = 400.0    # metres over which the field settles after the jump
FAN_DIST = 220.0       # metres over which the field fans out as it straightens
MIN_SEP = 50.0         # anti-collision: minimum distance between any two tokens


def track_xy(s, w, geom):
    """Full 3-stage track path (back straight -> bend -> home straight)."""
    return speedmap_engine.track_point(s, w, geom)


def _smooth(f):
    return f * f * (3 - 2 * f)


def _abbrev(name):
    parts = name.split()
    if len(parts) == 1:
        return parts[0][:8]
    return "{}.{}".format(parts[0][0], parts[-1])[:10]


def _leg(rows):
    """Render a list of (badge_html, name, meaning) as legend rows."""
    html = ""
    for badge, name, meaning in rows:
        html += ('<div class="leg-row"><div class="leg-badge">{b}</div>'
                 '<div class="leg-text"><b>{n}</b> — {m}</div></div>'.format(b=badge, n=name, m=meaning))
    st.markdown(html, unsafe_allow_html=True)


def render_guide():
    """Plain-English guide + a complete legend of every icon, colour and badge."""
    st.markdown(
        '<div class="guide-hero"><h2>👋 Welcome to The Edge</h2>'
        'The Edge rates every horse, works out what its price <i>should</i> be, and tells you when '
        'the market is paying more than it should — a <b>value bet</b>. You do not need to understand '
        'racing to use it. Here is everything, in plain English.</div>', unsafe_allow_html=True)

    st.markdown("### How it works, in 3 steps")
    st.markdown(
        '<div class="guide-step"><b>1. We price the horse.</b> Every runner gets a rating, which becomes '
        'our fair price — the <b>MY PRICE</b> tile. Think of it as "what the odds really should be".</div>'
        '<div class="guide-step"><b>2. We compare to the market.</b> We put our price next to the '
        '<b>LIVE MARKET</b> price. If the market is longer (bigger odds) than ours, that is value.</div>'
        '<div class="guide-step"><b>3. We tell you what to do.</b> Value bets get a green '
        '🔥 <b>+EV OVERLAY</b> badge, the lowest price still worth taking (<b>MAO</b>), and how much to '
        'stake. If a green badge shows, it is a bet; if not, leave it alone.</div>', unsafe_allow_html=True)

    st.markdown('<div class="guide-note">🟢 <b>Just want the bets?</b> On the <b>Suggested Bets</b> tab, '
                'the top section lists every qualifying value bet for the day with the horse, the stake, '
                'and the price to take. That is all a casual punter needs.</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### The key — what every icon means")

    st.markdown("#### 💲 Prices & value (the most important part)")
    _leg([
        ('<span class="tile tile-mine" style="min-width:70px"><span class="val" style="font-size:.95rem">MY PRICE</span></span>',
         "My Price", "<b>Our</b> fair price for the horse — what the odds should be if the market were perfect."),
        ('<span class="tile tile-mkt" style="min-width:70px"><span class="val" style="font-size:.95rem">LIVE MARKET</span></span>',
         "Live Market", "The price the betting market is offering <b>right now</b>."),
        ('<span class="edge-badge edge-pos" style="display:inline-block">🔥 +35% EV OVERLAY</span>',
         "Value overlay (green)", "The market is paying well more than fair — <b>this is a bet</b>. The % is how much value."),
        ('<span class="edge-badge edge-neg" style="display:inline-block">UNDERLAY -12%</span>',
         "Underlay (grey)", "The market is too short — <b>no value, leave it</b>."),
        ('<span class="edge-badge edge-gone" style="display:inline-block">🛑 VOID / VALUE GONE</span>',
         "Value gone (red)", "The price has shortened past the point of being worth it — <b>stand down</b>."),
        ('<span class="cond-chip cond-par">🎯 Par: 74</span>',
         "Par Score to Win", "The rating a horse usually needs to <b>win this grade</b> of race."),
        ('🛑 MAO', "Minimum Acceptable Odds", "The <b>shortest price still worth taking</b>. Never bet below it."),
        ('💵 Stake', "Recommended stake", "How much to bet (sized to win a set target, or by bankroll if in Syndicate mode)."),
    ])

    st.markdown("#### 📈 Market moves (is money coming for it?)")
    _leg([
        ('<span class="senti senti-steamer">🔥 STEAMER</span>', "Steamer", "Price is <b>firming</b> (shortening) — the horse is being backed."),
        ('<span class="senti senti-drifter">❄️ DRIFTER</span>', "Drifter", "Price is <b>drifting</b> (getting bigger) — support is weakening."),
        ('<span class="senti senti-stable">• STABLE</span>', "Stable", "Little price movement since the market opened."),
        ('<span style="font-family:monospace">$4.80 ➔ $4.20 ➔ $3.60</span>', "Fluctuation trail", "The price history from the open to now (left = oldest)."),
    ])

    st.markdown("#### ⭐ Rating & recent form")
    _leg([
        ('<span class="rc-proj proj-up">Projected 76.5 (+2.5)</span>', "Projected (vs Par)", "Our final rating for today, and how far above (+) or below (−) the winning par it sits."),
        ('<span class="form-box fb-hi">78</span> <span class="form-box fb-mid">63</span> <span class="form-box fb-lo">41</span>',
         "Last-5 form boxes", "Recent ratings, <b>newest on the left</b>. Green = strong (70+), slate = fair, dark = weak."),
        ('<span class="trend-up">▲ RISING</span> <span class="trend-fl">• STABLE</span> <span class="trend-dn">▼ EASING</span>',
         "Form trajectory", "Is the horse <b>improving</b> (green), holding its level (stable), or <b>falling off</b> (red)?"),
    ])

    st.markdown("#### 🏇 Campaign stage (fitness)")
    _leg([
        ('<span class="rc-prep rc-peak">3RD UP 🎯 TARGET PEAK</span>', "Target peak", "At the <b>planned best run</b> of its campaign — expected to be at its fittest."),
        ('<span class="rc-prep">1ST UP · CONDITIONING</span>', "Conditioning", "Still building fitness — <b>may need the run</b>."),
        ('<span class="rc-prep rc-taper">5TH+ UP · TAPERING</span>', "Tapering", "Past its peak this campaign — fitness may be fading."),
    ])

    st.markdown("#### 🎯 Angles & adjustments (why we like/dislike a horse)")
    _leg([
        ('<span class="ang ang-pos">🟢 Distance Conditioner (+2.0)</span>', "Green angle", "A situational pattern <b>in the horse's favour</b> (adds points)."),
        ('<span class="ang ang-neg">🔴 Heavy Hangover (-1.5)</span>', "Red angle", "A situational pattern <b>against</b> the horse (subtracts points)."),
        ('<span class="ang cust">🟣 Lanes 4-7 Bias (+2.5)</span>', "Purple (custom rule)", "A bias <b>you created yourself</b> in plain English via the co-pilot."),
        ('<span class="ang env-pos">⚡ Tailwind Propulsion (+1.5)</span>', "Cyan (conditions)", "An automatic edge from pace, wind, track bias or an intraday track pattern."),
    ])

    st.markdown("#### 🛣️ Speed map & tactics (how the race will be run)")
    _leg([
        ('<span style="color:#2E86DE;font-size:1.3rem">●</span>', "Blue dot / border", "A runner settling normally — the border colour is its silk colour."),
        ('<span style="color:#f1b000;font-size:1.3rem">●</span>', "Gold glow", "This runner is a current <b>value overlay</b>."),
        ('<span style="color:#e03131;font-size:1.3rem">●</span>', "Red glow", "<b>Contested speed</b> — too many leaders forcing a fast, risky early pace."),
        ('Rail / One-Off / 3-Wide', "Lanes", "How far off the inside rail a horse settles (Rail = best, saving ground)."),
        ('🔒 Pocketed', "Pocketed / Held Up", "Stuck behind others on the fence — needs luck for a run."),
        ('⚠️ Bend Entry · 🏁 Straightening', "Track markers", "Where the home turn begins and where the field straightens for home."),
        ('17.3 m/s', "Early speed", "How quickly a horse begins — higher means more likely to lead or press."),
    ])

    st.markdown("#### 📊 Betting & results terms")
    _leg([
        ('CLV %', "Closing Line Value", "Did the price you took <b>beat the final market price</b>? The #1 sign of long-term skill."),
        ('BSP', "Betfair Starting Price", "The market's <b>closing</b> price, used to measure CLV."),
        ('ROI %', "Return on investment", "Profit as a percentage of everything staked."),
        ('🩹 Scratch', "Scratch toggle", "Mark a non-runner; the market instantly re-prices without it."),
        ('🎲 Exotic fair dividends', "Exotics", "Fair Exacta/Trifecta dividends from the model (first 2 or 3 past the post)."),
    ])

    st.markdown("#### 📋 Form-guide chips (in the DETAILS drawer)")
    _leg([
        ('<span class="rec-chip"><span class="rl">Good</span><span class="rv">8: 1-0-0</span></span>',
         "Record chips", "Record under a filter, shown as <b>Starts: Wins-2nds-3rds</b>. Today's relevant filters are highlighted blue."),
        ('<span class="fact-chip"><span class="fl">DLS</span>13d</span> <span class="fact-chip alt"><span class="fl">ROI</span>+12%</span>',
         "Fact chips", "<b>DLS</b> days since last run · <b>DLW</b> days since last win · <b>DOD</b> depth of grade · <b>ROI</b> betting return."),
        ('Car · 12m · Crs · Dist · FU · 2U · 3U', "Filter codes", "Career · last 12 months · this course · this distance · 1st-up · 2nd-up · 3rd-up."),
    ])

    st.markdown("#### 🧭 Across the top (race conditions)")
    _leg([
        ('<span class="cond-chip pace-chip">💣 SUICIDAL SPEED DUEL</span>', "Pace tempo", "The projected speed of the race: 🐢 Slow · ⚖️ Genuine · 🔥 Fast · 💣 Suicidal."),
        ('<span class="cond-chip wind-chip">🧭 Wind N · Headwind 18 km/h</span>', "Wind", "Wind direction and strength down the straight (helps or hurts certain runners)."),
        ('<span class="intraday-banner" style="display:inline-block">⚡ Intraday Surface Drift</span>',
         "Intraday drift", "A track pattern detected from earlier races today (e.g. wide runners doing well)."),
    ])

    st.caption("All data comes from the live Form King feed. "
               "The icons and rules above are exactly what you'll see throughout the app.")


_ZONE_ORDER = [speedmap_engine.ZONE_LEADER, speedmap_engine.ZONE_BOXSEAT,
               speedmap_engine.ZONE_HANDY, speedmap_engine.ZONE_MIDFIELD,
               speedmap_engine.ZONE_WORSE, speedmap_engine.ZONE_BACK]
_AXIS_TAGS = ["LEADER", "PACE", "OFF PACE", "MIDFIELD", "OFF MIDFIELD", "BACKMARKER"]


def render_speed_strip(entries, tmap, cloth):
    """Horizontal lane speed strip (classic AU format): zone left->right, lane bottom->top."""
    field = [e for e in entries if not e.get("scratched")]
    cols = {i: [] for i in range(6)}
    for e in field:
        t = tmap.get(e["horse_name"], {})
        zone = t.get("zone", speedmap_engine.ZONE_MIDFIELD)
        col = _ZONE_ORDER.index(zone) if zone in _ZONE_ORDER else 3
        cols[col].append((e, t))

    col_html = ""
    for ci in range(6):
        runners = sorted(cols[ci], key=lambda x: -(x[1].get("lane", 2)))  # lane4 top first
        lane_stack = {}
        strips = ""
        for e, t in runners:
            lane = min(4, max(1, t.get("lane", 2)))
            es10 = t.get("early_speed", 5.0) or 5.0
            mps = round(15.3 + es10 * 0.28, 1)
            k = lane
            lane_stack[k] = lane_stack.get(k, 0) + 1
            top = 6 + (4 - lane) * 74 + (lane_stack[k] - 1) * 10
            strips += (
                '<div class="runner-strip" style="top:{top}px;border-left-color:{col}">'
                '<img src="{silk}"/><span class="rs-num">{num}</span>'
                '<div><div class="rs-name">{name}</div>'
                '<div class="rs-mps">{mps} m/s</div></div></div>'.format(
                    top=top, col=silks_engine.primary_color(e["horse_name"]),
                    silk=silks_engine.silk_data_uri(e["horse_name"], 30),
                    num=cloth[e["horse_name"]], name=e["horse_name"].upper(), mps=mps))
        col_html += '<div class="strip-col">{}</div>'.format(strips)

    axis = "".join('<div>{}</div>'.format(t) for t in _AXIS_TAGS)
    st.markdown('<div class="strip-wrap">' + col_html + '</div>'
                '<div class="strip-axis">' + axis + '</div>', unsafe_allow_html=True)
    st.caption("Horizontal position = settling zone (Leader → Backmarker); vertical = lane "
               "(Rail at the bottom → Wide at the top). Figure shown is projected early speed (m/s).")


def _xesc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_speedmap_svg(entries, cloth, geom, tmap):
    """Racing.com-style settling map drawn on the real track shape (with the bend for
    turning courses): each runner is its jockey silk + saddlecloth number + horse name,
    laid out front-to-back by running position and across the track by lane."""
    field = [e for e in entries if not e.get("scratched")]
    n = max(1, len(field))
    is_turn = (geom.get("turn_direction", "straight") != "straight"
               and geom.get("run_to_turn_m") and geom.get("turn_radius"))
    shown = geom.get("shown_m", 600)
    straighten = geom.get("straighten_m", shown * 0.85)

    order = sorted(field, key=lambda e: tmap.get(e["horse_name"], {}).get("rank", 99))
    d_lead = (straighten + 95.0) if is_turn else shown * 0.82
    spread = min(540.0, d_lead - 50.0)
    gap = spread / max(1, n - 1)

    placed = []
    for i, e in enumerate(order):
        t = tmap.get(e["horse_name"], {})
        lane = min(MAX_LANES, max(1, int(t.get("lane", 2))))
        d = max(35.0, d_lead - i * gap)
        w = (lane - 1) * LANE_W
        x, y = track_xy(d, w, geom)
        placed.append({"e": e, "x": x, "y": -y, "d": d, "lane": lane, "t": t})

    d0 = min(p["d"] for p in placed) - 55
    d1 = max(p["d"] for p in placed) + 70
    samples = [d0 + (d1 - d0) * k / 60.0 for k in range(61)]
    rail = [(xx, -yy) for xx, yy in (track_xy(s, 0.0, geom) for s in samples)]
    outer = [(xx, -yy) for xx, yy in (track_xy(s, W_OUT, geom) for s in samples)]

    S = 46.0
    allx = [p["x"] for p in placed] + [p[0] for p in rail + outer]
    ally = [p["y"] for p in placed] + [p[1] for p in rail + outer]
    padx, padyt, padyb = S * 1.8, S * 1.9, S * 1.9
    minx, maxx = min(allx) - padx, max(allx) + padx
    miny, maxy = min(ally) - padyt, max(ally) + padyb
    vb_w, vb_h = maxx - minx, maxy - miny

    def pts(ps):
        return " ".join("{:.1f},{:.1f}".format(a, b) for a, b in ps)

    out = ['<svg viewBox="{:.1f} {:.1f} {:.1f} {:.1f}" width="100%" '
           'style="max-height:600px;background:#0c0e13;border-radius:12px" '
           'xmlns="http://www.w3.org/2000/svg">'.format(minx, miny, vb_w, vb_h)]
    out.append('<path d="M {} L {} Z" fill="#171a21" stroke="rgba(255,255,255,0.14)" '
               'stroke-width="2"/>'.format(pts(rail), pts(list(reversed(outer)))))
    for ln in range(1, MAX_LANES):
        lp = [(xx, -yy) for xx, yy in (track_xy(s, ln * LANE_W, geom) for s in samples)]
        out.append('<polyline points="{}" fill="none" stroke="rgba(255,255,255,0.06)" '
                   'stroke-width="1" stroke-dasharray="5 7"/>'.format(pts(lp)))
    out.append('<polyline points="{}" fill="none" stroke="#ff6a1a" stroke-width="4"/>'.format(pts(rail)))
    # winning-post flag near the leader
    lead = placed[0]
    out.append('<text x="{:.1f}" y="{:.1f}" fill="#ff8a3d" font-size="{:.1f}" font-weight="700" '
               'font-family="monospace" text-anchor="middle">🏁 WIN POST</text>'.format(
                   lead["x"], lead["y"] - S * 1.05, S * 0.42))

    for idx, p in enumerate(placed):
        e = p["e"]
        name = e["horse_name"]
        x, y = p["x"], p["y"]
        half = S / 2.0
        edge = (e["market_odds"] / e["fair_odds"] - 1.0) if e.get("fair_odds") else 0.0
        if edge >= OVERLAY_EDGE:
            out.append('<circle cx="{:.1f}" cy="{:.1f}" r="{:.1f}" fill="none" stroke="#ff6a1a" '
                       'stroke-width="3"/>'.format(x, y, half + 6))
        out.append('<rect x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}" rx="6" '
                   'fill="#1e222c" stroke="rgba(255,255,255,0.25)" stroke-width="1"/>'.format(
                       x - half, y - half, S, S))
        out.append('<image href="{}" x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}"/>'.format(
            silks_engine.silk_data_uri(name, 64), x - half, y - half, S, S))
        bq = S * 0.33
        bx, by = x + half - bq * 0.5, y + half - bq * 0.5
        out.append('<circle cx="{:.1f}" cy="{:.1f}" r="{:.1f}" fill="#0b1f2a" stroke="#ff8a3d" '
                   'stroke-width="2"/>'.format(bx, by, bq))
        out.append('<text x="{:.1f}" y="{:.1f}" fill="#fff" font-size="{:.1f}" font-weight="800" '
                   'text-anchor="middle" dominant-baseline="central">{}</text>'.format(
                       bx, by, bq * 1.15, cloth[name]))
        fs = S * 0.38
        above = (idx % 2 == 1)
        ny = (y - half - S * 0.42) if above else (y + half + S * 0.52)
        nw = max(len(name) * fs * 0.56, S)
        out.append('<rect x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}" rx="4" '
                   'fill="rgba(12,14,19,0.82)"/>'.format(x - nw / 2.0, ny - fs * 0.78, nw, fs * 1.55))
        out.append('<text x="{:.1f}" y="{:.1f}" fill="#e8eaf0" font-size="{:.1f}" font-weight="600" '
                   'text-anchor="middle" dominant-baseline="central" font-family="Inter,sans-serif">{}</text>'.format(
                       x, ny, fs, _xesc(name)))

    out.append('</svg>')
    return "".join(out)


def build_horizontal_speedmap(entries, cloth, tmap, frame_ms=300):
    """Animated horizontal settling map: watch the field sort from the jump into
    its running order — zones Leader→Backmarker (x), lanes Rail→Wide (y)."""
    field = [e for e in entries if not e.get("scratched")]
    n = max(1, len(field))
    ZN, MAXLANE = 6, 5

    bucket, runners, leaders = {}, [], set()
    for e in field:
        t = tmap.get(e["horse_name"], {})
        zone = t.get("zone", speedmap_engine.ZONE_MIDFIELD)
        zi = _ZONE_ORDER.index(zone) if zone in _ZONE_ORDER else 3
        lane = min(MAXLANE, max(1, int(t.get("lane", 2))))
        es10 = t.get("early_speed", 5.0) or 5.0
        if es10 >= 7.0 and zi <= 1:
            leaders.add(e["horse_name"])
        key = (zi, lane)
        k = bucket.get(key, 0)
        bucket[key] = k + 1
        edge = (e["market_odds"] / e["fair_odds"] - 1.0) if e.get("fair_odds") else 0.0
        runners.append({
            "xs": zi + k * 0.30, "ys": lane + k * 0.16,
            "xj": -2.0, "yj": 1.0 + (e["barrier"] - 1) / max(1, n - 1) * (MAXLANE - 0.3),
            "num": str(cloth[e["horse_name"]]), "name": _abbrev(e["horse_name"]),
            "color": silks_engine.primary_color(e["horse_name"]), "overlay": edge >= OVERLAY_EDGE,
            "hover": "<b>{} (#{})</b><br>{}<br>Bar {} · {}<br>ES {:.1f}/10".format(
                e["horse_name"], cloth[e["horse_name"]], silks_engine.jockey_for(e["horse_name"]),
                e["barrier"], t.get("lane_name", "-"), es10),
        })
    duel = len(leaders) >= 3
    ring = [r["color"] for r in runners]
    glow = ["rgba(255,106,26,0.45)" if r["overlay"] else "rgba(0,0,0,0)" for r in runners]
    nums = [r["num"] for r in runners]
    labels = [r["name"] for r in runners]
    hovers = [r["hover"] for r in runners]

    def pos(r, p):
        pe = _smooth(p)
        return r["xj"] + (r["xs"] - r["xj"]) * pe, r["yj"] + (r["ys"] - r["yj"]) * pe

    static = []
    for ln in range(1, MAXLANE + 1):
        static.append(go.Scatter(x=[-2.6, ZN + 0.3], y=[ln, ln], mode="lines",
                      line=dict(color="rgba(255,255,255,0.06)", width=1),
                      hoverinfo="skip", showlegend=False))
    static.append(go.Scatter(x=[-2.0, -2.0], y=[0.3, MAXLANE + 0.7], mode="lines",
                  line=dict(color="rgba(255,106,26,0.5)", width=2, dash="dot"),
                  hoverinfo="skip", showlegend=False))

    def frame_traces(p):
        xs = [pos(r, p)[0] for r in runners]
        ys = [pos(r, p)[1] for r in runners]
        g = go.Scatter(x=xs, y=ys, mode="markers",
                       marker=dict(size=40, color=glow, line=dict(width=0)),
                       hoverinfo="skip", showlegend=False)
        m = go.Scatter(x=xs, y=ys, mode="markers+text",
                       marker=dict(size=26, color="#0b1f2a", line=dict(width=4, color=ring)),
                       text=nums, textposition="middle center",
                       textfont=dict(color="white", size=12, family="Arial Black"),
                       hovertext=hovers, hoverinfo="text", showlegend=False)
        lb = go.Scatter(x=xs, y=ys, mode="text", text=labels, textposition="top center",
                        textfont=dict(color="rgba(230,245,255,0.9)", size=9),
                        hoverinfo="skip", showlegend=False)
        return [g, m, lb]

    gi = len(static)
    fig = go.Figure(data=static + frame_traces(1.0))
    K = 24
    fig.frames = [go.Frame(name="f%d" % k, data=frame_traces(k / (K - 1)),
                           traces=[gi, gi + 1, gi + 2]) for k in range(K)]

    stages = [("Jump", 0.0), ("Early", 0.4), ("Midway", 0.7), ("Settled", 1.0)]

    def nearest(p):
        return "f%d" % round(p * (K - 1))

    steps = [dict(label=lab, method="animate",
                  args=[[nearest(p)], dict(mode="immediate", frame=dict(duration=0, redraw=False),
                        transition=dict(duration=0))]) for lab, p in stages]
    slider = dict(active=len(steps) - 1, x=0.0, y=-0.04, len=0.80, pad=dict(t=30),
                  currentvalue=dict(prefix="Stage: ", font=dict(color="#cfe8dc", size=12)),
                  steps=steps, bgcolor="rgba(255,255,255,0.12)", bordercolor="rgba(255,255,255,0.2)",
                  font=dict(color="#cfe8dc", size=10))

    fig.update_layout(
        height=520, plot_bgcolor="#0c0e13", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#cfe8dc"), showlegend=False, margin=dict(l=72, r=22, t=18, b=74),
        xaxis=dict(range=[-2.7, ZN + 0.4], showgrid=False, zeroline=False, tickmode="array",
                   tickvals=[-2.0] + list(range(ZN)), ticktext=["JUMP"] + _AXIS_TAGS,
                   tickfont=dict(color="#8b93a3", size=10)),
        yaxis=dict(range=[0.2, MAXLANE + 1.0], showgrid=False, zeroline=False, tickmode="array",
                   tickvals=[1, MAXLANE], ticktext=["RAIL", "WIDE"],
                   tickfont=dict(color="#8b93a3", size=10)),
        sliders=[slider],
        updatemenus=[dict(type="buttons", showactive=False, direction="right", x=0.0, y=1.13,
                     xanchor="left", yanchor="top", pad=dict(t=0, r=6),
                     bgcolor="rgba(255,255,255,0.08)", font=dict(color="#e6f5ee"),
                     buttons=[
                         dict(label="▶ Play", method="animate",
                              args=[None, dict(frame=dict(duration=frame_ms, redraw=False),
                                    fromcurrent=True,
                                    transition=dict(duration=frame_ms, easing="cubic-in-out"))]),
                         dict(label="⏸ Pause", method="animate",
                              args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")]),
                     ])])
    if duel:
        fig.add_annotation(xref="paper", x=0.02, yref="paper", y=0.98, showarrow=False, xanchor="left",
                           text="🔴 Contested speed duel projected", font=dict(color="#ff8080", size=12))
    return fig, duel, leaders


_SPEEDMAP_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><style>
 body{margin:0;font-family:Inter,system-ui,sans-serif;color:#e8eaf0;background:#0c0e13}
 .wrap{padding:4px 2px}
 .ctrl{display:flex;align-items:center;gap:8px;margin:2px 4px 6px;flex-wrap:wrap}
 button{background:#1e222c;color:#e8eaf0;border:1px solid #2a2f3b;border-radius:8px;padding:5px 12px;font-weight:600;cursor:pointer;font-family:inherit;font-size:13px}
 button:hover{border-color:#ff6a1a;color:#ff8a3d}
 .spd{padding:4px 9px;font-size:12px}
 .spd.on{background:#ff6a1a;color:#140a03;border-color:#ff6a1a}
 input[type=range]{flex:1;min-width:120px;accent-color:#ff6a1a}
 .stage{font-family:monospace;font-size:11px;color:#8b93a3;min-width:66px;text-align:right}
 .hint{font-size:11px;color:#8b93a3;margin:0 4px 4px}
 svg{width:100%;height:auto;max-height:__MAXH__px;background:#0c0e13;border-radius:12px;display:block;touch-action:none}
 svg g[data-run]{cursor:grab}
</style></head><body><div class="wrap">
 <div class="ctrl"><button id="play">&#9654; Play</button>
  <span style="font-size:11px;color:#8b93a3">Speed</span>
  <button class="spd" data-mult="0.5">0.5&#215;</button>
  <button class="spd on" data-mult="1">1&#215;</button>
  <button class="spd" data-mult="2">2&#215;</button>
  <input type="range" id="scrub" min="0" max="100" value="100">
  <span class="stage" id="stage">Settled</span>
  <button id="reset" title="Put every horse back to its projected lane">&#8634; Reset lanes</button></div>
 <div class="hint">Tip: drag any horse to move it into a different lane. Press Reset lanes to undo.</div>
 <svg id="map" viewBox="__MINX__ __MINY__ __VBW__ __VBH__" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">
  __FILL____LANES____RAIL__<g id="field"></g></svg></div>
<script>
 var D=__DATA__, S=D.S, STEPS=D.steps, NMFS=D.nmfs;
 var SVGNS='http://www.w3.org/2000/svg', svg=document.getElementById('map'), field=document.getElementById('field');
 var stages=[["Jump",0],["Early",0.4],["Midway",0.7],["Settled",1.0]];
 var groups=D.runners.map(function(r,idx){
  var g=document.createElementNS(SVGNS,'g'); g.setAttribute('data-run',idx); var half=S/2; var s='';
  if(r.overlay) s+='<circle cx="0" cy="0" r="'+(half+6)+'" fill="none" stroke="#ff6a1a" stroke-width="3"/>';
  s+='<rect x="'+(-half)+'" y="'+(-half)+'" width="'+S+'" height="'+S+'" rx="6" fill="#1e222c" stroke="rgba(255,255,255,0.25)"/>';
  s+='<image href="'+r.silk+'" x="'+(-half)+'" y="'+(-half)+'" width="'+S+'" height="'+S+'"/>';
  var bq=S*0.33, bx=half-bq*0.5, by=half-bq*0.5;
  s+='<circle cx="'+bx+'" cy="'+by+'" r="'+bq+'" fill="#0b1f2a" stroke="#ff8a3d" stroke-width="2"/>';
  s+='<text x="'+bx+'" y="'+by+'" fill="#fff" font-size="'+(bq*1.15)+'" font-weight="800" text-anchor="middle" dominant-baseline="central">'+r.num+'</text>';
  s+='<rect x="'+(-S*0.95)+'" y="'+(half+2)+'" width="'+(S*1.9)+'" height="'+(NMFS*1.5)+'" rx="4" fill="rgba(12,14,19,0.82)"/>';
  s+='<text x="0" y="'+(half+2+NMFS*0.9)+'" font-size="'+NMFS+'" font-weight="600" fill="#e8eaf0" text-anchor="middle" dominant-baseline="central">'+r.name+'</text>';
  g.innerHTML=s; field.appendChild(g); return g;
 });
 function posAt(r,t){var f=t*(STEPS-1),i=Math.floor(f),fr=f-i,a=r.path[i],b=r.path[Math.min(STEPS-1,i+1)];return [a[0]+(b[0]-a[0])*fr,a[1]+(b[1]-a[1])*fr];}
 function place(idx,p){groups[idx].setAttribute('transform','translate('+p[0]+','+p[1]+')');}
 function render(t){for(var idx=0;idx<D.runners.length;idx++){var r=D.runners[idx];place(idx, r.fixed?r.fixed:posAt(r,t));}var s=stages[0][0];for(var k=0;k<stages.length;k++){if(t>=stages[k][1]-0.001)s=stages[k][0];}document.getElementById('stage').textContent=s;}
 var scrub=document.getElementById('scrub'), playBtn=document.getElementById('play');
 scrub.addEventListener('input',function(){pause();render(scrub.value/100);});
 var playing=false,raf=null,t0=0,startT=0,DUR=5600;
 function step(ts){if(!playing)return;if(!t0)t0=ts;var t=startT+(ts-t0)/DUR;if(t>=1){t=1;playing=false;playBtn.innerHTML='&#9654; Play';}scrub.value=t*100;render(t);if(playing)raf=requestAnimationFrame(step);}
 function pause(){playing=false;if(raf)cancelAnimationFrame(raf);playBtn.innerHTML='&#9654; Play';}
 playBtn.addEventListener('click',function(){if(playing){pause();return;}var t=scrub.value/100;if(t>=1)t=0;startT=t;t0=0;playing=true;playBtn.innerHTML='&#10073;&#10073; Pause';raf=requestAnimationFrame(step);});
 Array.prototype.forEach.call(document.querySelectorAll('.spd'),function(b){b.addEventListener('click',function(){Array.prototype.forEach.call(document.querySelectorAll('.spd'),function(x){x.classList.remove('on');});b.classList.add('on');DUR=5600/parseFloat(b.getAttribute('data-mult'));});});
 document.getElementById('reset').addEventListener('click',function(){for(var i=0;i<D.runners.length;i++)D.runners[i].fixed=null;render(scrub.value/100);});
 // --- drag horses between lanes ---
 function toSVG(evt){var pt=svg.createSVGPoint();pt.x=evt.clientX;pt.y=evt.clientY;return pt.matrixTransform(svg.getScreenCTM().inverse());}
 var dragIdx=-1,dragOff=[0,0];
 groups.forEach(function(g,idx){
  g.addEventListener('pointerdown',function(evt){pause();dragIdx=idx;var p=toSVG(evt);var cur=D.runners[idx].fixed||posAt(D.runners[idx],scrub.value/100);dragOff=[p.x-cur[0],p.y-cur[1]];g.style.cursor='grabbing';g.setPointerCapture(evt.pointerId);evt.preventDefault();});
  g.addEventListener('pointermove',function(evt){if(dragIdx!==idx)return;var p=toSVG(evt);var np=[p.x-dragOff[0],p.y-dragOff[1]];D.runners[idx].fixed=np;place(idx,np);});
  g.addEventListener('pointerup',function(evt){if(dragIdx===idx){dragIdx=-1;g.style.cursor='grab';}});
 });
 render(1.0);
</script></body></html>"""


def build_speedmap_component(entries, cloth, geom, tmap):
    """One animated speed map: watch the field settle and swing around the bend,
    with jockey silks + saddlecloth number + horse name on every runner. Returns a
    self-contained HTML string (play button + stage scrubber, animation in JS)."""
    import json
    field = [e for e in entries if not e.get("scratched")]
    n = max(1, len(field))
    is_turn = (geom.get("turn_direction", "straight") != "straight"
               and geom.get("run_to_turn_m") and geom.get("turn_radius"))
    shown = geom.get("shown_m", 600)
    straighten = geom.get("straighten_m", shown * 0.85)

    order = sorted(field, key=lambda e: tmap.get(e["horse_name"], {}).get("rank", 99))
    # Runners JUMP at the barriers (d=0), settle down the real run-to-turn straight,
    # then round the FIRST bend — so the leader finishes around the bend while the
    # tail of the field is still coming down the straight toward it.
    run_to_turn = geom.get("run_to_turn_m") or shown
    arc = (geom.get("turn_radius") or 0.0) * math.pi / 2.0
    if is_turn:
        lead_d = run_to_turn + arc * 0.85       # leader has swung around the bend
        tail_d = max(40.0, run_to_turn * 0.40)  # backmarker still on the straight
    else:
        lead_d, tail_d = shown * 0.80, shown * 0.28
    gap = (lead_d - tail_d) / max(1, n - 1)

    info = []
    for i, e in enumerate(order):
        t = tmap.get(e["horse_name"], {})
        lane = min(MAX_LANES, max(1, int(t.get("lane", 2))))
        info.append((e, lead_d - i * gap, (lane - 1) * LANE_W))
    d_jump = 0.0                                 # everyone jumps from the start line

    STEPS = 30
    runners = []
    for e, ds, ws in info:
        wj = (e["barrier"] - 1) / max(1, n - 1) * W_OUT
        path = []
        for k in range(STEPS):
            tt = _smooth(k / (STEPS - 1))
            x, y = track_xy(d_jump + (ds - d_jump) * tt, wj + (ws - wj) * tt, geom)
            path.append([round(x, 1), round(-y, 1)])
        edge = (e["market_odds"] / e["fair_odds"] - 1.0) if e.get("fair_odds") else 0.0
        runners.append({"path": path, "num": str(cloth[e["horse_name"]]), "name": e["horse_name"],
                        "silk": silks_engine.silk_data_uri(e["horse_name"], 64), "overlay": edge >= OVERLAY_EDGE})

    d0 = -25.0                                   # show the start line / barriers
    d1 = max(x[1] for x in info) + 70
    samples = [d0 + (d1 - d0) * k / 60.0 for k in range(61)]
    rail = [[round(x, 1), round(-y, 1)] for x, y in (track_xy(s, 0.0, geom) for s in samples)]
    outer = [[round(x, 1), round(-y, 1)] for x, y in (track_xy(s, W_OUT, geom) for s in samples)]

    S = 50.0
    allpts = [p for r in runners for p in r["path"]] + rail + outer
    xs = [p[0] for p in allpts]
    ys = [p[1] for p in allpts]
    minx, maxx = min(xs) - S * 1.2, max(xs) + S * 1.2
    miny, maxy = min(ys) - S * 1.3, max(ys) + S * 1.5

    def ptstr(ps):
        return " ".join("{},{}".format(a, b) for a, b in ps)

    fill = ('<path d="M {} L {} Z" fill="#171a21" stroke="rgba(255,255,255,0.14)" '
            'stroke-width="2"/>'.format(ptstr(rail), ptstr(list(reversed(outer)))))
    lanes = ""
    for ln in range(1, MAX_LANES):
        lp = [[round(x, 1), round(-y, 1)] for x, y in (track_xy(s, ln * LANE_W, geom) for s in samples)]
        lanes += ('<polyline points="{}" fill="none" stroke="rgba(255,255,255,0.06)" '
                  'stroke-width="1" stroke-dasharray="5 7"/>'.format(ptstr(lp)))
    railp = '<polyline points="{}" fill="none" stroke="#ff6a1a" stroke-width="4"/>'.format(ptstr(rail))

    data = json.dumps({"runners": runners, "S": S, "steps": STEPS, "nmfs": round(S * 0.36, 1)})
    html = _SPEEDMAP_TEMPLATE
    for token, val in (("__DATA__", data), ("__FILL__", fill), ("__LANES__", lanes), ("__RAIL__", railp),
                       ("__MINX__", str(round(minx, 1))), ("__MINY__", str(round(miny, 1))),
                       ("__VBW__", str(round(maxx - minx, 1))), ("__VBH__", str(round(maxy - miny, 1))),
                       ("__MAXH__", "560")):
        html = html.replace(token, val)
    return html


def build_speed_map(entries, cloth, geom, tmap=None, frame_ms=300):
    """Tactical settling map across the FULL course: jump -> settle -> bend -> fan out
    off the corner into the home straight. De-clumped with anti-collision; silk-coloured
    borders; four tactical checkpoints on the scrubber."""
    field = [e for e in entries if not e.get("scratched")]
    n = max(1, len(field))
    tmap = tmap or {}
    for e in field:
        e["_es"] = _early_speed(e)
    order = sorted(field, key=lambda x: -x["_es"])
    rank_by = {e["horse_name"]: i for i, e in enumerate(order, start=1)}
    leaders = {e["horse_name"] for e in field if e["_es"] >= 70.0}
    duel = len(leaders) >= 3

    def tac_of(e):
        return tmap.get(e["horse_name"], {})

    def lane_of(e):
        t = tac_of(e)
        if t:
            return t["lane"]
        b = e["barrier"]
        return 1 if b <= 2 else 2 if b <= 5 else 3 if b <= 8 else 4

    is_turn = (geom.get("turn_direction", "straight") != "straight"
               and geom.get("run_to_turn_m") and geom.get("turn_radius"))
    shown = geom["shown_m"]
    L1 = geom.get("run_to_turn_m") or shown
    R = geom.get("turn_radius") or 1
    L2 = L1 + (R * math.pi / 2.0) if is_turn else shown
    total = geom.get("total_m", shown)
    # Leader's maximum travelled distance shown (into the home straight).
    max_travel = min(shown - 10, (geom.get("straighten_m", L2) + 160) if is_turn else shown * 0.72)

    glow_colors, ring_colors = [], []
    for e in field:
        e["_rank"] = rank_by[e["horse_name"]]
        e["_gap"] = (e["_rank"] - 1) * LEAD_SPACING
        sl = lane_of(e)
        t = tac_of(e)
        e["_settle_w"] = (sl - 1) * LANE_W
        e["_fan_w"] = (speedmap_engine.fan_lane(sl, t.get("zone", ""), t.get("tag", ""),
                                                e["_rank"], n) - 1) * LANE_W if is_turn else e["_settle_w"]
        e["_start_w"] = (e["barrier"] - 1) / max(1, n - 1) * W_OUT
        edge = (e["market_odds"] / e["fair_odds"] - 1.0) if e["fair_odds"] else 0.0
        e["_overlay"] = edge >= OVERLAY_EDGE
        ring_colors.append(silks_engine.primary_color(e["horse_name"]))
        if duel and e["horse_name"] in leaders:
            glow_colors.append("rgba(255,60,60,0.42)")
        elif e["_overlay"]:
            glow_colors.append("rgba(255,196,0,0.42)")
        else:
            glow_colors.append("rgba(0,0,0,0)")

    def lane_w_at(e, dtrav):
        if dtrav <= SETTLE_DIST:
            return e["_start_w"] + (e["_settle_w"] - e["_start_w"]) * _smooth(dtrav / SETTLE_DIST)
        if (not is_turn) or dtrav <= L2:
            return e["_settle_w"]
        return e["_settle_w"] + (e["_fan_w"] - e["_settle_w"]) * _smooth(min(1.0, (dtrav - L2) / FAN_DIST))

    def pos_at(e, P):
        dtrav = max(0.0, P - e["_gap"])
        return track_xy(dtrav, lane_w_at(e, dtrav), geom)

    # Anti-collision at the default (fully straightened) view: nudge gaps apart.
    placed = []
    for e in sorted(field, key=lambda x: x["_gap"]):
        fx, fy = pos_at(e, max_travel)
        tries = 0
        while tries < 120 and any((fx - px) ** 2 + (fy - py) ** 2 < MIN_SEP ** 2 for px, py in placed):
            e["_gap"] += 10.0
            fx, fy = pos_at(e, max_travel)
            tries += 1
        placed.append((fx, fy))

    nums = [str(cloth[e["horse_name"]]) for e in field]
    name_lbls = ["{} b{}".format(_abbrev(e["horse_name"]), e["barrier"]) for e in field]
    hovers = ["<b>{} (#{})</b><br>{}<br>Bar {} · {}<br>{}".format(
        e["horse_name"], cloth[e["horse_name"]], silks_engine.jockey_for(e["horse_name"]),
        e["barrier"], tac_of(e).get("lane_name", "-"),
        speedmap_engine.corner_role(tac_of(e).get("zone", ""), tac_of(e).get("tag", ""))) for e in field]

    # --- static track drawing (full path) ---
    samples = [shown * i / 200.0 for i in range(201)]
    rail = [track_xy(s, 0.0, geom) for s in samples]
    outer = [track_xy(s, W_OUT, geom) for s in samples]
    fill_x = [p[0] for p in rail] + [p[0] for p in reversed(outer)]
    fill_y = [p[1] for p in rail] + [p[1] for p in reversed(outer)]
    static = [go.Scatter(x=fill_x, y=fill_y, fill="toself", fillcolor="rgba(23,26,33,0.94)",
                         line=dict(width=0), hoverinfo="skip", showlegend=False)]
    for li in range(1, MAX_LANES):
        lp = [track_xy(s, li * LANE_W, geom) for s in samples]
        static.append(go.Scatter(x=[p[0] for p in lp], y=[p[1] for p in lp], mode="lines",
                                 line=dict(color="rgba(255,255,255,0.07)", width=1, dash="dot"),
                                 hoverinfo="skip", showlegend=False))
    static.append(go.Scatter(x=[p[0] for p in outer], y=[p[1] for p in outer], mode="lines",
                             line=dict(color="rgba(255,255,255,0.22)", width=2), hoverinfo="skip", showlegend=False))
    static.append(go.Scatter(x=[p[0] for p in rail], y=[p[1] for p in rail], mode="lines",
                             line=dict(color="rgba(255,106,26,0.20)", width=12), hoverinfo="skip", showlegend=False))
    static.append(go.Scatter(x=[p[0] for p in rail], y=[p[1] for p in rail], mode="lines",
                             line=dict(color="#ff6a1a", width=3), hoverinfo="skip", showlegend=False))
    s0r, s0o = track_xy(0, 0, geom), track_xy(0, W_OUT, geom)
    static.append(go.Scatter(x=[s0r[0], s0o[0]], y=[s0r[1], s0o[1]], mode="lines",
                             line=dict(color="rgba(255,255,255,0.5)", width=2, dash="dot"),
                             hoverinfo="skip", showlegend=False))
    if is_turn:
        for mark_d, lab_togo in ((L1, total - L1), (L2, total - L2)):
            ma, mb = track_xy(mark_d, 0, geom), track_xy(mark_d, W_OUT, geom)
            static.append(go.Scatter(x=[ma[0], mb[0]], y=[ma[1], mb[1]], mode="lines",
                                     line=dict(color="#ffa94d", width=2, dash="dash"),
                                     hoverinfo="skip", showlegend=False))

    def frame_traces(P):
        xs = [pos_at(e, P)[0] for e in field]
        ys = [pos_at(e, P)[1] for e in field]
        glow = go.Scatter(x=xs, y=ys, mode="markers",
                          marker=dict(size=42, color=glow_colors, line=dict(width=0)),
                          hoverinfo="skip", showlegend=False)
        main = go.Scatter(x=xs, y=ys, mode="markers+text",
                          marker=dict(size=27, color="#0b1f2a", line=dict(width=4, color=ring_colors)),
                          text=nums, textposition="middle center",
                          textfont=dict(color="white", size=12, family="Arial Black"),
                          hovertext=hovers, hoverinfo="text", showlegend=False)
        lbl = go.Scatter(x=xs, y=ys, mode="text", text=name_lbls, textposition="top center",
                         textfont=dict(color="rgba(230,245,255,0.9)", size=8),
                         hoverinfo="skip", showlegend=False)
        return [glow, main, lbl]

    gi = len(static)
    fig = go.Figure(data=static + frame_traces(max_travel))   # default: straightened / off corner
    K = 30
    fig.frames = [go.Frame(name="f%d" % k, data=frame_traces(max_travel * k / (K - 1)),
                           traces=[gi, gi + 1, gi + 2]) for k in range(K)]

    # Four tactical checkpoints (metres to go) -> leader travelled distance.
    if is_turn:
        checkpoints = [("Jump / Barriers ({}m)".format(total), 0.0),
                       ("Settled Back Straight ({}m)".format(total - 400), 400.0),
                       ("Mid-Bend / The Turn ({}m)".format(total - 900), 900.0),
                       ("Straightening / Off Corner ({}m)".format(total - 1200), 1200.0)]
    else:
        checkpoints = [("Jump", 0.0), ("Early", max_travel * 0.33),
                       ("Midway", max_travel * 0.66), ("Settled", max_travel)]

    def nearest(dist):
        return "f%d" % round(min(1.0, dist / max(1.0, max_travel)) * (K - 1))
    steps = [dict(label=lab, method="animate",
                  args=[[nearest(min(d, max_travel))], dict(mode="immediate",
                        frame=dict(duration=0, redraw=False), transition=dict(duration=0))])
             for lab, d in checkpoints]
    slider = dict(active=len(steps) - 1, x=0.0, y=-0.02, len=0.80, pad=dict(t=28),
                  currentvalue=dict(prefix="Stage: ", font=dict(color="#cfe8dc", size=12)),
                  steps=steps, bgcolor="rgba(255,255,255,0.12)", bordercolor="rgba(255,255,255,0.2)",
                  font=dict(color="#cfe8dc", size=10))

    # --- framing: fit the ENTIRE course with ~10% padding, equal aspect ---
    allx = [p[0] for p in rail + outer]
    ally = [p[1] for p in rail + outer]
    padx = (max(allx) - min(allx)) * 0.10 + 20
    pady = (max(ally) - min(ally)) * 0.10 + 20
    fig.update_layout(
        title=dict(text=geom["label"], font=dict(color="#e6f5ee", size=14)),
        height=720, plot_bgcolor="#0c0e13", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#cfe8dc"), showlegend=False, margin=dict(l=16, r=20, t=52, b=98),
        xaxis=dict(range=[min(allx) - padx, max(allx) + padx], showticklabels=False,
                   showgrid=False, zeroline=False),
        yaxis=dict(range=[min(ally) - pady, max(ally) + pady], showticklabels=False,
                   showgrid=False, zeroline=False, scaleanchor="x", scaleratio=1),
        sliders=[slider],
        updatemenus=[dict(type="buttons", showactive=False, direction="right",
                          x=0.0, y=1.07, xanchor="left", yanchor="top",
                          pad=dict(t=0, r=6), bgcolor="rgba(255,255,255,0.08)",
                          font=dict(color="#e6f5ee"),
                          buttons=[
                              dict(label="▶ Play", method="animate",
                                   args=[None, dict(frame=dict(duration=frame_ms, redraw=False),
                                                    fromcurrent=True,
                                                    transition=dict(duration=frame_ms, easing="cubic-in-out"))]),
                              dict(label="⏸ Pause", method="animate",
                                   args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")]),
                          ])])

    if is_turn:
        be = track_xy(L1, W_OUT, geom)
        st_pt = track_xy(L2, W_OUT, geom)
        fig.add_annotation(x=be[0], y=be[1] - 24, showarrow=False,
                           text="⚠️ Bend Entry ({}m)".format(total - int(L1)),
                           font=dict(color="#ffc078", size=11), bgcolor="rgba(7,13,18,0.85)")
        fig.add_annotation(x=st_pt[0] + 26, y=st_pt[1], showarrow=False, xanchor="left",
                           text="\U0001f3c1 Straightening ({}m)".format(total - int(L2)),
                           font=dict(color="#ffc078", size=11), bgcolor="rgba(7,13,18,0.85)")
    if duel:
        fig.add_annotation(xref="paper", x=0.02, yref="paper", y=0.98, showarrow=False, xanchor="left",
                           text="\U0001f534 Contested speed duel: {}".format(", ".join(sorted(leaders))),
                           font=dict(color="#ff8080", size=12))
    return fig, duel, leaders


# -----------------------------------------------------------------------------
# Tab 1 helpers: runner cards + career drawer
# -----------------------------------------------------------------------------
_STAGE_WORD = {1: "1ST UP", 2: "2ND UP", 3: "3RD UP", 4: "4TH UP", 5: "5TH+ UP"}


def _ord(n):
    return "{}{}".format(n, "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def _ms_date(ms):
    """Epoch-ms -> short date string (e.g. '12 Jul 26'), or '—' when absent."""
    if not ms:
        return "—"
    return datetime.datetime.utcfromtimestamp(ms / 1000).strftime("%d %b %y")


def _prep_markup(prep_run_num, tag):
    word = _STAGE_WORD[min(int(prep_run_num), 5)]
    if "PEAK TARGET" in tag:
        return ('<span class="rc-prep rc-peak" title="Campaign stage: run number this preparation. '
                'TARGET PEAK = the planned best run, expected to be at its fittest.">{} 🎯 TARGET PEAK</span>'.format(word))
    if "TAPERING" in tag:
        return ('<span class="rc-prep rc-taper" title="Campaign stage. TAPERING = past its peak this '
                'preparation; fitness may be fading.">{} · TAPERING</span>'.format(word))
    return ('<span class="rc-prep" title="Campaign stage: run number this preparation. CONDITIONING = '
            'still building fitness; may need the run.">{} · CONDITIONING</span>'.format(word))


def _form_blocks(trajectory, par=None, positions=None, is_debut=False):
    """Render the last-5 form pills NEWEST -> OLDEST (L1 latest, left to right).

    Boxes are coloured relative to `par` (the rating needed to win today's class)
    so "green = good enough to win this grade", amber = thereabouts, red = below.
    `positions` (newest-first finishing positions) are shown under each rating.
    These are ACTUAL runs only — barrier trials are excluded upstream.
    """
    # No ratings to show: a debutant gets a clean DEBUT badge; anything else
    # (data gap) says form is unavailable — never fabricated pills.
    if not trajectory:
        if is_debut:
            return ('<div class="chip-grid">'
                    '<span class="rec-chip hot">🆕 DEBUT</span>'
                    '<span class="rec-chip"><span class="rv">1st career start · • UNEXPOSED</span></span>'
                    '</div>')
        return ('<div class="chip-grid">'
                '<span class="rec-chip"><span class="rv">Recent form unavailable</span></span></div>')
    newest_first = list(reversed(trajectory))          # trajectory stored oldest->newest
    info = classify_trajectory(newest_first)
    labels = ["L1 (Latest)", "L2", "L3", "L4", "L5"]
    lab_cells = "".join('<span class="form-l">{}</span>'.format(lbl)
                        for lbl in labels[:len(newest_first)])
    box_cells = ""
    for i, v in enumerate(newest_first, start=1):
        if par is not None:
            cls = "fb-hi" if v >= par else "fb-mid" if v >= par - 7 else "fb-lo"
            tier = "would win this grade" if v >= par else ("competitive here" if v >= par - 7
                                                            else "below this grade")
            scale = "Green = at/above the ~{:.0f} par to win today's class, amber = within reach, red = below.".format(par)
        else:
            cls = "fb-hi" if v > 70 else "fb-mid" if v >= 50 else "fb-lo"
            tier = "strong" if v > 70 else "fair" if v >= 50 else "weak"
            scale = "Green = strong (70+), amber = fair (50-70), red = weak (under 50)."
        run_lbl = "most recent run" if i == 1 else "{} runs back".format(i - 1)
        pos_html, pos_txt = "", ""
        if positions and i - 1 < len(positions):
            p = positions[i - 1]
            pcls = "fp-win" if p == 1 else "fp-plc" if p <= 3 else "fp-out"
            pos_html = '<span class="fb-pos {pc}">{o}</span>'.format(pc=pcls, o=_ord(p))
            pos_txt = " — finished {}".format(_ord(p))
        box_cells += ('<div class="form-box {cls}" title="{lbl}: rated {v:.0f}/100{pt} — {tier}. {scale}">'
                      '<span class="fb-rt">{v:.0f}</span>{ph}</div>'.format(
                          cls=cls, lbl=run_lbl, v=v, tier=tier, scale=scale, pt=pos_txt, ph=pos_html))
    if info["cls"] == "up":
        badge = ('<span class="trend-up" title="Which way recent runs are heading — improving by this many '
                 'rating points per run. This is the direction of PAST runs only, separate from today\'s Projected.">'
                 '▲ RISING (+{:.1f}/run)</span>'.format(info["per_run"]))
    elif info["cls"] == "dn":
        badge = ('<span class="trend-dn" title="Which way recent runs are heading — easing off by this many '
                 'rating points per run. This is the direction of PAST runs only, separate from today\'s Projected.">'
                 '▼ EASING (-{:.1f}/run)</span>'.format(info["per_run"]))
    else:
        badge = ('<span class="trend-fl" title="Recent runs are holding their level — no genuine rise or fall. '
                 'This is the direction of PAST runs only, separate from today\'s Projected.">'
                 '• STABLE (±0.0/run)</span>')
    note = ('<div class="form-note"><b>Reading this:</b> each box is a past rating with the <b>finishing '
            'position</b> under it — <span style="color:#34d27f">green</span> = good enough to win today\'s grade, '
            '<span style="color:#fbbf24">amber</span> = thereabouts, '
            '<span style="color:#ff9a8f">red</span> = below it. The trend shows the direction of those '
            '<b>past</b> runs; the <b>Projected</b> number up top is today\'s forward rating (it adds class, '
            'distance and track). Full last-5 detail is in <b>DETAILS → Last 5 runs</b>.</div>')
    return ('<div class="form-hdr" title="The horse\'s last 5 ratings + finish, newest on the left.">RECENT FORM &middot; LAST 5 (rating / finish, Newest &#10142; Oldest)</div>'
            '<div class="form-row" style="margin:2px 0 0">{labs}</div>'
            '<div class="form-row">{boxes}{badge}</div>{note}'.format(
                labs=lab_cells, boxes=box_cells, badge=badge, note=note))


def _angle_badges(angles):
    if not angles:
        return ""
    chips = []
    for a in angles:
        cls = "ang-pos" if a["points"] > 0 else "ang-neg"
        dot = "🟢" if a["points"] > 0 else "🔴"
        tt = ("Situational angle (auto-detected pattern), {}{:+.1f} pts. Green helps, red hurts. "
              "All angles together are capped at ±2.5.").format(a["name"] + ": ", a["points"])
        chips.append('<span class="ang {}" title="{}">{} {} ({:+.1f})</span>'.format(
            cls, tt, dot, a["name"], a["points"]))
    return '<div class="ang-row">' + "".join(chips) + "</div>"


def _custom_badges(badges):
    if not badges:
        return ""
    chips = []
    for b in badges:
        cls = "cust" if b["points"] >= 0 else "cust-neg"
        dot = "🟣" if b["points"] >= 0 else "🔴"
        label = b["description"].split(" (")[0]
        tt = "Your own custom rule ({:+.1f} pts): {}".format(b["points"], b["description"])
        chips.append('<span class="ang {}" title="{}">{} {} ({:+.1f})</span>'.format(
            cls, tt, dot, label, b["points"]))
    return '<div class="ang-row">' + "".join(chips) + "</div>"


def _trigger_badges(r):
    """Render the #3 native-trigger chips (steam plunge, apprentice claim).

    Pace and wet-form carry score points and render via _env_badges; these two
    are display chips (steam is market info; the claim's points are in the base).
    """
    trigs = r.get("triggers") or []
    if not trigs:
        return ""
    tips = {
        "steam": "Late steam plunge — the price shortened sharply across the last few flucs (smart money).",
        "claim": "Apprentice's weight claim — lightens the carried weight, worth +0.38 pts/kg in the rating.",
    }
    chips = []
    for t in trigs:
        cls = t.get("cls", "claim")
        chips.append('<span class="trig trig-{}" title="{}">{}</span>'.format(
            cls, tips.get(cls, ""), t.get("label", "")))
    return '<div class="ang-row">' + "".join(chips) + "</div>"


def _env_badges(badges):
    if not badges:
        return ""
    chips = []
    for b in badges:
        cls = "env-pos" if b["points"] >= 0 else "env-neg"
        icon = "⚡" if b["points"] >= 0 else "🌀"
        tt = ("Conditions modifier from pace, wind or the day's track pattern "
              "({}{:+.1f} pts).").format(b["name"] + ": ", b["points"])
        chips.append('<span class="ang {}" title="{}">{} {} ({:+.1f})</span>'.format(
            cls, tt, icon, b["name"], b["points"]))
    return '<div class="ang-row">' + "".join(chips) + "</div>"


def _tactical_line(r):
    tag = str(r.get("tactical_tag", "-"))
    cls = ""
    if any(k in tag for k in ("3WNC", "Duel", "Pocket")):
        cls = "tac-tax"
    elif "Box" in tag:
        cls = "tac-box"
    tt = ("Projected run: where it settles in the field (zone), how far off the inside rail (lane), "
          "its early-speed figure (📡 = read from the horse's real in-run positions), and a tactical note.")
    es_mark = "📡" if r.get("es_live") else ""
    return ('<div class="tac" title="{tt}">Settle: <b>{zone}</b> &middot; <b>{lane}</b> &middot; ES {es}{mark} '
            '&middot; <span class="{cls}">{blurb}</span></div>'.format(
                tt=tt, mark=es_mark,
                zone=r.get("settle_zone", "-"), lane=r.get("lane_name", "-"),
                es=r.get("early_speed"), cls=cls, blurb=r.get("tactical_blurb", "-")))


def _style_current(df, col, value):
    def style(row):
        hit = str(row[col]) == str(value)
        return ["background-color:#fde68a;color:#111;font-weight:700" if hit else "" for _ in row]
    return df.style.apply(style, axis=1)


def _render_career_drawer(r, race):
    profile = career_profiles.generate_profile(
        r["horse_name"], race["distance"], r["prep_run_num"], r["base"],
        fk=r.get("fk"), runs=r.get("runs_all"))
    bio, car = profile["bio"], profile["career"]
    cond_bucket = r["cond"]

    records, facts = profile["records"], profile["facts"]
    cond = profile["condition"]
    rec_avg = profile.get("rec_avg", {})

    def _rec_chips(keys):
        out = ""
        labels = {"Car": "Career", "Crs": "Track", "Crs&Dist": "Track+Dist", "Dist": "Distance"}
        for k in keys:
            hot = (k in ("Dist", "Crs&Dist", "Crs"))
            rec = records.get(k, "0: 0-0-0")
            head = rec.split(":")[0].strip()
            starts = int(head) if head.isdigit() else 0
            av = rec_avg.get(k)
            avt = " · avg {:.0f}".format(av) if (av is not None and starts > 0) else ""
            out += '<div class="rec-chip{hot}"><span class="rl">{lbl}</span>' \
                   '<span class="rv">{v}{avt}</span></div>'.format(
                       hot=" hot" if hot else "", lbl=labels.get(k, k), v=rec, avt=avt)
        return '<div class="chip-grid">' + out + "</div>"

    def _rates_chips():
        out = ""
        for k in ["Good", "Soft", "Heavy", "Synthetic"]:
            cd = cond.get(k, {})
            rec = cd.get("rec", "0: 0-0-0")
            av = cd.get("avg_score")
            rate = " · rates {:.0f}".format(av) if av is not None else ""
            hot = (k == cond_bucket)
            out += '<div class="rec-chip{hot}"><span class="rl">{k}</span>' \
                   '<span class="rv">{rec}{rate}</span></div>'.format(hot=" hot" if hot else "", k=k, rec=rec, rate=rate)
        d = profile["distance"]
        drec = "{}: {}-{}-{}".format(d["starts"], d["wins"], d["places"],
                                     max(0, d["starts"] - d["wins"] - d["places"]))
        dr = " · rates {:.0f}".format(d["avg_score"]) if d.get("avg_score") is not None else ""
        out += '<div class="rec-chip hot"><span class="rl">{}m</span><span class="rv">{rec}{rate}</span></div>'.format(
            d["distance"], rec=drec, rate=dr)
        return '<div class="chip-grid">' + out + "</div>"

    def _conn_chips():
        rows = [("Jockey", bio["jockey"], bio["jockey_l50"], bio["jockey_roi"]),
                ("Trainer", bio["trainer"], bio["trainer_l50"], bio["trainer_roi"]),
                ("J/T Combo", "", bio["jt_combo"], bio["jt_roi"])]
        out = ""
        for role, who, sr, roi in rows:
            name = (who + " · ") if who else ""
            out += ('<div class="rec-chip"><span class="rl">{role}</span>'
                    '<span class="rv">{name}12m SR {sr}</span></div>'.format(
                        role=role, name=name, sr=sr, roi=roi))
        return '<div class="chip-grid">' + out + "</div>"

    runs = r.get("real_runs") or []   # last 5 ACTUAL runs (trials excluded)
    with st.expander("📋 DETAILS"):
        t_main, t_runs = st.tabs(["📊 Ratings · connections · adjust", "🏇 Last 5 runs"])
        with t_main:
            if profile["hot_form_winners"] > 0:
                st.markdown('<span class="hot-badge">🔥 Hot Form Race: {} Winner{} Produced</span>'.format(
                    profile["hot_form_winners"], "s" if profile["hot_form_winners"] != 1 else ""),
                    unsafe_allow_html=True)

            st.markdown(
                '<div class="pedi"><b>{name}</b> — {bio} ({code}) · Prizemoney <b>${prize:,.0f}</b><br>'
                'Sire <b>{sire}</b> &nbsp;|&nbsp; Dam <b>{dam}</b> &nbsp;|&nbsp; Dam Sire <b>{damsire}</b></div>'.format(
                    name=r["horse_name"], bio=bio["age_sex"], code=bio["code"], prize=bio["prizemoney"],
                    sire=bio["sire"], dam=bio["dam"], damsire=bio["dam_sire"]),
                unsafe_allow_html=True)

            st.markdown('<div class="grid-hdr" title="Starts: Wins-2nds-3rds, then the average 0-100 rating in '
                        'that bucket. Today\'s track & distance highlighted.">'
                        'RECORD &nbsp;(Starts: W-2-3 · avg rating)</div>', unsafe_allow_html=True)
            st.markdown(_rec_chips(["Car", "Crs", "Crs&Dist", "Dist"]), unsafe_allow_html=True)

            st.markdown('<div class="grid-hdr" title="Starts: Wins-2nds-3rds on each going and at today\'s trip, '
                        'then the average 0-100 rating there. Today\'s going is highlighted.">'
                        'BY SURFACE &amp; DISTANCE (Starts: W-2-3 · rating)</div>', unsafe_allow_html=True)
            st.markdown(_rates_chips(), unsafe_allow_html=True)

            st.markdown('<div class="grid-hdr" title="Form King 12-month win strike rate for the jockey and '
                        'trainer, and the trainer/jockey combination.">'
                        'CONNECTIONS (12-month strike rate, Form King)</div>', unsafe_allow_html=True)
            st.markdown(_conn_chips(), unsafe_allow_html=True)

            st.markdown('<div class="grid-hdr">FACTS</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="chip-grid">'
                '<div class="fact-chip"><span class="fl">DLS</span>{dls}d</div>'
                '<div class="fact-chip"><span class="fl">DLW</span>{dlw}</div>'
                '<div class="fact-chip alt"><span class="fl">DOD</span>{dod}</div>'
                '<div class="fact-chip alt"><span class="fl">ROI</span>{roi}</div></div>'.format(
                    dls=r["dls"], dlw=facts["DLW"], dod=facts["DOD"], roi=facts["ROI %"]),
                unsafe_allow_html=True)

            if r["angles"]:
                st.markdown("**Active situational angles:** " + ", ".join(
                    "{} ({:+.1f})".format(a["name"], a["points"]) for a in r["angles"]))

            mkey = "adj_{}_{}".format(r["race_id"], r["entry_id"])
            st.session_state.setdefault(mkey, 0.0)
            st.number_input("Manual Score Adjustment (± pts)", step=0.5, key=mkey, format="%.1f",
                            help="Applies instantly to this runner's projected score, fair price and edge.")

        with t_runs:
            if r.get("is_debut") or not runs:
                st.info("🆕 **Debutant — 1st career start.** No prior race form to show.")
            else:
                st.caption("The last 5 **actual runs** (barrier trials excluded) — date, trip, going, "
                           "the rating earned and where it finished (newest first).")
                df5 = pd.DataFrame([{
                    "Run": "L{}".format(i + 1), "Date": _ms_date(run.get("date")),
                    "Trip": "{}m".format(run["dist"]), "Going": run.get("going") or "—",
                    "Rated": int(round(run["rating"])) if run.get("rating") is not None else None,
                    "Finish": _ord(run["pos"]),
                } for i, run in enumerate(runs)])
                st.dataframe(df5, use_container_width=True, hide_index=True, column_config={
                    "Rated": st.column_config.NumberColumn("Rated", help="The 0-100 rating earned that day."),
                    "Finish": st.column_config.TextColumn("Finish", help="Finishing position that day."),
                    "Date": st.column_config.TextColumn("Date", help="Race date."),
                })
                st.caption("ℹ️ The RISING/EASING trend on the card is the slope of these actual-run ratings.")


_RFS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th+"}


def render_worksheet(rows, race, cloth):
    """High-density Don-Scott-style rating worksheet with editable User+/- and Scratch."""
    race_id = race["race_id"]
    entry_ids = [r["entry_id"] for r in rows]
    data = []
    for r in rows:
        akey = "adj_{}_{}".format(race_id, r["entry_id"])
        data.append({
            "Scratch": bool(r["scratched"]),
            "TAB": cloth[r["horse_name"]],
            "🎽": silks_engine.silk_data_uri(r["horse_name"], 28),
            "Horse": r["horse_name"],
            "RFS": _RFS.get(min(int(r["prep_run"]), 5), "-"),
            "DLS": r["dls"],
            "Base": round(r["base"], 1),
            "FormΔ": r["form_delta"],
            "CondΔ": r["cond_delta"],
            "DistΔ": r["dist_delta"],
            "Angles": r["angles_clamped"],
            "User+/-": float(st.session_state.get(akey, 0.0) or 0.0),
            "Projected": r["projected"],
            "My Price": r["disp_fair"],
            "Live Market": r["market"],
            "Edge %": round(r["edge"] * 100, 1) if r["edge"] is not None else None,
        })
    df = pd.DataFrame(data)
    cfg = {
        "Scratch": st.column_config.CheckboxColumn("Scr", width="small"),
        "TAB": st.column_config.NumberColumn("TAB", width="small", help="Saddlecloth / TAB number."),
        "🎽": st.column_config.ImageColumn("Silk", width="small", help="Jockey silks."),
        "Horse": st.column_config.TextColumn("Horse", width="medium", help="Runner name."),
        "RFS": st.column_config.TextColumn("RFS", width="small", help="Runs from spell (prep stage)"),
        "DLS": st.column_config.NumberColumn("DLS", width="small", help="Days since last run"),
        "Base": st.column_config.NumberColumn("Base", format="%.1f",
                                              help="Raw 0-100 model rating before today's adjustments."),
        "FormΔ": st.column_config.NumberColumn("FormΔ", format="%+.1f",
                                               help="Points added or removed for recent form trajectory."),
        "CondΔ": st.column_config.NumberColumn("CondΔ", format="%+.1f",
                                               help="Points for how the horse handles today's going (track condition)."),
        "DistΔ": st.column_config.NumberColumn("DistΔ", format="%+.1f",
                                               help="Points for how the horse suits today's distance."),
        "Angles": st.column_config.NumberColumn("Angles", format="%+.1f", help="Clamped situational (-2.5..+2.5)"),
        "User+/-": st.column_config.NumberColumn("User+/-", step=0.5, format="%.1f",
                                                 help="Editable manual adjustment — applies instantly"),
        "Projected": st.column_config.NumberColumn("Projected", format="%.1f",
                                                   help="Final rating after all adjustments — what the price is built from."),
        "My Price": st.column_config.NumberColumn("My Price", format="$%.2f",
                                                  help="Fair odds from the model (100% book)."),
        "Live Market": st.column_config.NumberColumn("Live Market", format="$%.2f",
                                                     help="Current Form King market price (average across bookmakers)."),
        "Edge %": st.column_config.NumberColumn("Edge %", format="%+.1f%%",
                                                help="How much more the market pays than our fair price. Positive = value."),
    }
    readonly = [c for c in df.columns if c not in ("Scratch", "User+/-")]
    edited = st.data_editor(df, column_config=cfg, disabled=readonly, hide_index=True,
                            use_container_width=True, key="ws_{}".format(race_id))

    changed = False
    for idx, eid in enumerate(entry_ids):
        akey = "adj_{}_{}".format(race_id, eid)
        skey = "scr_{}_{}".format(race_id, eid)
        nv = float(edited.at[idx, "User+/-"] or 0.0)
        sv = bool(edited.at[idx, "Scratch"])
        if abs(float(st.session_state.get(akey, 0.0) or 0.0) - nv) > 1e-9:
            st.session_state[akey] = nv
            changed = True
        if bool(st.session_state.get(skey, False)) != sv:
            st.session_state[skey] = sv
            changed = True
    if changed:
        st.rerun()
    st.caption("Edit **User+/-** or **Scr** to re-score instantly — the fair book re-normalises to 100% "
               "and every price/edge updates. Base + clamped Angles + User +/- = Projected.")


def render_bet_slip(r, race):
    """Interactive bet slip on a runner card: log a To-Win or Fixed-Stake bet
    into the syndicate ledger, with live stake/return/edge metrics."""
    rid = r["entry_id"]
    fair = r.get("disp_fair")
    with st.expander("🎯 LOG BET — {}".format(r["horse_name"])):
        mode = st.radio("Bet mode", ["🎯 To Win $", "💵 Fixed Stake"], horizontal=True,
                        key="bm_{}".format(rid))
        default_odds = float(r.get("market") or fair or 2.0)
        odds = st.number_input("Odds taken", min_value=1.01, value=round(default_odds, 2),
                               step=0.1, key="odds_{}".format(rid),
                               help="Pre-filled with the current market price; edit to the price you took.")
        if mode.startswith("🎯"):
            target = st.number_input("Target win ($)", min_value=1.0, value=100.0, step=10.0,
                                     key="tw_{}".format(rid))
            stake = target / (odds - 1.0) if odds > 1.0 else 0.0
        else:
            stake = st.number_input("Stake ($)", min_value=1.0, value=50.0, step=10.0,
                                    key="stk_{}".format(rid))
            target = stake * (odds - 1.0)
        edge = ((odds / fair) - 1.0) if fair else None
        m1, m2, m3 = st.columns(3)
        m1.metric("Stake", "${:.2f}".format(stake))
        m2.metric("Potential return", "${:.2f}".format(stake * odds))
        m3.metric("Edge @ bet", "{:+.1f}%".format(edge * 100) if edge is not None else "—")
        if edge is not None and edge > 0:
            st.success("🟢 +EV — {:+.1f}% over fair (${:.2f}).".format(edge * 100, fair))
        if st.button("💾 Confirm & Log Bet", key="log_{}".format(rid), use_container_width=True):
            log_user_bet({
                "meeting_id": meeting["meeting_id"], "race_id": race["race_id"],
                "track_name": meeting["track_name"], "race_number": race["race_number"],
                "runner_id": rid, "horse_name": r["horse_name"],
                "saddlecloth": r.get("saddlecloth"), "bet_mode": "TO_WIN" if mode.startswith("🎯") else "STAKE",
                "target_win": round(target, 2), "stake": round(stake, 2), "odds_taken": round(odds, 2),
                "fair_odds": round(fair, 2) if fair else None, "edge_at_bet": edge})
            st.toast("✅ Logged {} @ ${:.2f} — stake ${:.2f}".format(r["horse_name"], odds, stake))
            st.rerun()


def render_bet_ledger():
    """Sidebar drawer: the syndicate bet ledger — live metrics, table, cancel."""
    # Guarantee the user_bets table exists even on a DB that persisted from a
    # pre-ledger build, then settle anything with live results.
    conn = get_connection()
    try:
        ensure_schema(conn)
    finally:
        conn.close()
    try:
        sync_formking.settle_pending_bets()
        bets = load_user_bets()
    except Exception as exc:
        st.sidebar.caption("💼 Bet ledger unavailable: {}".format(exc))
        return
    with st.sidebar.expander("💼 Syndicate Bet Ledger ({})".format(len(bets)), expanded=False):
        mx = ledger_metrics(bets)
        a, b = st.columns(2)
        a.metric("Active outlay", "${:,.2f}".format(mx["active_outlay"]),
                 help="Total stake across all PENDING bets.")
        b.metric("Settled P&L", "${:,.2f}".format(mx["settled_pnl"]),
                 delta="{:+.2f}".format(mx["settled_pnl"]) if mx["n_settled"] else None)
        c, d = st.columns(2)
        c.metric("ROI", "{:+.1f}%".format(mx["roi"]) if mx["n_settled"] else "—")
        d.metric("Strike rate", "{:.0f}%".format(mx["strike"]) if mx["n_settled"] else "—")
        if not bets:
            st.caption("No bets logged yet. Open a runner card and use 🎯 LOG BET.")
            return
        df = pd.DataFrame([{
            "Bet": "{} R{} · {}".format(b["track_name"], b["race_number"], b["horse_name"]),
            "Mode": b["bet_mode"], "Stake": "${:.2f}".format(b["stake"] or 0),
            "Odds": "${:.2f}".format(b["odds_taken"] or 0), "Status": b["status"],
            "P&L": "${:+.2f}".format(b["net_pnl"] or 0) if b["status"] in ("WON", "LOST") else "—",
        } for b in bets])
        st.dataframe(df, use_container_width=True, hide_index=True)
        pend = [b for b in bets if b["status"] == "PENDING"]
        if pend:
            opts = {"#{} {} R{} · {}".format(b["bet_id"], b["track_name"], b["race_number"], b["horse_name"]): b["bet_id"]
                    for b in pend}
            sel = st.selectbox("Cancel a pending bet", ["—"] + list(opts), key="cancel_sel")
            if sel != "—" and st.button("❌ Cancel Bet", key="cancel_btn", use_container_width=True):
                cancel_user_bet(opts[sel]); st.rerun()


def render_runner_card(r, race, cloth):
    key = "scr_{}_{}".format(race["race_id"], r["entry_id"])
    with st.container(border=True):
        left, right, ctrl = st.columns([3.0, 2.3, 0.9])

        if r["scratched"]:
            left.markdown(
                '<img class="silk" src="{}" style="opacity:.45"/>'
                '<span class="rc-cloth">{}</span><span class="rc-name" style="text-decoration:line-through;color:#94a3b8">{}</span>'
                '<div class="rc-sub">Barrier {} · {:.1f}kg · <span class="scr-flag">SCRATCHED</span></div>'.format(
                    silks_engine.silk_data_uri(r["horse_name"]), cloth[r["horse_name"]],
                    r["horse_name"], r["barrier"], r["weight"]),
                unsafe_allow_html=True)
            right.markdown('<div class="rc-sub" style="text-align:right">Removed — remaining prices re-normalised.</div>',
                           unsafe_allow_html=True)
            ctrl.checkbox("🩹 Scratch", key=key)
            return

        prep = profile_runner(r["horse_name"], r["prep_run_num"], r["base"], r.get("runs_all"))
        proj_cls = "proj-up" if r["par_delta"] >= 0 else "proj-dn"
        left.markdown(
            '<img class="silk" src="{silk}" alt="silk" title="Jockey silks &amp; saddlecloth number — the colours the horse carries in the race."/>'
            '<span class="rc-cloth" title="Saddlecloth number.">{cloth}</span><span class="rc-name">{name}</span>'
            '<div class="rc-sub" title="Barrier drawn, carried weight, the raw 0-100 model rating, and the jockey.">Barrier {bar} · {wt:.1f}kg · Model {score:.1f} · {jky}</div>'
            '<div class="rc-proj {pcls}" title="Projected rating after today\'s adjustments, and how far it sits above (+) or below (-) the par score needed to win this class.">Projected: {proj:.1f} (vs Par: {delta:+.1f})</div>'
            '{tac}{prep}{angles}{cust}{env}{trig}{form}'.format(
                cloth=cloth[r["horse_name"]], name=r["horse_name"], bar=r["barrier"],
                wt=r["weight"], score=r["base"], pcls=proj_cls,
                silk=silks_engine.silk_data_uri(r["horse_name"]),
                jky=silks_engine.jockey_for(r["horse_name"]),
                proj=r["projected"], delta=r["par_delta"], tac=_tactical_line(r),
                prep=_prep_markup(r["prep_run_num"], prep["tag"]),
                angles=_angle_badges(r["angles"]), cust=_custom_badges(r["custom_badges"]),
                env=_env_badges(r.get("env_badges", [])), trig=_trigger_badges(r),
                form=_form_blocks(r["traj"], par_for(race["class_name"]),
                                  [run["pos"] for run in (r.get("real_runs") or [])],
                                  is_debut=r.get("is_debut", False))),
            unsafe_allow_html=True)

        if r["value_gone"]:
            badge = ('<span class="edge-badge edge-gone" title="The market has firmed past our price — '
                     'the value that was there is gone, so no bet.">🛑 VOID / VALUE GONE</span>')
        elif r["overlay"]:
            badge = ('<span class="edge-badge edge-pos" title="Overlay: the market is paying more than our fair '
                     'price, so this bet has positive expected value (+EV) by this margin.">🔥 +{:.0f}% EV OVERLAY</span>'.format(r["edge"] * 100))
        elif r["edge"] > 0:
            badge = ('<span class="edge-badge edge-neg" title="A small positive edge, but too thin to clear our bet '
                     'threshold.">+{:.0f}% (thin)</span>'.format(r["edge"] * 100))
        else:
            badge = ('<span class="edge-badge edge-neg" title="Underlay: the market price is shorter than our fair '
                     'price, so there is no value — no bet.">UNDERLAY {:.0f}%</span>'.format(r["edge"] * 100))

        senti_html = ('<span class="senti senti-{}" title="Market move since the open: STEAMER = being backed in '
                      '(shortening), DRIFTER = drifting out (lengthening), STABLE = little change.">{}</span>'.format(
                          r["sentiment"], r["sentiment_label"])
                      if r["sentiment_label"] else "")
        fluc_html = ('<div class="fluc-line" title="Price history: opening price → current price.">{}{}</div>'.format(
                         r["fluc_string"], senti_html)
                     if r["fluc_string"] else "")

        right.markdown(
            '<div class="price-wrap">'
            '<div class="tile tile-mine" title="MY PRICE — the fair odds the model rates this horse at, from a book that sums to 100%. Bet only when the market pays more than this."><div class="lbl">MY PRICE</div><div class="val">${:.2f}</div></div>'
            '<div><div class="tile tile-mkt" title="LIVE MARKET — the current Form King price (average across bookmakers)."><div class="lbl">LIVE MARKET</div><div class="val">${:.2f}</div></div>{}</div>'
            '</div>{}'.format(r["disp_fair"], r["market"], badge, fluc_html),
            unsafe_allow_html=True)

        if r["overlay"]:
            stake_txt = "<b>${:,.2f}</b> (to win ${:.0f})".format(r["stake_dollars"], TARGET_PROFIT)
        else:
            stake_txt = "<b>No bet</b> (below MAO / not +EV)"
        right.markdown(
            '<div class="exec-strip" title="MAO = Minimum Acceptable Odds: the shortest price worth taking. Stake = how much to bet, sized to win the target profit (or Quarter-Kelly in syndicate mode).">'
            '<span>🛑 MAO: <b>bet ${:.2f} or better</b></span>'
            '<span>💵 Stake: {}</span></div>'.format(r["mao"], stake_txt),
            unsafe_allow_html=True)

        ctrl.checkbox("🩹 Scratch", key=key)
        _render_career_drawer(r, race)


# -----------------------------------------------------------------------------
# Sidebar
# -----------------------------------------------------------------------------
# Migrate any pre-existing racing.db to the current schema (adds jump_time,
# career_starts, user_bets) so a DB that persisted across a redeploy never
# crashes on a missing column before the next rebuild.
init_db(reset=False)
ensure_data()

with st.sidebar:
    st.markdown("## 🏇 {}".format(BRAND))
    st.caption("{} — live syndicate dashboard (Form King).".format(TAGLINE))
    if st.button("🔄 Rebuild live card", use_container_width=True,
                 help="Re-fetch the current card from the live Form King feed and re-price it."):
        try:
            rebuild_data()
            for k in [k for k in st.session_state if str(k).startswith(("scr_", "adj_"))]:
                del st.session_state[k]
            st.rerun()
        except Exception as exc:
            formking_client.LAST_FETCH_ERROR = str(exc)
            st.error("🔴 Live Form King Feed Error: {}".format(exc))
    if st.button("♻️ Reset scratchings & adjustments", use_container_width=True,
                 help="Clear every scratching you ticked and every manual score override, back to the model defaults."):
        for k in [k for k in st.session_state if str(k).startswith(("scr_", "adj_"))]:
            del st.session_state[k]
        st.rerun()
    st.divider()
    st.caption("⚙️ Staking, commission & surface drift now live in the **Settings** tab. "
               "Live Form King data — strict live-only, no mock fallback.")
    _mw = float(st.session_state.get("market_weight", DEFAULT_MARKET_WEIGHT))
    st.markdown('<span class="rec-chip hot">⚡ Active Blend: {:.0f}% Market / {:.0f}% Model</span>'.format(
        _mw * 100, (1 - _mw) * 100), unsafe_allow_html=True)
    st.caption("Market anchoring (Bayesian shrinkage) — tune it in **Settings**.")
    st.caption("🏗️ {}".format(BUILD_TAG))

render_bet_ledger()

# Non-fatal notice: some meetings' live fetch failed (e.g. a Form King 500) and
# were skipped. The rest of the card still renders — strict live-only, nothing
# fabricated — so one bad meeting can't black out the whole dashboard.
_skipped = getattr(formking_client, "SKIPPED_MEETINGS", [])
if _skipped:
    # Dedupe by track so a meeting listed under two ids (both failing) shows once.
    _seen, _names = set(), []
    for s in _skipped:
        nm = s.get("track") or s.get("id") or "?"
        if nm not in _seen:
            _seen.add(nm)
            _names.append(nm)
    st.warning("⚠️ {} meeting(s) temporarily unavailable from the live feed and skipped: {}. "
               "Showing the rest — press 🔄 Rebuild live card to retry them.".format(len(_names), ", ".join(_names)))

# --- Meeting selection (home screen) --------------------------------------
# The Race Cards tab opens as a list of meetings; clicking one sets
# sel_meeting_id and drills into it. Speed Map / Suggested Bets follow the
# selected meeting (falling back to the first while on the home screen).
all_meetings = load_meetings()
_sel_id = st.session_state.get("sel_meeting_id")
sel_meeting = next((m for m in all_meetings if m["meeting_id"] == _sel_id), None)
meeting = sel_meeting if sel_meeting is not None else all_meetings[0]
races = load_races(meeting["meeting_id"])


def _today_melb():
    """Today's date on the Melbourne clock (not the UTC server clock).

    Streamlit Cloud runs in UTC, which on a race morning is a day behind
    Melbourne (UTC+11), so a naive date.today() files today's live meetings
    under 'Tomorrow'. All race-day bucketing is anchored here instead, matching
    the jump clock (see CLAUDE.md: timing uses Australia/Melbourne)."""
    return datetime.datetime.now(MELBOURNE).date()


def _meeting_status(meeting_date):
    """Return (bucket, label, chip, verb) for a meeting relative to today."""
    today = _today_melb().isoformat()
    if not meeting_date:
        return ("today", "Racing today", "📡", "Open")
    if meeting_date < today:
        return ("past", "Completed", "🏁", "View results")
    if meeting_date == today:
        return ("today", "Racing today", "📡", "Open")
    days = (datetime.date.fromisoformat(meeting_date) - _today_melb()).days
    when = "Tomorrow" if days == 1 else "In {} days".format(days)
    return ("future", "Upcoming · " + when, "⏭", "Bet early")


def _fmt_date(meeting_date):
    try:
        return datetime.date.fromisoformat(meeting_date).strftime("%a %d %b")
    except Exception:
        return meeting_date or "today"


_STATE_BY_TRACK = {"Flemington": "VIC", "Caulfield": "VIC", "Moonee Valley": "VIC", "Sandown": "VIC",
                   "Rosehill": "NSW", "Randwick": "NSW", "Warwick Farm": "NSW", "Canterbury": "NSW",
                   "Eagle Farm": "QLD", "Doomben": "QLD", "Morphettville": "SA", "Ascot": "WA"}
_STATE_COLOR = {"VIC": "#1f6f4a", "NSW": "#1b5e8a", "QLD": "#8a2140", "SA": "#b4532a",
                "WA": "#b48a15", "AUS": "#334155"}


def _mins_to_jump(jump_ms):
    """Minutes from now (Melbourne clock) to a race jump time (epoch ms).
    Positive = upcoming, <=0 = already jumped. None when no jump time."""
    if not jump_ms:
        return None
    return (jump_ms - datetime.datetime.now(MELBOURNE).timestamp() * 1000) / 60000.0


def _race_clock(jump_ms, completed=False):
    """Human jump-clock label for a single race on the Melbourne clock."""
    mins = _mins_to_jump(jump_ms)
    if mins is None:
        return "—"
    if mins > 0:
        return "⏱️ {:.0f} min{} to jump".format(mins, "" if mins < 1.5 else "s")
    ago = -mins
    if completed or ago >= 60:
        return "🏁 COMPLETED" + ("" if not ago else " · {:.0f}m ago".format(ago))
    return "🏁 JUMPED · {:.0f}m ago".format(ago)


def _next_to_jump(m):
    """Real (race_number, mins_to_jump) for a meeting's soonest upcoming race from
    live jump times; mins<=0 means it has jumped. (1, None) when no live times."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT race_number, jump_time FROM races WHERE meeting_id=? AND jump_time IS NOT NULL "
            "ORDER BY jump_time", (m["meeting_id"],)).fetchall()
    finally:
        conn.close()
    if not rows:
        return (1, None)
    now_ms = datetime.datetime.now(MELBOURNE).timestamp() * 1000
    nxt = next((r for r in rows if r["jump_time"] > now_ms), rows[-1])
    return (nxt["race_number"], _mins_to_jump(nxt["jump_time"]))


def _meeting_row(m):
    state = _STATE_BY_TRACK.get(m["track_name"], "AUS")
    bkt = _meeting_status(m["meeting_date"])[0]
    nr, mins = _next_to_jump(m)
    if bkt == "today":
        if mins is None:
            txt = "R{}".format(nr)
        elif mins > 0:
            txt = "R{} &middot; {:.0f}m".format(nr, mins)
        elif -mins < 60:
            txt = "R{} &middot; 🏁 JUMPED".format(nr)
        else:
            txt = "🏁 COMPLETED"
        nj = ('<span style="background:rgba(255,106,26,.14);color:#ff8a3d;border:1px solid rgba(255,106,26,.42);'
              'padding:5px 11px;border-radius:9px;font-weight:700;font-family:var(--mono);font-size:.82rem">'
              '{}</span>'.format(txt))
    elif bkt == "future":
        nj = ('<span style="background:var(--surf2);color:var(--dim);border:1px solid var(--line);padding:5px 11px;'
              'border-radius:9px;font-weight:600;font-size:.8rem">Opens {}</span>'.format(_fmt_date(m["meeting_date"])))
    else:
        nj = ('<span style="background:var(--surf2);color:var(--dim);border:1px solid var(--line);padding:5px 11px;'
              'border-radius:9px;font-weight:600;font-size:.8rem">🏁 Finished</span>')
    with st.container(border=True):
        c1, c2 = st.columns([5, 1.1])
        c1.markdown(
            '<div style="display:flex;align-items:center;gap:13px">'
            '<div style="width:44px;height:44px;border-radius:50%;background:{col};display:flex;align-items:center;'
            'justify-content:center;font-weight:800;font-size:.78rem;color:#fff;flex:none;letter-spacing:.02em">{st}</div>'
            '<div style="flex:1;min-width:0"><div style="font-family:var(--disp);font-weight:700;font-size:1.05rem;'
            'color:var(--txt)">{track}</div><div style="color:var(--dim);font-size:.82rem">{races} races &middot; {cond} '
            '&middot; Rail {rail}</div></div><div>{nj}</div></div>'.format(
                col=_STATE_COLOR.get(state, "#334155"), st=state, track=m["track_name"],
                races=m["race_count"], cond=m["condition"], rail=m["rail_position"], nj=nj),
            unsafe_allow_html=True)
        if c2.button("Open →", key="open_m_{}".format(m["meeting_id"]), use_container_width=True):
            st.session_state["sel_meeting_id"] = m["meeting_id"]
            st.rerun()


def _date_head(ds):
    bkt = _meeting_status(ds)[0]
    return {"past": "🏁 {} — results & CLV", "today": "📡 {} — racing today",
            "future": "⏭ {} — early market, bet early"}[bkt].format(_fmt_date(ds))


def render_meeting_home(meetings):
    """Home screen: day tabs + month-calendar / prev-next date picker, then meeting rows."""
    st.markdown('<div class="tip-bar">👋 Welcome to <b>The Edge</b>. Pick a day (tabs, arrows or the '
                'calendar), then open a meeting for its full card. New here? The <b>📖 Guide &amp; Legend</b> '
                'tab explains every icon.</div>', unsafe_allow_html=True)
    if not meetings:
        st.info("No meetings available.")
        return
    today = _today_melb()
    today_iso = today.isoformat()
    all_dates = sorted({m["meeting_date"] for m in meetings})
    past = sorted([m for m in meetings if m["meeting_date"] < today_iso],
                  key=lambda m: m["meeting_date"], reverse=True)
    todayfut = [m for m in meetings if m["meeting_date"] >= today_iso]
    fut_dates = sorted({m["meeting_date"] for m in todayfut})

    def _tablabel(ds):
        d = datetime.date.fromisoformat(ds)
        delta = (d - today).days
        if delta == 0:
            return "📅 Today"
        if delta == 1:
            return "Tomorrow"
        return "{} {}".format(d.strftime("%a"), d.day)

    tab_defs = [("🏁 Results", "results", None), ("⏱ Next to Jump", "nextjump", None)]
    for ds in fut_dates:
        tab_defs.append((_tablabel(ds), "date", ds))
    labels = [t[0] for t in tab_defs]
    default = "📅 Today" if "📅 Today" in labels else labels[0]
    if st.session_state.get("home_tab") not in labels:
        st.session_state["home_tab"] = default
    if "home_cal" not in st.session_state:
        st.session_state["home_cal"] = (today if today_iso in all_dates
                                        else datetime.date.fromisoformat(all_dates[0]))

    # --- one source of truth: a date tab highlights the matching tab, any other
    # date (e.g. a past day) is shown via cal_override. Tabs, arrows and the
    # calendar all funnel through _select_date via callbacks. ---
    def _select_date(ds):
        lab = next((t[0] for t in tab_defs if t[1] == "date" and t[2] == ds), None)
        if lab:
            st.session_state["home_tab"] = lab
            st.session_state["cal_override"] = None
        else:
            st.session_state["cal_override"] = ds
        st.session_state["home_cal"] = datetime.date.fromisoformat(ds)

    def _active_date():
        ov = st.session_state.get("cal_override")
        if ov:
            return ov
        t = next((x for x in tab_defs if x[0] == st.session_state.get("home_tab", default)), None)
        if t and t[1] == "date":
            return t[2]
        return today_iso if today_iso in all_dates else all_dates[0]

    def _on_tab():
        st.session_state["cal_override"] = None
        t = next((x for x in tab_defs if x[0] == st.session_state.get("home_tab")), None)
        if t and t[1] == "date":
            st.session_state["home_cal"] = datetime.date.fromisoformat(t[2])

    def _on_cal():
        v = st.session_state.get("home_cal")
        if v:
            _select_date(v.isoformat())

    def _step(delta):
        cur = _active_date()
        i = all_dates.index(cur) if cur in all_dates else 0
        _select_date(all_dates[max(0, min(len(all_dates) - 1, i + delta))])

    def _go_today2():
        _select_date(today_iso if today_iso in all_dates else all_dates[0])

    st.pills("Race day", labels, key="home_tab", on_change=_on_tab,
             help="Results = completed meetings. Next to Jump = today & upcoming by jump time. "
                  "Or pick a race day — tabs, the ‹ › arrows or the calendar.")
    st.markdown('<div class="rc-sub" style="margin:2px 0 -6px">📅 Or jump to any date</div>',
                unsafe_allow_html=True)
    a1, a2, a3, a4 = st.columns([0.7, 3, 0.7, 1.4])
    a1.button("‹", on_click=_step, args=(-1,), use_container_width=True, help="Previous race day")
    a2.date_input("Jump to a date", key="home_cal", on_change=_on_cal, label_visibility="collapsed",
                  min_value=datetime.date.fromisoformat(all_dates[0]),
                  max_value=datetime.date.fromisoformat(all_dates[-1]))
    a3.button("›", on_click=_step, args=(1,), use_container_width=True, help="Next race day")
    a4.button("📅 Today", on_click=_go_today2, use_container_width=True)

    ov = st.session_state.get("cal_override")
    sel = next((t for t in tab_defs if t[0] == st.session_state.get("home_tab", default)), tab_defs[0])
    if ov:
        shown, head = [m for m in meetings if m["meeting_date"] == ov], _date_head(ov)
    elif sel[1] == "results":
        shown, head = past, "🏁 Results — completed meetings"
    elif sel[1] == "nextjump":
        shown = sorted(todayfut, key=lambda m: (m["meeting_date"],
                                                 _next_to_jump(m)[1] if _next_to_jump(m)[1] is not None else 9e9))
        head = "⏱ Next to Jump"
    else:
        shown, head = [m for m in meetings if m["meeting_date"] == sel[2]], _date_head(sel[2])

    st.markdown("### " + head)
    if not shown:
        st.info("No meetings on this date.")
        return
    for m in shown:
        _meeting_row(m)


# --- Settings values -------------------------------------------------------
# The controls themselves live in the Settings tab; their values persist in
# session_state, so we resolve them here (with defaults) before any tab that
# needs them renders. Changing a control triggers a rerun that picks up here.
stake_mode = st.session_state.get("stake_mode", STAKE_CONSUMER)
bankroll = float(st.session_state.get("bankroll", DEFAULT_BANKROLL) or DEFAULT_BANKROLL)
commission_rate = 0.10 if str(st.session_state.get("comm_choice", "")).startswith("10") else 0.08
apply_intraday = bool(st.session_state.get("apply_intraday", True))


def _short_class(name):
    if "Benchmark 84" in name:
        return "BM84"
    if "Maiden" in name:
        return "Maiden"
    return name


pill_labels = ["R{} — {}m {}{}".format(
                   r["race_number"], r["distance"], _short_class(r["class_name"]),
                   ("  ·  " + _race_clock(r["jump_time"], completed=bool(r["completed"]))) if r["jump_time"] else "")
               for r in races]
label_to_race = {lbl: races[i] for i, lbl in enumerate(pill_labels)}

_hdr = meeting["track_name"] if sel_meeting is not None else "Today's Meetings"
st.markdown('<div class="pie-title">🏇 {brand} — {track}</div><div class="pie-tag">{tag}</div>'.format(
    brand=BRAND, track=_hdr, tag=TAGLINE), unsafe_allow_html=True)

tab1, tab2, tab3, tab4, tabg, tabset = st.tabs([
    "📊 Race Cards & Overlays",
    "🏇 Realistic Speed Map",
    "🎯 Suggested Bets & Tracker",
    "🤖 AI Database Assistant",
    "📖 Guide & Legend",
    "⚙️ Settings",
])

with tabg:
    render_guide()

with tabset:
    st.markdown("### ⚙️ Settings")
    st.caption("Staking, commission and surface-drift controls. Changes apply instantly across every tab.")
    sc1, sc2 = st.columns(2)
    with sc1:
        st.radio("Staking mode", [STAKE_CONSUMER, STAKE_SYNDICATE], index=0, key="stake_mode",
                 help="Consumer = flat stake sized to win the target profit. "
                      "Syndicate = Quarter-Kelly staking off your bankroll.")
        if st.session_state.get("stake_mode") == STAKE_SYNDICATE:
            st.number_input("Bankroll ($)", min_value=100.0, value=DEFAULT_BANKROLL, step=100.0,
                            key="bankroll",
                            help="Total betting bank. Quarter-Kelly stakes are a fraction of this.")
    with sc2:
        st.radio("Commission", ["8% (default)", "10% (NSW)"], index=0, key="comm_choice",
                 help="Betting-exchange commission on winnings. It lowers your effective odds, "
                      "so value and MAO are calculated net of it.")
        st.checkbox("Apply intraday surface drift", value=True, key="apply_intraday",
                    help="Adjust ratings for the day's track pattern (e.g. a gutter favouring "
                         "wider lanes) detected from completed races.")
    st.markdown("#### ⚡ Market Anchoring (Bayesian Shrinkage)")
    mw = st.slider("Market Anchor Weight", min_value=0.50, max_value=0.85,
                   value=DEFAULT_MARKET_WEIGHT, step=0.05, key="market_weight",
                   help="Blends live market odds with model projections. 0.70 = 70% live market "
                        "consensus, 30% proprietary model. Eliminates unrealistic phantom overlays.")
    st.markdown('<span class="rec-chip hot">⚡ Active Blend: {:.0f}% Market / {:.0f}% Model</span>'.format(
        mw * 100, (1 - mw) * 100), unsafe_allow_html=True)
    st.caption("Every price is `my_price = 1 / p_blended`, where "
               "`p_blended = {:.0%}·market + {:.0%}·model`. The market is de-vigged (overround "
               "removed) before blending, so edges are grounded in live consensus.".format(mw, 1 - mw))
    st.divider()
    # Data source: locally generated mock cards, or the live Form King feed.
    if formking_client.is_live():
        err = getattr(formking_client, "LAST_FETCH_ERROR", None)
        if err:
            st.error("**Data source: LIVE requested — but the last fetch fell back to MOCK.**\n\n"
                     "Reason: `{}`\n\n"
                     "Check `FORMKING_API_KEY` (no stray spaces) and your Form King credits in "
                     "Streamlit secrets, then hit **Rebuild** in the sidebar.".format(err))
        else:
            st.success("**Data source: LIVE** — real cards from the Form King API. "
                       "Controlled by the `DATA_SOURCE` secret; the public repo defaults to mock.")
    else:
        st.info("**Data source: MOCK** — locally generated cards, no external API calls. "
                "To go live, set `DATA_SOURCE=\"live\"` and your Form King key in Streamlit "
                "secrets (see `.streamlit/secrets.toml.example`).")
    st.caption("Value & MAO use net-of-commission effective odds. Pricing re-normalises to 100% "
               "on every change.")


def _render_signals_box(rows, race, races, race_id, par, track_bias, mgr):
    """Right-hand 'Signals & Tools' panel: value overlays, AI Co-Pilot, custom rules —
    tucked beside the field so scrolling the main column shows the horses straight away."""
    with st.container(border=True):
        st.markdown('<div class="side-hdr">🛰️ Signals &amp; Tools</div>', unsafe_allow_html=True)

        overlays = [r for r in rows if r["overlay"]]
        if overlays:
            st.markdown('<div class="side-overlay">🔥 {} value overlay{}<br>{}</div>'.format(
                len(overlays), "" if len(overlays) == 1 else "s",
                "<br>".join("{} <b>+{:.0f}%</b>".format(r["horse_name"], r["edge"] * 100) for r in overlays)),
                unsafe_allow_html=True)
        else:
            st.caption("No live value overlays in this race right now.")

        with st.expander("🤖 AI Co-Pilot"):
            st.caption("Local situational analyst over this race's live context. No external API.")
            ctx = copilot.build_context(race, meeting, rows, par, track_bias)
            for i, prompt in enumerate(copilot.SAMPLE_PROMPTS[:3]):
                if st.button(prompt, key="cp{}".format(i), use_container_width=True):
                    st.session_state["copilot_q"] = prompt
            typed = st.text_input("Ask the co-pilot", key="copilot_text",
                                  placeholder="e.g. who suits a hot pace?")
            q = typed or st.session_state.get("copilot_q", "")
            if q:
                st.markdown(copilot.analyze(ctx, q))

        with st.expander("🧠 Custom rule"):
            st.caption("Plain English, e.g. “Bonus lanes 4–7 down the straight”, "
                       "“Penalise 3-wide no cover”, “Give leaders +1.5”.")
            rule_runners = [{"name": r["horse_name"], "lane": r.get("lane"), "barrier": r["barrier"],
                             "settle_zone": r.get("settle_zone"), "tactical_tag": r.get("tactical_tag"),
                             "weight": r["weight"], "prep_stage": r.get("prep_stage", ""),
                             "prep_run_num": r["prep_run_num"]} for r in rows if not r["scratched"]]
            rtext = st.text_input("Describe the rule", key="rule_text",
                                  placeholder="Bonus lanes 4-7 down the straight")
            if st.button("Propose rule", key="rule_propose", use_container_width=True,
                         help="The co-pilot reads your rule, picks the runners and calibrates the points.") and rtext.strip():
                st.session_state["rule_proposal"] = copilot.parse_rule_request(rtext, rule_runners)
                st.session_state["rule_tried"] = True
            if st.session_state.get("rule_tried"):
                prop = st.session_state.get("rule_proposal")
                if prop:
                    pc = "#34d27f" if prop["points"] >= 0 else "#ff9a8f"
                    st.markdown("**Proposed:** {}<br>**Points:** <span style='color:{}'><b>{:+.1f}</b></span>".format(
                        prop["description"], pc, prop["points"]), unsafe_allow_html=True)
                    st.markdown("**Targets ({}):** {}".format(
                        len(prop["targets"]), ", ".join(prop["targets"]) or "none in this race"))
                    sel = st.multiselect("Races for “Selected”",
                                         ["R{}".format(rc["race_number"]) for rc in races],
                                         default=["R{}".format(race["race_number"])], key="rule_sel")

                    def _mk(scope, ids):
                        return custom_rules.CustomRule(prop["description"], prop["points"],
                                                       prop["filter_type"], prop["filter_params"], scope, ids)
                    if st.button("Apply to This Race", key="scope_this", use_container_width=True):
                        mgr.add_rule(_mk(custom_rules.SCOPE_THIS, [race_id]))
                        st.session_state["rule_tried"] = False
                        st.rerun()
                    if st.button("Apply to Selected Races…", key="scope_sel", use_container_width=True):
                        ids = [rc["race_id"] for rc in races if "R{}".format(rc["race_number"]) in sel]
                        mgr.add_rule(_mk(custom_rules.SCOPE_SELECTED, ids or [race_id]))
                        st.session_state["rule_tried"] = False
                        st.rerun()
                    if st.button("Apply to Whole Meeting", key="scope_meet", use_container_width=True):
                        mgr.add_rule(_mk(custom_rules.SCOPE_MEETING, [rc["race_id"] for rc in races]))
                        st.session_state["rule_tried"] = False
                        st.rerun()
                else:
                    st.warning("Couldn't translate that. Try naming lanes (4–7), barriers, a tactical tag "
                               "(3WNC, box seat), weight (over 60kg), or a prep stage.")

        st.markdown('<div class="side-hdr" style="margin-top:6px">📋 Active Rules &amp; Biases</div>',
                    unsafe_allow_html=True)
        all_rules = mgr.all_rules()
        if not all_rules:
            st.caption("No custom rules yet — create one above and it applies instantly.")
        else:
            for rule in all_rules:
                col = "#34d27f" if rule.points >= 0 else "#ff9a8f"
                st.markdown("<span class='ruleitem'>{desc} <b style='color:{c}'>{p:+.1f}</b> · {scope}</span>".format(
                    desc=rule.description.split(" (")[0], c=col, p=rule.points, scope=rule.scope_label()),
                    unsafe_allow_html=True)
                if st.button("❌ Remove", key="rm_" + rule.rule_id, use_container_width=True):
                    mgr.remove_rule(rule.rule_id)
                    st.rerun()
            if st.button("🗑️ Clear all rules", key="clear_rules", use_container_width=True):
                mgr.clear_all_rules()
                st.rerun()


def _render_field(rows, race, race_id, cloth):
    """Main column: view/filter controls and the runner cards (or worksheet)."""
    vm1, vm2 = st.columns([2, 2])
    with vm1:
        view_mode = st.pills("View Mode", ["🃏 Visual Cards", "📊 Rating Worksheet"],
                             default="🃏 Visual Cards", selection_mode="single", key="view_mode",
                             help="Visual Cards = one rich card per runner. Rating Worksheet = a compact "
                                  "sortable table of every runner's numbers.") or "🃏 Visual Cards"
    with vm2:
        flt = st.pills("Filter", ["All Runners", "🔥 Value Overlays (+EV)", "Top Rated"],
                       default="All Runners", selection_mode="single", key="flt_{}".format(race_id),
                       help="Narrow the field: all runners, only positive-value overlays, or the top-rated "
                            "runners by model score.") or "All Runners"

    if flt.startswith("🔥"):
        shown = [r for r in rows if r["overlay"]]
    elif flt == "Top Rated":
        shown = sorted([r for r in rows if not r["scratched"]], key=lambda r: -(r["projected"] or 0))
    else:
        shown = rows

    if not shown:
        st.info("No runners match this filter.")
    elif view_mode.endswith("Worksheet"):
        render_worksheet(shown, race, cloth)
    else:
        for r in shown:
            render_runner_card(r, race, cloth)
            if not r.get("scratched"):
                render_bet_slip(r, race)


# -----------------------------------------------------------------------------
# Tab 1
# -----------------------------------------------------------------------------
def render_race_view():
    st.markdown('<div class="meet-head">🏇 <b>{track}</b> &middot; {date} &middot; {cond} &middot; '
                'Rail {rail}</div>'.format(track=meeting["track_name"],
                date=_fmt_date(meeting["meeting_date"]), cond=meeting["condition"],
                rail=meeting["rail_position"]), unsafe_allow_html=True)

    _bkt, _lbl, _chip, _verb = _meeting_status(meeting["meeting_date"])
    if _bkt == "past":
        st.markdown('<div class="tip-bar" style="border-left-color:#8b93a3">🏁 <b>Completed meeting</b> '
                    '({}) — these races have been run; official results &amp; CLV are in the '
                    '<b>Official Results</b> panel on each race below.</div>'.format(_fmt_date(meeting["meeting_date"])),
                    unsafe_allow_html=True)
    elif _bkt == "future":
        st.markdown('<div class="intraday-banner">⏭ <b>Upcoming meeting — early market</b> ({}). '
                    'Bet early: prices will keep firming closer to the jump.</div>'.format(
                        _fmt_date(meeting["meeting_date"])), unsafe_allow_html=True)

    chosen = st.pills("Race", pill_labels, default=pill_labels[0],
                      selection_mode="single", key="race_pill",
                      help="Pick a race on the card. Each pill shows race number, distance and class.") or pill_labels[0]
    race = label_to_race[chosen]
    race_id = race["race_id"]
    par = par_for(race["class_name"])

    entries = load_entries(race_id)
    cloth = saddlecloths(entries)
    scratched_names = scratched_for(race_id, entries)
    active_entries = [e for e in entries if e["horse_name"] not in set(scratched_names)]

    env = build_env(meeting, race, active_entries, commission_rate, stake_mode, bankroll, apply_intraday)
    wind = env["wind"]
    rail_prof = track_rail_profiles.profile_for(meeting["track_name"], meeting["rail_position"])

    # Pre-race historical prior (#1): how this track plays on today's going, from
    # the whole card's past runs here. Shared into env so the per-runner barrier
    # nudge in evaluate_race uses the same read.
    # Defensive: the prior is a non-critical enhancement, so a bad data edge case
    # (or a stale module during a soft redeploy) must never crash the race view.
    hist_bias = {"available": False, "n": 0}
    if hasattr(track_rail_profiles, "get_historical_track_bias"):
        _conn = get_connection()
        try:
            hist_bias = track_rail_profiles.get_historical_track_bias(
                _conn, meeting["track_name"], meeting["condition"])
        except Exception:
            hist_bias = {"available": False, "n": 0}
        finally:
            _conn.close()
    env["hist_bias"] = hist_bias
    _hn = hist_bias.get("n", 0)
    if hist_bias.get("available"):
        prior_chip = ("<span class=\"cond-chip prior-chip\" title=\"Historical prior from the card's "
                      "past runs at this track on today's going (n={n}). IV&gt;1 = that barrier group "
                      "wins more than its share.\">🏛️ PRE-RACE PRIOR: {txt}</span>").format(
                          n=_hn, txt=hist_bias["assessment"])
    else:
        # Below the sample threshold — show the "gathering" state with the sample
        # size (also tells us at a glance if the track match is finding runs).
        prior_chip = ("<span class=\"cond-chip\" title=\"Not enough same-going history at this track "
                      "yet to call a prior (need {m}).\">🏛️ Track prior: building (n={n})</span>").format(
                          m=getattr(track_rail_profiles, "MIN_SAMPLE", 20), n=_hn)

    st.markdown(
        '<div class="cond-strip">'
        '<span class="cond-chip">🏟️ {track}</span><span class="cond-chip">📏 {dist} m</span>'
        '<span class="cond-chip">🛤️ Rail: {rail}</span><span class="cond-chip">🌤️ {cond}</span>'
        '<span class="cond-chip cond-par">🎯 Par: {par:.1f}</span>'
        '<span class="cond-chip pace-chip">{tempo}</span>'
        '<span class="cond-chip wind-chip">🧭 Wind {wfrom} · {wlabel}{wlive}</span>{prior}</div>'
        '<div class="rc-sub" style="margin-top:-2px">Rail profile: {railnote} · '
        'Commission {comm:.0f}% (net-of-commission pricing)</div>'.format(
            track=meeting["track_name"], dist=race["distance"], rail=meeting["rail_position"],
            cond=meeting["condition"], par=par, tempo=env["tempo_badge"],
            wfrom=wind["from_point"], wlabel=wind["label"],
            wlive=" 📡 BOM" if wind.get("live") else "", railnote=rail_prof["note"],
            prior=prior_chip, comm=commission_rate * 100),
        unsafe_allow_html=True)

    if env["gutter"]:
        st.markdown('<div class="intraday-banner">⚡ Intraday Surface Drift Applied '
                    '(Lanes 4+ Advantaged) — Gutter Pattern detected from completed races</div>',
                    unsafe_allow_html=True)

    geom_tp = geometry_for(meeting["track_name"], race["distance"])
    play = track_play_engine.analyze_track_play(
        meeting["track_name"], meeting["rail_position"], wind, race["distance"])
    first_turn = ("~{:.0f}m to the first turn".format(geom_tp["run_to_turn_m"])
                  if geom_tp.get("run_to_turn_m") else "straight course — no turn")
    with st.expander("📐 How {} plays today — {} · {}".format(
            meeting["track_name"], play["headline"], first_turn)):
        lean_cls = "edge-pos" if play["pace"] > 0 else "edge-gone" if play["pace"] < 0 else "edge-neg"
        st.markdown(
            '<div style="margin-bottom:6px"><span class="edge-badge {lc}" style="display:inline-block;margin:0">'
            '{hl}</span> &nbsp;<span style="color:var(--dim)">Likely to suit:</span> <b>{lean}</b></div>'
            '<div class="play-row">🛤️ <b>Rail:</b> {rail}</div>'
            '<div class="play-row">🧭 <b>Wind:</b> {wind}</div>'
            '<div class="play-row">📐 <b>Course:</b> {course}</div>'
            '<div class="play-row" style="color:var(--orange-2)">📈 <b>History:</b> {hist}</div>'.format(
                lc=lean_cls, hl=play["headline"], lean=play["lean"], rail=play["rail_note"],
                wind=play["wind_note"], course=geom_tp["label"], hist=play["history"]),
            unsafe_allow_html=True)
        st.caption("Mock historical read synthesised from the rail position and the day's wind — "
                   "no external data (see project rules).")

    hb1, hb2 = st.columns([3, 1])
    with hb1:
        bias_label = st.pills("Track Bias", BIAS_OPTIONS, default=BIAS_OPTIONS[0],
                              selection_mode="single", key="bias_pill",
                              help="Tell the model how the track is racing — e.g. favouring on-pace runners or "
                                   "wide barriers — and ratings tilt accordingly.") or BIAS_OPTIONS[0]
    with hb2:
        st.caption("Prices: Form King, as of the last rebuild.")
    track_bias = BIAS_MAP[bias_label]

    rows = evaluate_race(entries, scratched_names, race, meeting, race_markets(race_id),
                         track_bias, rule_manager(), env)
    mgr = rule_manager()

    # Data-quality note: how many runners' speed-map positions are read from
    # real in-run form (settling positions) vs the debutant fallback.
    _nrow = [r for r in rows if not r.get("scratched")]
    _nlive = sum(1 for r in _nrow if r.get("es_live"))
    st.caption("📡 Speed map: {}/{} runners positioned from real in-run form "
               "(the rest are first-starters / unexposed).".format(_nlive, len(_nrow)))

    main_col, side_col = st.columns([3.7, 1], gap="medium")
    with side_col:
        _render_signals_box(rows, race, races, race_id, par, track_bias, mgr)
    with main_col:
        _render_field(rows, race, race_id, cloth)

    # Exotic fair dividends (no tote comparison: the feed has no tote pools)
    with st.expander("🎲 Exotic fair dividends (Exacta & Trifecta)"):
        active_rows = [r for r in rows if not r["scratched"] and r["disp_fair"]]
        if len(active_rows) >= 3:
            probs = {r["entry_id"]: 1.0 / r["disp_fair"] for r in active_rows}
            tot = sum(probs.values())
            probs = {k: v / tot for k, v in probs.items()}
            names = {r["entry_id"]: r["horse_name"] for r in active_rows}
            ex, tri = exotics_engine.fair_exotics(probs, names)
            st.caption("Fair dividends from the 100% win model via the Harville method. Compare them "
                       "to the live tote yourself: a combination paying well over fair is value.")
            st.markdown("**Most likely exactas**")
            st.dataframe(pd.DataFrame([{"Combination": " → ".join(e["combo"]), "Fair $": e["fair"]}
                                       for e in ex]), use_container_width=True, hide_index=True)
            st.markdown("**Most likely trifectas**")
            st.dataframe(pd.DataFrame([{"Combination": " → ".join(t["combo"]), "Fair $": t["fair"]}
                                       for t in tri]), use_container_width=True, hide_index=True)
        else:
            st.info("Need at least three active runners to price exotics.")

    # Official results & CLV reconciliation (completed races)
    if race["completed"]:
        with st.expander("🏁 Official Results & CLV Reconciliation", expanded=False):
            conn = get_connection()
            try:
                res = conn.execute(
                    "SELECT horse_name, finish_pos, beaten_lengths, official_time, result_bsp, "
                    "market_odds, fair_odds, score_0_to_100 FROM race_entries "
                    "WHERE race_id=? AND finish_pos IS NOT NULL ORDER BY finish_pos", (race_id,)).fetchall()
                meta = conn.execute("SELECT benchmark_par_time, actual_win_time, tsv FROM races "
                                    "WHERE race_id=?", (race_id,)).fetchone()
            finally:
                conn.close()
            if meta:
                st.caption("Winning time {:.2f}s vs par {:.2f}s → TSV {:+.2f}s ({}).".format(
                    meta["actual_win_time"], meta["benchmark_par_time"], meta["tsv"],
                    "slow/tough" if meta["tsv"] > 0 else "fast/slick"))
            res_df = pd.DataFrame([{
                "Pos": r["finish_pos"], "Horse": r["horse_name"],
                "Beaten (L)": r["beaten_lengths"], "Time (s)": r["official_time"],
                "Proj Score": r["score_0_to_100"], "Taken $": r["market_odds"],
                "Fair $": r["fair_odds"], "BSP $": r["result_bsp"],
                "CLV %": round((r["market_odds"] / r["result_bsp"] - 1.0) * 100, 1) if r["result_bsp"] else None,
            } for r in res])
            st.dataframe(res_df, use_container_width=True, hide_index=True)
            st.caption("CLV% = how the pre-race taken price compares to the Betfair Starting Price (BSP).")


# Race Cards tab: meeting-list home screen, or the drilled-in race view.
with tab1:
    if sel_meeting is None:
        render_meeting_home(all_meetings)
    else:
        if st.button("← All meetings", key="back_to_meetings"):
            st.session_state.pop("sel_meeting_id", None)
            st.rerun()
        render_race_view()


# -----------------------------------------------------------------------------
# Tab 2
# -----------------------------------------------------------------------------
with tab2:
    chosen2 = st.pills("Race", pill_labels, default=pill_labels[0],
                       selection_mode="single", key="race_pill_sm",
                       help="Pick the race to map.") or pill_labels[0]
    race2 = label_to_race[chosen2]
    geom = geometry_for(meeting["track_name"], race2["distance"])
    all2 = load_entries(race2["race_id"])
    cloth2 = saddlecloths(all2)
    sm_scratched = set(scratched_for(race2["race_id"], all2))
    entries2 = [{**e, "scratched": False} for e in all2 if e["horse_name"] not in sm_scratched]

    tac = speedmap_engine.build_tactical_map(entries2, geom)
    tmap = tac["runners"]

    # "Next to jump" — this meeting's races at a glance.
    jump_bits = []
    for i, rc in enumerate(races):
        mins = i * 32
        tag = "🟢 NEXT" if rc["race_id"] == race2["race_id"] else "+{}m".format(mins) if mins else "NOW"
        jump_bits.append('<span class="cond-chip{hot}">R{n} · {d}m · {tag}</span>'.format(
            hot=" cond-par" if rc["race_id"] == race2["race_id"] else "",
            n=rc["race_number"], d=rc["distance"], tag=tag))
    st.markdown('<div class="rc-sub" style="margin-bottom:2px">⏱ Next to jump at {}</div>'
                '<div class="cond-strip">{}</div>'.format(meeting["track_name"], "".join(jump_bits)),
                unsafe_allow_html=True)

    duel, leaders = tac["duel"], tac["leaders"]
    td = geom.get("turn_direction")
    if td == "straight":
        geo_txt = "a straight course — no turn"
    else:
        dirw = "clockwise (NSW/QLD)" if td == "right" else "anti-clockwise (VIC/SA/WA/TAS)"
        geo_txt = "{}, first turn ~{:.0f}m after the jump".format(dirw, geom.get("run_to_turn_m") or 0)
    st.caption("Press ▶ Play (or drag the scrubber) to watch the field settle and swing around the bend — {}. "
               "Each runner carries its silks, saddlecloth number and name; orange ring = value overlay.".format(geo_txt))
    components.html(build_speedmap_component(entries2, cloth2, geom, tmap), height=660, scrolling=False)

    lc1, lc2 = st.columns(2)
    lc1.markdown("🟠 **Value overlay** (orange ring)")
    lc2.markdown("🔴 **Contested speed duel** (3+ leaders)")
    if duel:
        st.warning("Suicidal early pressure projected — leaders may over-race: " + ", ".join(sorted(leaders)))

    st.markdown("#### Silks &amp; Jockeys")
    cloth2 = saddlecloths(entries2)
    silk_cells = []
    for e in sorted(entries2, key=lambda x: cloth2[x["horse_name"]]):
        name = e["horse_name"]
        t = tmap.get(name, {})
        silk_cells.append(
            '<div style="display:flex;align-items:center;gap:9px;padding:7px 10px;border:1px solid var(--line);'
            'border-radius:10px;min-width:210px;background:var(--surf)">'
            '<img src="{silk}" width="40" height="40" style="border:1px solid var(--line);border-radius:7px;background:var(--surf2)"/>'
            '<div style="font-size:0.8rem;line-height:1.3"><b style="color:var(--txt)">{num}. {name}</b><br>'
            '<span style="color:var(--dim)">{jky} · Bar {bar}</span><br>'
            '<span style="color:var(--orange-2);font-weight:600">{tag}</span></div></div>'.format(
                silk=silks_engine.silk_data_uri(name), num=cloth2[name], name=name,
                jky=silks_engine.jockey_for(name), bar=e["barrier"], tag=t.get("tag_blurb", "-")))
    st.markdown('<div style="display:flex;flex-wrap:wrap;gap:8px">' + "".join(silk_cells) + "</div>",
                unsafe_allow_html=True)
    st.caption("Marker borders on the map above use each runner's primary silk colour; hover a "
               "token for jockey, barrier, lane and tactical tag.")

    st.markdown("#### Tactical Settling Summary")
    sum_rows = []
    for e in sorted(entries2, key=lambda x: tmap.get(x["horse_name"], {}).get("rank", 99)):
        t = tmap.get(e["horse_name"], {})
        sum_rows.append({
            "#": cloth2[e["horse_name"]], "Horse": e["horse_name"], "Barrier": e["barrier"],
            "Settle Zone": t.get("zone", "-"), "Settling Lane": t.get("lane_name", "-"),
            "Tactical Tag": t.get("tag_blurb", "-"), "Early Speed (0-10)": t.get("early_speed"),
        })
    st.dataframe(pd.DataFrame(sum_rows), use_container_width=True, hide_index=True)


# -----------------------------------------------------------------------------
# Tab 3 — Suggested Bets & Performance Tracker
# -----------------------------------------------------------------------------
with tab3:
    st.markdown("### 🎯 Active / Pending Bets Today")
    st.caption("Qualified suggestions: Edge ≥ 15% (live ≥ MAO) · Projected within ±1.5 of Par · "
               "$2.20–$18.00 · trend > −1.0.")

    bias = current_bias()
    suggested = []
    for rc in races:
        ents = load_entries(rc["race_id"])
        scr = scratched_for(rc["race_id"], ents)
        active = [e for e in ents if e["horse_name"] not in set(scr)]
        env_rc = build_env(meeting, rc, active, commission_rate, stake_mode, bankroll, apply_intraday)
        for row in evaluate_race(ents, scr, rc, meeting, race_markets(rc["race_id"]), bias,
                                 rule_manager(), env_rc):
            if is_suggested(row):
                suggested.append((rc, row))

    if suggested:
        sug_df = pd.DataFrame([{
            "Race": "R{}".format(rc["race_number"]), "Horse": row["horse_name"],
            "Stake $": round(row["stake_dollars"], 2), "Live $": row["market"],
            "Fair $": row["disp_fair"], "Edge %": round(row["edge"] * 100, 1), "MAO $": row["mao"],
            "Proj (Δ Par)": "{:.1f} ({:+.1f})".format(row["projected"], row["par_delta"]),
            "Fluc": row["fluc_string"], "Sentiment": row["sentiment_label"],
        } for rc, row in suggested])
        st.dataframe(sug_df, use_container_width=True, hide_index=True)
        st.caption("{} qualified suggestion(s). Stakes sized to win ${:.0f}.".format(len(suggested), TARGET_PROFIT))
    else:
        st.info("No runners currently qualify on the current prices. Try a track-bias setting, or Rebuild for fresh prices.")

    st.divider()
    st.markdown("### 📒 Settled Bets & Audit Ledger")
    conn = get_connection()
    try:
        bets = conn.execute(
            """
            SELECT r.race_number AS Race, e.horse_name AS Horse, b.stake_dollars AS "Stake $",
                   b.taken_price AS Taken, b.fair_price AS Fair, b.bsp AS BSP,
                   b.clv_percent AS "CLV %", b.result AS Result, b.profit_units AS "P/L $"
            FROM bets_ledger b
            JOIN race_entries e ON e.entry_id = b.entry_id
            JOIN races r ON r.race_id = e.race_id ORDER BY b.bet_id
            """).fetchall()
    finally:
        conn.close()

    graded = [b for b in bets if b["Result"] in ("WIN", "LOSS")]
    wins = sum(1 for b in graded if b["Result"] == "WIN")
    staked = sum(b["Stake $"] for b in graded)
    pl = sum(b["P/L $"] for b in graded)
    clvs = [b["CLV %"] for b in graded if b["CLV %"] is not None]
    avg_clv = sum(clvs) / len(clvs) if clvs else 0.0
    beat = (sum(1 for c in clvs if c > 0) / len(clvs) * 100) if clvs else 0.0

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Strike Rate", "{:.1f}%".format(wins / len(graded) * 100 if graded else 0),
              help="Share of settled bets that won.")
    m2.metric("Total Staked", "${:,.0f}".format(staked),
              help="Total dollars outlaid across all settled bets.")
    m3.metric("P/L", "${:+,.0f}".format(pl),
              help="Net profit or loss in dollars after settlement.")
    m4.metric("ROI", "{:+.1f}%".format(pl / staked * 100 if staked else 0),
              help="Return on investment — profit as a percentage of total staked.")
    m5.metric("Avg CLV", "{:+.2f}%".format(avg_clv),
              help="Average Closing Line Value — how your taken prices compared to the Betfair SP. "
                   "Positive and consistent CLV is the key long-term edge signal. CLV beat rate {:.0f}%.".format(beat))

    st.dataframe(pd.DataFrame([dict(b) for b in bets]), use_container_width=True, hide_index=True)
    st.caption("To-Win-$100 staking. Results come only from official Form King results; "
               "CLV beat rate = share of bets whose taken price beat the BSP.")


# -----------------------------------------------------------------------------
# Tab 4
# -----------------------------------------------------------------------------
with tab4:
    import nl_sql

    st.markdown("Ask in plain English, or edit the generated SQL. Queries run "
                "**read-only** against `racing.db`.")
    sample = st.selectbox("Sample questions", ["(type your own below)"] + nl_sql.SAMPLE_QUESTIONS,
                          help="Pick a ready-made question to see what you can ask, or choose the first "
                               "option and type your own below.")
    default_q = "" if sample.startswith("(") else sample
    question = st.text_input("Your question", value=default_q,
                             placeholder="e.g. Find all 3rd-up runners with score > 70",
                             help="Ask about the data in plain English — it is turned into read-only SQL "
                                  "you can inspect before the results show.")
    if st.button("Run query", type="primary",
                 help="Translate your question to SQL and run it read-only against the mock database."):
        try:
            sql = nl_sql.generate_sql(question)
            st.code(sql, language="sql")
            cols, data = nl_sql.run_query(sql)
            if data:
                st.dataframe(pd.DataFrame(data, columns=cols), use_container_width=True, hide_index=True)
                st.caption("{} row(s).".format(len(data)))
            else:
                st.info("Query ran successfully but returned no rows.")
        except Exception as exc:
            st.error("Could not run that query: {}".format(exc))
