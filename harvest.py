"""Form King harvester: grow the history database from every card pulled.

Each meeting card (5 credits) carries every runner's last 12 runs. This script
stores the raw card, then explodes it into the history tables (history_db.py):

    meetings / races   - today's meeting and races, plus every past race seen
    runs               - every past run of every runner (+ top placegetters)
    horses             - breeding and connections
    entries            - today's runners (barrier, weight, jockey, prep, gear...)
    odds_snapshots     - the price of every runner at this pull

Usage
    python harvest.py                      # today's meetings (Melbourne date)
    python harvest.py --date 2026-11-10    # a given day's meetings
    python harvest.py --file card.json     # load a saved card (0 credits)
    python harvest.py --dry-run            # list what would be pulled; no fetch

Credits: 1 for the upcoming list + 5 per meeting. Only Victorian meetings are
pulled (HARVEST_STATES, default "VIC"; "ALL" for every state). HARVEST_MAX_MEETINGS
(env) caps meetings per run. Run it twice on race days: morning (cards, odds) and
after the last race (results land in the runners' past runs).
"""

import argparse
import datetime
import json
import re
import sys
import zlib
from zoneinfo import ZoneInfo

import formking_client as fk
from history_db import HistoryDB

MELBOURNE = ZoneInfo("Australia/Melbourne")
RAW_KEEP_DAYS = 30


# --- small converters --------------------------------------------------------
def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def _melb_date(epoch_ms):
    if not isinstance(epoch_ms, (int, float)) or epoch_ms <= 0:
        return None
    return datetime.datetime.fromtimestamp(epoch_ms / 1000, MELBOURNE).date().isoformat()


def _utc_iso(epoch_ms):
    if not isinstance(epoch_ms, (int, float)) or epoch_ms <= 0:
        return None
    return datetime.datetime.fromtimestamp(epoch_ms / 1000, datetime.timezone.utc).isoformat()


def _race_date(race_id, epoch_ms):
    """Race date from the race id ('NARA_011126_1' -> 2026-11-01), else Melbourne date."""
    m = re.match(r"^[A-Z0-9]+_(\d{2})(\d{2})(\d{2})_\d+$", race_id or "")
    if m:
        dd, mm, yy = m.groups()
        return "20{}-{}-{}".format(yy, mm, dd)
    return _melb_date(epoch_ms)


def _int(v):
    return fk._as_int(v)


def _float(v):
    return fk._as_float(v)


def _gear(gear):
    if not gear:
        return None
    return json.dumps([{"gear": g.get("gear"), "change": g.get("change"), "on": g.get("on")}
                       for g in gear if isinstance(g, dict)])


