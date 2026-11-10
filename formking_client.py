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

# Meetings whose summary fetch failed on the most recent live pull. Each item is
# {"id", "track", "error"}. The ingest skips these (never fabricating them) and
# the app surfaces them as a non-fatal notice, so one meeting's feed error can't
# black out the whole card. Reset at the start of every fetch_live_meetings().
SKIPPED_MEETINGS = []

_TIMEOUT = 25                       # per-request network timeout (seconds)
_UPCOMING_PATH = "/b2c/meetings/upcoming"
_SUMMARY_PATH = "/b2c/meetings/{meeting_id}"   # full races + runners (5 credits)
_DEFAULT_MAX_MEETINGS = 0           # 0 = load every upcoming meeting (no cap)
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
def _as_int(val):
    """int(val) when it's a usable number, else None (tolerates feed nulls/strings)."""
    try:
        return int(val) if val is not None and str(val) != "" else None
    except (TypeError, ValueError):
        return None


def _as_float(val):
    """float(val) when usable, else None."""
    try:
        return float(val) if val is not None and str(val) != "" else None
    except (TypeError, ValueError):
        return None


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
    return rail_position or "True"


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
    """Current market price: average now, else best now, else opening.

    Once a race has been run the live market is gone, so the starting price is
    the market. Without this an old or picnic meeting comes back with no priced
    runners at all and never reaches the review.
    """
    o = entry.get("odds") or {}
    live = o.get("avgNow") or o.get("bestNow") or o.get("avgOpen")
    if live:
        return live
    r = entry.get("horseResult") or {}
    return _as_float(r.get("startingPrice")) or _as_float(r.get("betfairStartingPrice"))


def _weight(entry):
    """Carried weight (kg). Prefer weightCarried, then allocated weight."""
    for key in ("weightCarried", "weight", "ridingWeight"):
        val = entry.get(key)
        if val:
            return float(val)
    return _DEFAULT_WEIGHT


def _career_starts(entry):
    """Career start count from Form King; 0 = debutant. None if unknown.

    firstStarter is authoritative; otherwise the leading number of careerForm
    ("16:0-1-1" -> 16 starts).
    """
    if entry.get("firstStarter"):
        return 0
    cf = (entry.get("form") or {}).get("careerForm")
    if cf and ":" in cf:
        try:
            return int(cf.split(":")[0])
        except ValueError:
            pass
    return None


def _last5(entry, limit=5):
    """Up to 5 most-recent ACTUAL race runs for a runner, newest first.

    Barrier trials (trial=True), spells and non-runs (no finish/distance) are
    excluded — just real race form. Each run: rating (0-100), finishing pos,
    distance, going and date (epoch ms).
    """
    runs = []
    for ev in (entry.get("pastEvents") or []):
        if ev.get("trial") or ev.get("spell"):
            continue
        pos, dist = ev.get("finishPosition"), ev.get("distance")
        if not pos or not dist:            # 0 / None = not a completed run
            continue
        # 0-100 ability rating for that run; weightForAgeRating is in the summary
        # feed, the others are fallbacks for the richer race-form feed.
        rating = next((ev.get(k) for k in ("weightForAgeRating", "exp", "benchmarkRating", "lws")
                       if isinstance(ev.get(k), (int, float))), None)
        runs.append({
            # Form King's own ids for that race, so the site can open the full field.
            "rid":       ev.get("raceId"),
            "mid":       ev.get("meetingId"),
            "rating":    round(float(rating), 1) if rating is not None else None,
            "pos":       int(pos),
            "dist":      int(dist),
            "going":     ev.get("going"),
            "date":      ev.get("date"),
            # Richer per-run detail for the bias / speed-map / settle engines.
            "settle":    _as_int(ev.get("posSettling")),   # settling position
            "pos400":    _as_int(ev.get("pos400m")),       # position 400m out
            "pos800":    _as_int(ev.get("pos800m")),       # position 800m out
            "barrier":   _as_int(ev.get("barrier")),       # barrier drawn that run
            "nrun":      _as_int(ev.get("numRunners")),    # field size that run
            "track":     ev.get("track"),                  # which track this run was at
            "bsp":       _as_float(ev.get("bsp")),         # Betfair SP (results channel)
            "margin":    _as_float(ev.get("margin")),      # beaten/winning margin (L)
            "sp":        _as_float(ev.get("startingPrice")),
            "trackspd":  _as_float(ev.get("trackSpeed")),  # speed figure for the run
            # Real per-run context (v2): prep stage, weight, rider, stewards.
            "prep":      _as_int(ev.get("raceInPrep")),    # run number in that prep
            "wt":        _as_float(ev.get("weight")),      # weight carried that run
            "jockey":    ev.get("jockey"),
            "comment":   ev.get("stewardsComment") or None,
            "class":     ev.get("restrictions"),
            "dsp":       _as_int(ev.get("daysSincePreviousRace")),
            "next_wins": _as_int(((ev.get("subsequentForm") or {}).get("ALL") or {}).get("wins")),
            "next_runs": _as_int(((ev.get("subsequentForm") or {}).get("ALL") or {}).get("races")),
            "rname":     ev.get("raceName"),
            "time_ms":   _as_int(ev.get("timeInMillis")),
            "fstr":      _as_float(ev.get("fieldStrength")),
        })
    runs.sort(key=lambda r: r["date"] or 0, reverse=True)
    return runs[:limit]


