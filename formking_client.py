"""Form King API client for The Edge — PIE (Phase 4, live data).

This is the ONLY module that talks to Form King. Everything downstream (the
rating model, pricing book, staking, ledger, speed map) runs off racing.db, so
this client's single job is to fetch the real card and return it in the exact
shape that ingest.ingest_meeting() expects — identical to
mock_data_generator.generate_meetings():

    {"meeting": {track_id, track_name, rail_position, condition,
                 track_variant, meeting_date},
     "races":   [{race_number, distance, class_name, pace_pressure_index,
                  "entries": [{horse_name, barrier, weight, prep_run_num,
                               wfa_rating, market_odds}, ...]}, ...]}

Secrets & config are read from st.secrets when running under Streamlit, and
from environment variables otherwise (env wins, so a local shell or CI can
override). The API key is NEVER hard-coded or committed; see
.streamlit/secrets.toml.example.

Data source is chosen by DATA_SOURCE ("mock" default, or "live"). In "mock"
mode this module makes no outbound calls at all, preserving the Phase 1-3
contract in CLAUDE.md for anyone who has not configured a key.

Credit cost: /b2c/meetings/upcoming is 1 credit and lists every meeting, but
the per-runner detail (weight, odds, run-this-prep, benchmark) lives in
/b2c/meetings/{id} at 5 credits each. So a live refresh costs
1 + 5 * (meetings enriched). FORMKING_MAX_MEETINGS caps that count.
"""

import datetime
import os

import requests

# Reason the most recent live fetch fell back to mock (None when live succeeded
# or mock is the configured source). ingest.load_meetings() sets it; the app's
# Settings badge reads it so a failed live pull is diagnosable, not silent.
LAST_FETCH_ERROR = None

_TIMEOUT = 25                       # per-request network timeout (seconds)
_UPCOMING_PATH = "/b2c/meetings/upcoming"
_SUMMARY_PATH = "/b2c/meetings/{meeting_id}"   # full races + runners (5 credits)
_DEFAULT_MAX_MEETINGS = 4           # keep live refreshes cheap by default
_DEFAULT_WEIGHT = 58.0              # fallback carried weight (kg) if absent


# --- config / secrets --------------------------------------------------------
def _cfg(name, default=None):
    """Resolve a config value: env var first, then st.secrets, then default."""
    if name in os.environ:
        return os.environ[name]
    try:
        import streamlit as st
        # st.secrets raises if no secrets file exists; guard the whole access.
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return default


def data_source():
    """Return "live" or "mock" (default). Mock makes no outbound calls."""
    return str(_cfg("DATA_SOURCE", "mock")).strip().lower()


def is_live():
    return data_source() == "live"


def _require(name):
    val = _cfg(name)
    if not val:
        raise RuntimeError(
            f"{name} is not set. Add it to .streamlit/secrets.toml (see "
            ".streamlit/secrets.toml.example) before using DATA_SOURCE=live."
        )
    return val


def _session():
    """A requests session carrying the Form King auth header (x-api-key)."""
    s = requests.Session()
    header = _cfg("FORMKING_AUTH_HEADER", "x-api-key")
    s.headers.update({header: _require("FORMKING_API_KEY"), "Accept": "application/json"})
    return s