# --- card -> rows ------------------------------------------------------------
def parse_card(card, pulled_at=None):
    """Turn one /b2c/meetings/{id} response into rows per history table."""
    pulled_at = pulled_at or _now_iso()
    out = {t: [] for t in ("meetings", "races", "horses", "runs", "entries", "odds_snapshots")}
    meeting_date = _melb_date(card.get("date"))

    out["meetings"].append({
        "meeting_id": card.get("id"), "meeting_date": meeting_date,
        "track": card.get("trackName"), "state": card.get("state"),
        "going": card.get("going"), "going_number": _int(card.get("goingNumber")),
        "rail": card.get("railPosition"), "rail_metres": _float(card.get("railMetres")),
        "penetrometer": card.get("penetrometer"), "rainfall": card.get("rainfall"),
        "irrigation": card.get("irrigation"), "tab_meeting": int(bool(card.get("tabMeeting"))),
        "updated_at": pulled_at,
    })

    for race in card.get("races") or []:
        race_id = race.get("raceId")
        betfair = next((x.get("id") for x in ((race.get("thirdPartyIds") or {}).get("BETFAIR") or [])
                        if x.get("type") == "WIN"), None)
        going = race.get("going")
        if going and race.get("goingNumber") is not None:
            going = "{} {}".format(going, race.get("goingNumber"))
        out["races"].append({
            "race_id": race_id, "meeting_id": card.get("id"), "race_date": meeting_date,
            "track": race.get("trackName") or card.get("trackName"), "state": card.get("state"),
            "race_number": _int(race.get("number")), "race_name": race.get("name"),
            "distance": _int(race.get("distance")), "restrictions": race.get("restrictions"),
            "class_band": fk._class_name(race.get("restrictions"), race.get("name")),
            "going": going, "rail": race.get("railPosition"),
            "prize_money": _float(race.get("totalPrizeMoney")),
            "field_size": _int(race.get("numRunners")), "jump_time": _utc_iso(race.get("date")),
            "race_time_ms": None, "betfair_market_id": betfair,
            "tab_meeting": int(bool(race.get("tabMeeting"))), "updated_at": pulled_at,
        })

        for e in race.get("entries") or []:
            horse = e.get("horse") or {}
            name = horse.get("name")
            if not name:
                continue
            rt = e.get("ratings") or {}
            out["horses"].append({
                "horse_name": name, "breeding_id": e.get("breedingId"), "sire": horse.get("sire"),
                "dam": horse.get("dam"), "dam_sire": horse.get("sireOfDam"),
                "foal_date": _melb_date(horse.get("foalDate")), "sex": horse.get("type"),
                "country": horse.get("country"), "trainer": e.get("trainer"),
                "training_location": horse.get("trainingLocation"), "last_seen": meeting_date,
            })
            out["entries"].append({
                "race_id": race_id, "horse_name": name, "saddlecloth": _int(e.get("number")),
                "barrier": _int(e.get("barrier")),
                "weight": _float(e.get("weightCarried") or e.get("weight")),
                "apprentice_claim": _float(e.get("apprenticeClaim")),
                "jockey": e.get("jockey"), "trainer": e.get("trainer"),
                "race_in_prep": _int(e.get("raceInPrep")),
                "days_since_run": _int(e.get("daysSinceLastRace")),
                "distance_change": e.get("distanceChange"),
                "gear_changes": e.get("gearChanges") or None,
                "scratched": int(bool(e.get("scratched"))), "emergency": int(bool(e.get("emergency"))),
                "fk_exp": _float(rt.get("exp")), "fk_peak": _float(rt.get("peak")),
                "fk_peak12m": _float(rt.get("peak12m")), "fk_neural": _float(rt.get("neural")),
                "profile_json": json.dumps(fk._profile(e)), "updated_at": pulled_at,
            })
            odds = e.get("odds") or {}
            if odds:
                out["odds_snapshots"].append({
                    "race_id": race_id, "horse_name": name, "pulled_at": pulled_at,
                    "feed_timestamp": _utc_iso(odds.get("timestamp")),
                    "avg_open": _float(odds.get("avgOpen")), "avg_now": _float(odds.get("avgNow")),
                    "best_now": _float(odds.get("bestNow")),
                    "firm_or_drift": _float(odds.get("firmOrDrift")),
                })
            for ev in e.get("pastEvents") or []:
                _past_event(out, ev, name, pulled_at)

    for table in out:
        out[table] = _dedupe(table, out[table])
    return out