def _trials(entry, limit=6):
    """Recent jump-outs and official trials for a runner, newest first (real
    Form King data: date, track, trip, going, finish, field, margin, time)."""
    out = []
    for ev in (entry.get("recentTrials") or []):
        if not ev.get("date"):
            continue
        out.append({
            "id": ev.get("raceId"), "date": ev.get("date"), "track": ev.get("track"),
            "dist": _as_int(ev.get("distance")), "going": ev.get("going"),
            "pos": _as_int(ev.get("finishPosition")) or None, "nrun": _as_int(ev.get("numRunners")) or None,
            "margin": _as_float(ev.get("margin")), "time_ms": _as_int(ev.get("timeInMillis")) or None,
            "name": ev.get("raceName"), "jockey": ev.get("jockey"),
        })
    out.sort(key=lambda r: r["date"] or 0, reverse=True)
    return out[:limit]


def _jump_time(race):
    """Race jump time as epoch milliseconds.

    Prefer Form King's advertisedStart / raceTime when numeric; otherwise the
    race's own `date` field (epoch ms). app.py reads this against the
    Australia/Melbourne clock to show a live countdown or JUMPED.
    """
    for key in ("advertisedStart", "raceTime"):
        v = race.get(key)
        if isinstance(v, (int, float)):
            return int(v)
    d = race.get("date")
    return int(d) if isinstance(d, (int, float)) else None


def _profile(entry):
    """Real runner profile from the card: connections, breeding, records, ratings.

    Only fields Form King actually supplies; anything absent stays None so the
    UI can show "-" rather than a made-up value.
    """
    horse = entry.get("horse") or {}
    form = entry.get("form") or {}
    going = form.get("goingForm") or {}
    jf = entry.get("jockeyForm") or {}
    tf = entry.get("trainerForm") or {}
    rt = entry.get("ratings") or {}
    return {
        "jockey": entry.get("jockey"), "trainer": entry.get("trainer"),
        "age": _as_int(horse.get("age")), "sex": horse.get("type"),
        "sire": horse.get("sire"), "dam": horse.get("dam"), "dam_sire": horse.get("sireOfDam"),
        "prizemoney": _as_float(entry.get("totalPrizeMoney")),
        "days_since_run": _as_int(entry.get("daysSinceLastRace")),
        "days_since_win": _as_int(entry.get("daysSinceLastWin")),
        "distance_change": entry.get("distanceChange"),
        "gear_changes": entry.get("gearChanges") or None,
        "form": {
            "career": form.get("careerForm"), "track": form.get("trackForm"),
            "distance": form.get("distanceForm"), "track_dist": form.get("trackAndDistanceForm"),
            "good": going.get("good"), "soft": going.get("soft"), "heavy": going.get("heavy"),
            "synthetic": going.get("synthetic"), "dead": going.get("dead"),
            "slow": going.get("slow"), "fast": going.get("fast"),
            "first_up": form.get("firstUpForm"), "second_up": form.get("secondUpForm"),
            "third_up": form.get("thirdUpForm"), "todays_going": form.get("todaysGoingForm"),
        },
        "jockey_12m": jf.get("lastTwelveMonthForm"),
        "jockey_12m_win_pct": _as_float(jf.get("lastTwelveMonthWinPercentage")),
        "jockey_horse": jf.get("horseComboForm"),
        "trainer_12m": tf.get("lastTwelveMonthForm"),
        "trainer_12m_win_pct": _as_float(tf.get("lastTwelveMonthWinPercentage")),
        "trainer_jockey": tf.get("jockeyComboForm"),
        "trainer_jockey_win_pct": _as_float(tf.get("jockeyComboWinPercentage")),
        "fk_rating_exp": _as_float(rt.get("exp")), "fk_rating_peak": _as_float(rt.get("peak")),
        "fk_rating_peak12m": _as_float(rt.get("peak12m")), "fk_rating_neural": _as_float(rt.get("neural")),
        # Rider / stable detail straight from the feed.
        "jockey_12m_place_pct": _as_float(jf.get("lastTwelveMonthPlacePercentage")),
        "jockey_12m_rides": _as_int(jf.get("lastTwelveMonthRides")),
        "jockey_track": jf.get("trackComboForm"), "trainer_track": tf.get("trackComboForm"),
        "first_starter": bool(entry.get("firstStarter")),
        "class_form": form.get("classForm"),
        "benchmark": _as_float(entry.get("benchmarkRating")),
    }


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
    o = entry.get("odds") or {}
    flucs = o.get("flucs")
    return {
        "horse_name":    name,
        "saddlecloth":   _as_int(entry.get("number")),      # real race-book number
        "barrier":       int(entry.get("barrier") or 0),
        "weight":        _weight(entry),
        "prep_run_num":  int(prep) if prep else 1,
        "wfa_rating":    entry.get("benchmarkRating"),
        "market_odds":   odds,
        "career_starts": _career_starts(entry),
        "last5":         _last5(entry),
        # Live fields for the bias/trigger engines.
        "apprentice_claim": _as_float(entry.get("apprenticeClaim")) or 0.0,
        "sire":             horse.get("sire"),
        "firm_or_drift":    _as_float(o.get("firmOrDrift")),
        "flucs":            flucs if isinstance(flucs, list) else None,
        # v2: every past run Form King returns (up to 12) and the runner's real
        # profile, so no part of the card has to be invented.
        "runs_all":         _last5(entry, limit=12),
        "trials":           _trials(entry),
        "fk_profile":       _profile(entry),
    }