def _get(session, path, **params):
    """GET BASE_URL + path, return parsed JSON, raising on any HTTP error."""
    base = _require("FORMKING_BASE_URL").rstrip("/")
    resp = session.get(base + path, params=params or None, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# --- field helpers -----------------------------------------------------------
def _date_str(epoch_ms):
    """Form King dates are epoch milliseconds -> 'YYYY-MM-DD' (UTC)."""
    if not epoch_ms:
        return None
    return datetime.datetime.utcfromtimestamp(epoch_ms / 1000).strftime("%Y-%m-%d")


def _condition(going, going_number):
    """'Good' + 3 -> 'Good 3' (matches the app's condition format)."""
    if not going:
        return None
    return f"{going} {going_number}".strip() if going_number is not None else str(going)


def _rail(rail_position, rail_metres):
    """Format rail as '+3m' when moved out, else the position text ('True')."""
    try:
        if rail_metres and float(rail_metres) > 0:
            return "+{:g}m".format(float(rail_metres))
    except (TypeError, ValueError):
        pass
    return rail_position


def _class_name(restrictions, race_name):
    """Derive a class_name the model's BENCHMARK_PAR table can grade.

    Form King encodes grade in `restrictions` (the token before the first dot):
    'MDN...' maiden, 'C1...' class 1, '64+...' benchmark 64, 'OPEN...', 'G1...'.
    Falls back to the human race name when the code is unfamiliar.
    """
    code = (restrictions or "").split(".")[0].strip().upper()
    if code.startswith("MDN"):
        return "Maiden"
    if code in ("G1", "GRP1"):
        return "Group 1"
    if code in ("G2", "GRP2"):
        return "Group 2"
    if code in ("G3", "GRP3"):
        return "Group 3"
    if code in ("LR", "LISTED"):
        return "Listed"
    if code.startswith("OPEN") or code == "WFA":
        return "Open"
    if code.startswith("C") and code[1:2].isdigit():
        return "Class " + code[1:].rstrip("+")
    digits = code.rstrip("+")
    if digits.isdigit():                      # e.g. '64+' -> 'Benchmark 64'
        return "Benchmark " + digits
    return race_name or restrictions or "Race"


def _odds(entry):
    """Current market price: average now, else best now, else opening."""
    o = entry.get("odds") or {}
    return o.get("avgNow") or o.get("bestNow") or o.get("avgOpen")


def _weight(entry):
    """Carried weight (kg). Prefer weightCarried, then allocated weight."""
    for key in ("weightCarried", "weight", "ridingWeight"):
        val = entry.get(key)
        if val:
            return float(val)
    return _DEFAULT_WEIGHT


# --- mapping: Form King JSON -> ingest shape ---------------------------------
def _map_entry(entry):
    """One runner -> ingest entry dict, or None if scratched/no name."""
    if entry.get("scratched"):
        return None
    horse = entry.get("horse") or {}
    name = horse.get("name")
    if not name:
        return None
    # A runner with no market price can't be priced against the book, so skip it
    # (the model, like the mock card, assumes every runner carries market_odds).
    odds = _odds(entry)
    if odds is None:
        return None
    prep = entry.get("raceInPrep")
    return {
        "horse_name":   name,
        "barrier":      int(entry.get("barrier") or 0),
        "weight":       _weight(entry),
        "prep_run_num": int(prep) if prep else 1,
        "wfa_rating":   entry.get("benchmarkRating"),
        "market_odds":  odds,
    }


def _map_race(race):
    """One race (+ its runners) -> ingest race dict."""
    entries = [m for m in (_map_entry(e) for e in race.get("entries", [])) if m]
    return {
        "race_number":         int(race.get("number") or 0),
        "distance":            int(race.get("distance") or 0),
        "class_name":          _class_name(race.get("restrictions"), race.get("name")),
        "pace_pressure_index": None,   # not supplied; the model derives tempo from the map
        "entries":             entries,
    }


def _map_meeting(summary):
    """A /b2c/meetings/{id} summary -> one ingest-shaped meeting dict."""
    meeting = {
        "track_id":      summary.get("id"),
        "track_name":    summary.get("trackName"),
        "rail_position": _rail(summary.get("railPosition"), summary.get("railMetres")),
        "condition":     _condition(summary.get("going"), summary.get("goingNumber")),
        "track_variant": None,
        "meeting_date":  _date_str(summary.get("date")),
    }
    races = [_map_race(r) for r in summary.get("races", [])]
    # Drop races with no live runners so the book is never built on an empty field.
    races = [r for r in races if r["entries"]]
    return {"meeting": meeting, "races": races}


# --- public entry point ------------------------------------------------------
def fetch_live_meetings(max_meetings=None):
    """Fetch the live card from Form King and return ingest-shaped meetings.

    Lists upcoming meetings (1 credit), then pulls the full summary (5 credits)
    for up to max_meetings of them — TAB meetings first, soonest first — so the
    dashboard shows real weights, odds, prep runs and benchmarks. Raises
    RuntimeError if config is missing and requests.HTTPError on an API error;
    ingest.load_meetings() catches those and falls back to mock data.
    """
    if max_meetings is None:
        max_meetings = int(_cfg("FORMKING_MAX_MEETINGS", _DEFAULT_MAX_MEETINGS))

    session = _session()
    upcoming = _get(session, _UPCOMING_PATH)
    if isinstance(upcoming, dict):               # tolerate {"meetings": [...]}
        upcoming = upcoming.get("meetings", [])

    # TAB meetings first, then by date (soonest first), to spend credits well.
    upcoming.sort(key=lambda m: (not m.get("tabMeeting", False), m.get("date") or 0))

    out = []
    for m in upcoming[:max_meetings]:
        mid = m.get("id")
        if not mid:
            continue
        summary = _get(session, _SUMMARY_PATH.format(meeting_id=mid))
        mapped = _map_meeting(summary)
        if mapped["races"]:
            out.append(mapped)
    return out