def _past_event(out, ev, horse_name, pulled_at):
    """One past run -> a race row, a run row, minimal meeting row, placings."""
    race_id = ev.get("raceId")
    if not race_id or ev.get("trial"):
        return
    race_date = _race_date(race_id, ev.get("date"))
    out["meetings"].append({"meeting_id": ev.get("meetingId"), "meeting_date": race_date,
                            "track": ev.get("track"), "state": ev.get("state"),
                            "tab_meeting": int(bool(ev.get("tabMeeting"))), "updated_at": pulled_at})
    out["races"].append({
        "race_id": race_id, "meeting_id": ev.get("meetingId"), "race_date": race_date,
        "track": ev.get("track"), "state": ev.get("state"), "race_number": _int(ev.get("raceNumber")),
        "race_name": ev.get("raceName"), "distance": _int(ev.get("distance")),
        "restrictions": ev.get("restrictions"),
        "class_band": fk._class_name(ev.get("restrictions"), ev.get("raceName")),
        "going": ev.get("going"), "prize_money": _float(ev.get("totalPrizemoney")),
        "field_size": _int(ev.get("numRunners")), "race_time_ms": _int(ev.get("timeInMillis")),
        "tab_meeting": int(bool(ev.get("tabMeeting"))), "updated_at": pulled_at,
    })
    sub = (ev.get("subsequentForm") or {}).get("ALL") or {}
    out["runs"].append({
        "race_id": race_id, "horse_name": ev.get("horse") or horse_name,
        "runner_number": _int(ev.get("runnerNumber")), "barrier": _int(ev.get("barrier")),
        "weight": _float(ev.get("weight")), "jockey": ev.get("jockey"),
        "finish_pos": _int(ev.get("finishPosition")) or None, "margin": _float(ev.get("margin")),
        "field_size": _int(ev.get("numRunners")), "settle_pos": _int(ev.get("posSettling")) or None,
        "pos_800": _int(ev.get("pos800m")) or None, "pos_400": _int(ev.get("pos400m")) or None,
        "sp": _float(ev.get("startingPrice")) or None, "bsp": _float(ev.get("bsp")) or None,
        "track_speed": _float(ev.get("trackSpeed")), "wfa_rating": _float(ev.get("weightForAgeRating")),
        "lws": _float(ev.get("lws")), "wfa_diff": _float(ev.get("wfaDiff")),
        "field_strength": _float(ev.get("fieldStrength")),
        "race_in_prep": _int(ev.get("raceInPrep")), "race_in_career": _int(ev.get("raceInCareer")),
        "days_since_prev": _int(ev.get("daysSincePreviousRace")),
        "stewards_comment": ev.get("stewardsComment") or None, "gear": _gear(ev.get("gear")),
        "next_runs": _int(sub.get("races")), "next_wins": _int(sub.get("wins")),
        "next_woe": _float(sub.get("winsOverExpectations")),
        "source": "pastEvents", "updated_at": pulled_at,
    })
    # Top placegetters of that race: partial rows for horses we may never card.
    # Placings give lengths BEHIND the winner (winner 0.0); convert to the
    # pastEvents convention used everywhere: winner = +winning margin, others =
    # -lengths beaten. The winning margin is the 2nd placegetter's margin.
    placings = ev.get("placings") or []
    second = next((_float(p.get("margin")) for p in placings
                   if _int(p.get("finishPosition")) == 2), None)
    for p in placings:
        if p.get("thisHorse") or not p.get("horse"):
            continue
        pos = _int(p.get("finishPosition")) or None
        raw = _float(p.get("margin"))
        if pos == 1:
            margin = second
        else:
            margin = -abs(raw) if raw is not None else None
        out["runs"].append({
            "race_id": race_id, "horse_name": p["horse"], "barrier": _int(p.get("barrier")),
            "weight": _float(p.get("weight")) or None, "jockey": p.get("jockey"),
            "finish_pos": pos, "margin": margin,
            "field_size": _int(ev.get("numRunners")), "source": "placings", "updated_at": pulled_at,
        })


def _dedupe(table, rows):
    """Merge rows with the same key inside one card, keeping the fullest values.

    A pastEvents row beats a placings row for the same horse and race."""
    from history_db import TABLES
    keys = TABLES[table]["key"]
    merged = {}
    for r in rows:
        k = tuple(r.get(c) for c in keys)
        if any(v is None for v in k):
            continue
        if k not in merged:
            merged[k] = dict(r)
            continue
        cur = merged[k]
        prefer_new = table == "runs" and r.get("source") == "pastEvents" and cur.get("source") != "pastEvents"
        for c, v in r.items():
            if v is not None and (cur.get(c) is None or prefer_new):
                cur[c] = v
    return list(merged.values())


# --- store -------------------------------------------------------------------
ORDER = ("meetings", "races", "horses", "runs", "entries", "odds_snapshots")