def _map_race(race):
    """One race (+ its runners) -> ingest race dict."""
    entries = [m for m in (_map_entry(e) for e in race.get("entries", [])) if m]
    return {
        "race_number":         int(race.get("number") or 0),
        "distance":            int(race.get("distance") or 0),
        "class_name":          _class_name(race.get("restrictions"), race.get("name")),
        # Form King doesn't supply a pace index; use a neutral 1.0 (mock range is
        # 0.8-1.2). Tempo is derived mainly from the speed map's leader count.
        "pace_pressure_index": 1.0,
        "jump_time":           _jump_time(race),
        "entries":             entries,
    }


def _map_meeting(summary):
    """A /b2c/meetings/{id} summary -> one ingest-shaped meeting dict."""
    meeting = {
        "track_id":      summary.get("id"),
        "track_name":    summary.get("trackName"),
        "rail_position": _rail(summary.get("railPosition"), summary.get("railMetres")),
        "condition":     _condition(summary.get("going"), summary.get("goingNumber")),
        "track_variant": 0.0,
        "meeting_date":  _date_str(summary.get("date")),
        # Live surface-moisture readings (strings in the feed).
        "penetrometer":  summary.get("penetrometer"),
        "rainfall":      summary.get("rainfall"),
        "irrigation":    summary.get("irrigation"),
    }
    races = [_map_race(r) for r in summary.get("races", [])]
    # Drop races with no live runners so the book is never built on an empty field.
    races = [r for r in races if r["entries"]]
    return {"meeting": meeting, "races": races}


# Victorian thoroughbred tracks, for meetings whose listing has no state field.
# Matched on the start of the track name, so "Pakenham Synthetic" or
# "Sandown-Hillside" match too. A listed state always wins over this list.
VIC_TRACKS = (
    "flemington", "caulfield", "moonee valley", "the valley", "sandown", "cranbourne",
    "pakenham", "mornington", "geelong", "ballarat", "bendigo", "kilmore", "seymour",
    "sale", "moe", "traralgon", "warrnambool", "hamilton", "stawell", "horsham", "ararat",
    "swan hill", "echuca", "wangaratta", "wodonga", "benalla", "kyneton", "donald",
    "bairnsdale", "werribee", "tatura", "yarra valley", "yarra glen", "mildura", "colac",
    "camperdown", "casterton", "coleraine", "penshurst", "terang", "dunkeld",
    "great western", "avoca", "murtoa", "nhill", "st arnaud", "burrumbeet", "edenhope",
    "balnarring", "woolamai", "hanging rock", "towong", "swifts creek", "stony creek",
    "alexandra", "mansfield", "wycheproof", "ouyen", "kerang", "manangatang", "healesville",
)