def store_card(db, card, pulled_at=None, ref=None, keep_raw=True):
    """Save the raw card and upsert its rows. Returns {table: rows written}."""
    pulled_at = pulled_at or _now_iso()
    if keep_raw:
        body = zlib.compress(json.dumps(card, separators=(",", ":")).encode("utf-8"), 9)
        db.upsert("raw_payloads", [{"endpoint": "meeting", "ref": ref or card.get("id"),
                                    "pulled_at": pulled_at, "body_zlib": body}])
    rows = parse_card(card, pulled_at)
    counts = {t: db.upsert(t, rows[t]) for t in ORDER}
    db.commit()
    return counts


# --- fetch -------------------------------------------------------------------
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


def meetings_for(date_iso, upcoming, states=("VIC",)):
    """Upcoming meetings on a Melbourne date in the given states (None = all),
    one listing per track, TAB listing first. Returns (kept, skipped_names)."""
    seen, out, skipped = set(), [], []
    for m in sorted(upcoming, key=lambda m: (not m.get("tabMeeting", False), m.get("id") or "")):
        if _melb_date(m.get("date")) != date_iso or not m.get("id"):
            continue
        key = ((m.get("trackName") or "").strip().lower(), m.get("date"))
        if key in seen:
            continue
        seen.add(key)
        if states and meeting_state(m) not in states:
            skipped.append(m.get("trackName") or m["id"])
            continue
        out.append(m)
    return out, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="Melbourne date YYYY-MM-DD (default: today)")
    ap.add_argument("--file", nargs="*", help="load saved card JSON file(s) instead of fetching")
    ap.add_argument("--max", type=int, default=None, help="cap meetings this run (credits)")
    ap.add_argument("--dry-run", action="store_true", help="list meetings; fetch no cards")
    ap.add_argument("--keep-raw-days", type=int, default=RAW_KEEP_DAYS)
    args = ap.parse_args(argv)

    import os
    if os.environ.get("GITHUB_ACTIONS") and not os.environ.get("DATABASE_URL"):
        # On GitHub the SQLite fallback would vanish with the runner: stop before
        # spending any Form King credits.
        print("DATABASE_URL secret is not set - nothing harvested, no credits used.", file=sys.stderr)
        return 2
    db = HistoryDB()
    db.ensure_schema()
    print("History database: {}".format(db.kind))

    if args.file:
        for path in args.file:
            card = json.load(open(path))
            print(path, store_card(db, card, ref=card.get("id")))
        db.close()
        return 0

    date_iso = args.date or datetime.datetime.now(MELBOURNE).date().isoformat()
    session = fk._session()
    upcoming = fk._get(session, fk._UPCOMING_PATH)
    if isinstance(upcoming, dict):
        upcoming = upcoming.get("meetings", [])
    states_cfg = (fk._cfg("HARVEST_STATES", "VIC") or "VIC").strip().upper()
    states = None if states_cfg == "ALL" else tuple(x.strip() for x in states_cfg.split(","))
    todays, skipped = meetings_for(date_iso, upcoming, states)
    if skipped:
        print("Not pulled (outside {}): {}".format(states_cfg, ", ".join(skipped)))
    cap = args.max if args.max is not None else int(fk._cfg("HARVEST_MAX_MEETINGS", 0) or 0)
    if cap > 0:
        todays = todays[:cap]
    print("{} meeting(s) on {}: {} (cost {} credits)".format(
        len(todays), date_iso, ", ".join(m.get("trackName") or m["id"] for m in todays),
        1 + 5 * len(todays)))
    if args.dry_run:
        db.close()
        return 0

    failed = 0
    for m in todays:
        try:
            card = fk._get(session, fk._SUMMARY_PATH.format(meeting_id=m["id"]))
            print(m.get("trackName"), store_card(db, card, ref=m["id"]))
            if states and (card.get("state") or "").upper() not in states:
                print("NOTE: {} is in {} - add it to the skip rules".format(
                    m.get("trackName"), card.get("state")))
        except Exception as exc:          # one bad meeting never stops the rest
            failed += 1
            db.conn.rollback()
            print("SKIPPED {}: {}".format(m.get("trackName") or m["id"], exc), file=sys.stderr)
    db.prune_raw(args.keep_raw_days)
    db.commit()
    db.close()
    return 1 if failed and failed == len(todays) else 0


if __name__ == "__main__":
    sys.exit(main())