def meeting_state(m):
    """State of an upcoming meeting: its listed state, else VIC by track name."""
    state = (m.get("state") or "").strip().upper()
    if state:
        return state
    name = (m.get("trackName") or m.get("venueName") or m.get("id") or "").strip().lower()
    return "VIC" if any(name.startswith(t) for t in VIC_TRACKS) else None


def allowed_states():
    """States to load (FORMKING_STATES / HARVEST_STATES, default VIC); None = all."""
    cfg = str(_cfg("FORMKING_STATES", _cfg("HARVEST_STATES", "VIC")) or "VIC").strip().upper()
    return None if cfg == "ALL" else tuple(x.strip() for x in cfg.split(","))


# --- public entry point ------------------------------------------------------
def fetch_live_meetings(max_meetings=None):
    """Fetch the live card from Form King and return ingest-shaped meetings.

    Lists every upcoming meeting (1 credit), then pulls each one's full summary
    (5 credits each) — soonest first — so the dashboard shows real weights, odds,
    prep runs and benchmarks for the whole day's (and beyond) card.

    By default ALL upcoming meetings are loaded. FORMKING_MAX_MEETINGS can cap
    this to save credits: 0 (or unset) means no cap / load everything, any
    positive number loads at most that many. Raises on a feed error — strict
    live-only, no mock fallback.
    """
    if max_meetings is None:
        try:
            max_meetings = int(_cfg("FORMKING_MAX_MEETINGS", _DEFAULT_MAX_MEETINGS))
        except (TypeError, ValueError):
            max_meetings = _DEFAULT_MAX_MEETINGS

    session = _session()
    upcoming = _get(session, _UPCOMING_PATH)
    if isinstance(upcoming, dict):               # tolerate {"meetings": [...]}
        upcoming = upcoming.get("meetings", [])

    # The upcoming feed can list the same meeting id more than once; dedupe so we
    # never fetch (and bill) a meeting's summary twice or show it twice.
    seen, unique = set(), []
    for m in upcoming:
        mid = m.get("id")
        if mid and mid not in seen:
            seen.add(mid)
            unique.append(m)
    upcoming = unique

    # Soonest first (TAB meetings ahead of non-TAB at the same time).
    upcoming.sort(key=lambda m: (m.get("date") or 0, not m.get("tabMeeting", False)))

    # The feed also lists one physical meeting under more than one id (e.g. a TAB
    # and a non-TAB listing of the same card), which the id dedupe above can't
    # catch. Collapse those on (track_name, date) now that the list is sorted, so
    # the TAB listing wins and we never fetch (or show) the same card twice.
    def _track_key(m):
        name = m.get("trackName") or m.get("venueName") or m.get("name") or ""
        return (name.strip().lower(), m.get("date") or 0)

    seen_tracks, collapsed = set(), []
    for m in upcoming:
        key = _track_key(m)
        if key[0] and key in seen_tracks:
            continue
        seen_tracks.add(key)
        collapsed.append(m)
    upcoming = collapsed

    # Victorian meetings only by default (FORMKING_STATES=ALL for every state):
    # the syndicate bets Victoria and each extra card costs 5 credits.
    states = allowed_states()
    if states:
        upcoming = [m for m in upcoming if meeting_state(m) in states]

    # 0 / negative / unset => load every upcoming meeting; else cap for credits.
    selected = upcoming if max_meetings <= 0 else upcoming[:max_meetings]

    # Reset the skip log for this pull. A single meeting's summary can 500 (a
    # Form King server error) or time out; skip just that meeting and keep the
    # rest rather than aborting the whole card. Strict live-only still holds —
    # nothing is fabricated, the skipped meetings are simply not shown.
    SKIPPED_MEETINGS.clear()
    out = []
    for m in selected:
        mid = m.get("id")
        if not mid:
            continue
        try:
            summary = _get(session, _SUMMARY_PATH.format(meeting_id=mid))
            mapped = _map_meeting(summary)
        except Exception as exc:
            SKIPPED_MEETINGS.append({"id": mid, "track": m.get("trackName"), "error": str(exc)})
            continue
        if mapped["races"]:
            out.append(mapped)
    return out
