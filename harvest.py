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
def parse_card(card, pulled_at=None, placings=True):
    """Turn one /b2c/meetings/{id} response into rows per history table."""
    pulled_at = pulled_at or _now_iso()
    out = {t: [] for t in ("meetings", "races", "horses", "runs", "entries", "odds_snapshots", "trials")}
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
            "race_time_ms": _int((race.get("officialTiming") or {}).get("timeInMillis")), "betfair_market_id": betfair,
            "tab_meeting": int(bool(race.get("tabMeeting"))), "updated_at": pulled_at,
        })

        starters = sum(1 for e in race.get("entries") or [] if not e.get("scratched")) or None
        win_margin = next((_float((e.get("horseResult") or {}).get("margin")) for e in race.get("entries") or []
                           if _int((e.get("horseResult") or {}).get("finishPosition")) == 2), None)
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
                "profile_json": json.dumps(dict(fk._profile(e), benchmark=_float(e.get("benchmarkRating")),
                                                first_starter=bool(e.get("firstStarter")), home_track=e.get("homeTrack"),
                                                avg_prize=_float(e.get("averagePrizeMoney")), wfa_diff=_float(e.get("wfaDiff")),
                                                trials=len(e.get("recentTrials") or []))),
                "updated_at": pulled_at,
            })
            for tr in e.get("recentTrials") or []:
                if not tr.get("raceId"):
                    continue
                out["trials"].append({
                    "trial_id": tr.get("raceId"), "horse_name": tr.get("horse") or name,
                    "trial_date": _race_date(tr.get("raceId"), tr.get("date")), "track": tr.get("track"),
                    "state": tr.get("state"), "distance": _int(tr.get("distance")), "going": tr.get("going"),
                    "trial_name": tr.get("raceName"), "finish_pos": _int(tr.get("finishPosition")) or None,
                    "margin": _float(tr.get("margin")), "field_size": _int(tr.get("numRunners")) or None,
                    "jockey": tr.get("jockey"), "time_ms": _int(tr.get("timeInMillis")) or None, "updated_at": pulled_at,
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
                _past_event(out, ev, name, pulled_at, placings)
            hr = e.get("horseResult") or {}
            pos = _int(hr.get("finishPosition"))
            if pos and not e.get("scratched"):
                # Today's result, straight off the card (past runs only get it
                # later, with the rating and stewards report).
                m = _float(hr.get("margin"))
                out["runs"].append({
                    "race_id": race_id, "horse_name": name, "runner_number": _int(hr.get("number")),
                    "barrier": _int(hr.get("barrier")), "weight": _float(hr.get("weight")),
                    "jockey": hr.get("jockey"), "finish_pos": pos,
                    "margin": (win_margin if pos == 1 else (-abs(m) if m is not None else None)),
                    "field_size": starters, "sp": _float(hr.get("startingPrice")),
                    "bsp": _float(hr.get("betfairStartingPrice")),
                    "race_in_prep": _int(e.get("raceInPrep")), "days_since_prev": _int(e.get("daysSinceLastRace")),
                    "open_fluc": _float((hr.get("officialFlucs") or [None])[0]), "top_fluc": _float(hr.get("topFluc")) or None,
                    "flucs": json.dumps(hr.get("officialFlucs")) if hr.get("officialFlucs") else None,
                    "tote_win": _float(hr.get("bestToteWin")) or None,
                    "source": "result", "updated_at": pulled_at,
                })

    for table in out:
        out[table] = _dedupe(table, out[table])
    return out


def _past_event(out, ev, horse_name, pulled_at, with_placings=True):
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
    placings = (ev.get("placings") or []) if with_placings else []
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
ORDER = ("meetings", "races", "horses", "runs", "entries", "odds_snapshots", "trials")


def store_card(db, card, pulled_at=None, ref=None, keep_raw=True, placings=True):
    """Save the raw card and upsert its rows. Returns {table: rows written}."""
    pulled_at = pulled_at or _now_iso()
    if keep_raw:
        body = zlib.compress(json.dumps(card, separators=(",", ":")).encode("utf-8"), 9)
        db.upsert("raw_payloads", [{"endpoint": "meeting", "ref": ref or card.get("id"),
                                    "pulled_at": pulled_at, "body_zlib": body}])
    rows = parse_card(card, pulled_at, placings)
    counts = {t: db.upsert(t, rows[t]) for t in ORDER}
    db.commit()
    return counts


# --- fetch -------------------------------------------------------------------
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
        if states and fk.meeting_state(m) not in states:
            skipped.append(m.get("trackName") or m["id"])
            continue
        out.append(m)
    return out, skipped


def known_meetings(db, date_iso, states=("VIC",)):
    """Meetings already in the history database for a date. Form King's upcoming
    list drops a meeting once it has raced, so a past date (e.g. a results pull
    the next morning) uses the meeting ids we stored when the card was pulled."""
    try:
        rows = db.query("SELECT meeting_id, track, state FROM meetings WHERE meeting_date = ?", (date_iso,))
    except Exception:
        db.conn.rollback()
        return []
    out = []
    for mid, track, state in rows:
        if states and (state or "").upper() not in states:
            continue
        out.append({"id": mid, "trackName": track, "date": date_iso})
    return out


def results_pending(db, today_iso, days=3):
    """Published meetings from the last few days whose races still have no
    result (the night run was missed or ran before the last race)."""
    since = (datetime.date.fromisoformat(today_iso) - datetime.timedelta(days=days)).isoformat()
    t = "public.edge_races" if db.kind == "postgres" else "edge_races"
    tm = "public.edge_meetings" if db.kind == "postgres" else "edge_meetings"
    try:
        rows = db.query(
            "SELECT DISTINCT r.meeting_id, m.track, r.meeting_date FROM {t} r JOIN {tm} m ON m.meeting_id = r.meeting_id "
            "WHERE r.meeting_date >= ? AND r.meeting_date < ? AND COALESCE(r.result_in, 0) = 0".format(t=t, tm=tm),
            (since, today_iso))
    except Exception:
        db.conn.rollback()
        return []
    return [{"id": mid, "trackName": "{} ({}, results)".format(track, d), "date": d} for mid, track, d in rows]


def backfill_candidates(db, date_from, date_to, states=("VIC",)):
    """Meetings in the window that we know of (from horses' past runs) but have
    never pulled as a card. Form King returns an old card as it stood on race
    day: full field, opening and final prices, results, form as of that day."""
    rows = db.query(
        "SELECT m.meeting_id, m.track, m.state, m.meeting_date FROM meetings m "
        "WHERE m.meeting_date >= ? AND m.meeting_date <= ? "
        "AND NOT EXISTS (SELECT 1 FROM races r JOIN entries e ON e.race_id = r.race_id WHERE r.meeting_id = m.meeting_id) "
        "ORDER BY m.meeting_date DESC", (date_from, date_to))
    out = []
    for mid, track, state, d in rows:
        if not mid or not re.search(r"-\d{8}$", mid):
            continue                                  # trials / jump-out meetings
        if states and fk.meeting_state({"state": state, "trackName": track}) not in states:
            continue
        out.append({"id": mid, "trackName": track, "date": d})
    return out


def run_backfill(db, date_from, date_to, cap, states=("VIC",)):
    session = fk._session()
    todo = backfill_candidates(db, date_from, date_to, states)
    print("Backfill {} to {}: {} meeting(s) not yet pulled; doing up to {}".format(date_from, date_to, len(todo), cap))
    done = credits = failed = 0
    for m in todo[:cap]:
        try:
            card = fk._get(session, fk._SUMMARY_PATH.format(meeting_id=m["id"]))
            credits += 5
            if states and (card.get("state") or "").upper() not in states:
                print("  {} is {} - skipped".format(m["id"], card.get("state"))); continue
            counts = store_card(db, card, ref=m["id"], keep_raw=False, placings=False)
            done += 1
            print("  {} {} entries {} runs {}".format(m["date"], m["id"], counts.get("entries"), counts.get("runs")))
        except Exception as exc:
            failed += 1
            db.conn.rollback()
            print("  SKIPPED {}: {}".format(m["id"], str(exc)[:120]), file=sys.stderr)
            if failed >= 15 and done == 0:
                print("Too many failures, stopping.", file=sys.stderr); break
    print("Backfill done: {} stored, {} failed, about {} credits; {} still to do".format(done, failed, credits, max(0, len(todo) - cap)))
    return 0


def republish_window(db, date_from, date_to, cap, states=("VIC",)):
    """Re-pull meetings we already hold form for and publish them to the site, so
    Meeting Review can show past days. 5 credits a meeting; meetings already on
    the site with results are skipped."""
    rows = db.query(
        "SELECT DISTINCT r.meeting_id, m.track, m.meeting_date FROM races r "
        "JOIN entries e ON e.race_id = r.race_id "
        "JOIN meetings m ON m.meeting_id = r.meeting_id "
        "WHERE r.race_date >= ? AND r.race_date <= ? "
        "AND NOT EXISTS (SELECT 1 FROM public.edge_races pr "
        "                WHERE pr.meeting_id = r.meeting_id AND pr.result_in = 1) "
        "ORDER BY m.meeting_date DESC", (date_from, date_to))
    todo = [{"id": mid, "track": track, "date": d} for mid, track, d in rows if mid]
    print("Publish window {} to {}: {} meeting(s) held but not on the site; doing up to {}".format(
        date_from, date_to, len(todo), cap))
    session = fk._session()
    done = failed = credits = 0
    cards = []
    for m in todo[:cap]:
        try:
            card = fk._get(session, fk._SUMMARY_PATH.format(meeting_id=m["id"]))
            credits += 5
            if states and (card.get("state") or "").upper() not in states:
                print("  {} is {} - skipped".format(m["id"], card.get("state"))); continue
            store_card(db, card, ref=m["id"], keep_raw=True, placings=False)
            cards.append(card)
            done += 1
            if len(cards) >= 10:
                publish_all(db, cards); cards = []
        except Exception as exc:
            failed += 1
            db.conn.rollback()
            print("  SKIPPED {} {}: {}".format(m["date"], m["id"], str(exc)[:120]), file=sys.stderr)
            if failed >= 15 and done == 0:
                print("Too many failures, stopping.", file=sys.stderr); break
    if cards:
        publish_all(db, cards)
    print("Publish window done: {} meetings, {} failed, about {} credits; {} still to do".format(
        done, failed, credits, max(0, len(todo) - cap)))
    return 0


VIC_TRACK_WORDS = (
    "flemington caulfield moonee valley sandown pakenham cranbourne geelong ballarat bendigo "
    "werribee kyneton seymour benalla wangaratta wodonga echuca swan hill mildura horsham "
    "warrnambool hamilton casterton coleraine penshurst ararat stawell donald st arnaud "
    "sale bairnsdale traralgon moe yarra valley healesville kilmore mornington racing.com "
    "colac camperdown terang stony creek yea alexandra mansfield balnarring great western "
    "avoca dunkeld edenhope manangatang murtoa nhill birchip charlton tatura wycheproof "
    "hanging rock bright buchan corryong omeo"
).split()


def _is_vic(track, state=None):
    if state:
        return str(state).upper() == "VIC"
    t = str(track or "").lower()
    if not t or " - " in t:                       # overseas meetings read "G B - York"
        return False
    return any(w in t for w in VIC_TRACK_WORDS)


def audit_window(db, date_from, date_to, cap, fix=True):
    """Every Victorian meeting we have any trace of in the window, against what
    the website actually holds. Anything missing is pulled and published.

    Our own meetings table only knows meetings we pulled on the day, so this
    works from the races table instead, which also carries meetings seen in
    horses' past runs - that is how a meeting we missed at the time (a Form King
    error, a cap, a day the harvest did not run) can still be found later.
    """
    rows = db.query(
        "SELECT r.meeting_id, MIN(r.race_date), MIN(r.track), MAX(r.state), COUNT(DISTINCT r.race_id), "
        "       (SELECT COUNT(*) FROM public.edge_races pr WHERE pr.meeting_id = r.meeting_id) "
        "FROM races r WHERE r.race_date >= ? AND r.race_date <= ? AND r.meeting_id IS NOT NULL "
        "GROUP BY r.meeting_id ORDER BY MIN(r.race_date) DESC", (date_from, date_to))
    known, missing = [], []
    for mid, d, track, state, races, pub in rows:
        if not _is_vic(track, state):
            continue
        known.append((d, track, mid, races, pub))
        if not pub:
            missing.append({"id": mid, "date": d, "track": track, "races": races})
    print("Audit {} to {}: {} Victorian meetings known, {} not on the website".format(
        date_from, date_to, len(known), len(missing)))
    for m in missing:
        print("  MISSING {} {:<22} {} ({} races in our history)".format(m["date"], m["track"], m["id"], m["races"]))
    if not fix or not missing:
        return missing
    session = fk._session()
    done = failed = 0
    cards = []
    for m in missing[:cap]:
        try:
            card = fk._get(session, fk._SUMMARY_PATH.format(meeting_id=m["id"]))
            store_card(db, card, ref=m["id"], keep_raw=True, placings=False)
            cards.append(card)
            done += 1
            if len(cards) >= 8:
                publish_all(db, cards); cards = []
        except Exception as exc:
            failed += 1
            db.conn.rollback()
            print("  COULD NOT PULL {} {}: {}".format(m["date"], m["id"], str(exc)[:140]), file=sys.stderr)
    if cards:
        publish_all(db, cards)
    print("Audit done: {} pulled, {} could not be pulled, about {} credits; {} left over the cap".format(
        done, failed, done * 5, max(0, len(missing) - cap)))
    # Say plainly what the website holds now, date by date.
    after = db.query(
        "SELECT meeting_date, track, COUNT(*) FROM public.edge_races "
        "WHERE meeting_date >= ? AND meeting_date <= ? GROUP BY meeting_date, track "
        "ORDER BY meeting_date DESC, track", (date_from, date_to))
    print("On the website now: {} meetings".format(len(after)))
    for d, track, n in after:
        print("  {} {:<22} {} races".format(d, track, n))
    return missing


def publish_all(db, cards):
    """Score and publish the pulled cards for the website (no extra credits).
    A publishing failure never undoes the harvest."""
    try:
        import publish
        publish.ensure_pub_schema(db)
        model = publish.load_model(db)
        for card in cards:
            try:
                print("Published {}: {}".format(card.get("trackName") or card.get("id"),
                                                publish.publish_card(db, card, model)))
            except Exception as exc:
                db.conn.rollback()
                print("PUBLISH FAILED {}: {}".format(card.get("id"), exc), file=sys.stderr)
        if model is not None:
            try:
                print("Rising Stars: {} listed".format(publish.publish_stars(db, model)))
            except Exception as exc:
                db.conn.rollback()
                print("STARS FAILED: {}".format(exc), file=sys.stderr)
    except Exception as exc:
        print("PUBLISH FAILED: {}".format(exc), file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="Melbourne date YYYY-MM-DD (default: today)")
    ap.add_argument("--file", nargs="*", help="load saved card JSON file(s) instead of fetching")
    ap.add_argument("--max", type=int, default=None, help="cap meetings this run (credits)")
    ap.add_argument("--dry-run", action="store_true", help="list meetings; fetch no cards")
    ap.add_argument("--keep-raw-days", type=int, default=RAW_KEEP_DAYS)
    ap.add_argument("--no-publish", action="store_true", help="skip publishing scores for the website")
    ap.add_argument("--catchup-only", action="store_true",
                    help="only re-pull recent meetings that are still missing results")
    ap.add_argument("--backfill", nargs=2, metavar=("FROM", "TO"),
                    help="pull old meetings in this date range as they stood on race day (5 credits each)")
    ap.add_argument("--publish-window", nargs=2, metavar=("FROM", "TO"),
                    help="re-pull meetings we hold in this range and publish them to the site (5 credits each)")
    ap.add_argument("--audit", nargs=2, metavar=("FROM", "TO"),
                    help="find every Victorian meeting in this range that the website is missing, and pull it")
    ap.add_argument("--audit-only", action="store_true", help="list the gaps without spending credits")
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

    if args.audit:
        audit_window(db, args.audit[0], args.audit[1],
                     args.max if args.max is not None else 40, fix=not args.audit_only)
        db.close()
        return 0

    if args.publish_window:
        rc = republish_window(db, args.publish_window[0], args.publish_window[1],
                              args.max if args.max is not None else 40)
        db.close()
        return rc

    if args.backfill:
        rc = run_backfill(db, args.backfill[0], args.backfill[1], args.max if args.max is not None else 100)
        db.close()
        return rc

    if args.file:
        cards = []
        for path in args.file:
            card = json.load(open(path))
            print(path, store_card(db, card, ref=card.get("id")))
            cards.append(card)
        if not args.no_publish:
            publish_all(db, cards)
        db.close()
        return 0

    date_iso = args.date or datetime.datetime.now(MELBOURNE).date().isoformat()
    session = fk._session()
    upcoming = fk._get(session, fk._UPCOMING_PATH)
    if isinstance(upcoming, dict):
        upcoming = upcoming.get("meetings", [])
    states_cfg = (fk._cfg("HARVEST_STATES", "VIC") or "VIC").strip().upper()
    states = None if states_cfg == "ALL" else tuple(x.strip() for x in states_cfg.split(","))
    today_iso = datetime.datetime.now(MELBOURNE).date().isoformat()
    if args.catchup_only:
        todays, skipped = [], []
    else:
        todays, skipped = meetings_for(date_iso, upcoming, states)
        if not todays and date_iso < today_iso:
            todays = known_meetings(db, date_iso, states)
            if todays:
                print("{} has raced: re-pulling the stored meeting(s) for results.".format(date_iso))
    if skipped:
        print("Not pulled (outside {}): {}".format(states_cfg, ", ".join(skipped)))
    cap = args.max if args.max is not None else int(fk._cfg("HARVEST_MAX_MEETINGS", 0) or 0)
    if cap > 0:
        todays = todays[:cap]
    if args.catchup_only or (not args.date and fk._cfg("HARVEST_CATCHUP", "1") != "0"):
        have = {m["id"] for m in todays}
        extra = [m for m in results_pending(db, today_iso) if m["id"] not in have]
        if extra:
            print("Missing results, re-pulling: {}".format(", ".join(m["trackName"] for m in extra)))
            todays = todays + extra
    print("{} meeting(s) on {}: {} (cost {} credits)".format(
        len(todays), date_iso, ", ".join(m.get("trackName") or m["id"] for m in todays),
        1 + 5 * len(todays)))
    if args.dry_run:
        db.close()
        return 0

    failed = 0
    cards = []
    for m in todays:
        try:
            card = fk._get(session, fk._SUMMARY_PATH.format(meeting_id=m["id"]))
            print(m.get("trackName"), store_card(db, card, ref=m["id"]))
            cards.append(card)
            if states and (card.get("state") or "").upper() not in states:
                print("NOTE: {} is in {} - add it to the skip rules".format(
                    m.get("trackName"), card.get("state")))
        except Exception as exc:          # one bad meeting never stops the rest
            failed += 1
            db.conn.rollback()
            print("SKIPPED {}: {}".format(m.get("trackName") or m["id"], exc), file=sys.stderr)
    db.prune_raw(args.keep_raw_days)
    db.commit()
    if cards and not args.no_publish:
        publish_all(db, cards)
    db.close()
    return 1 if failed and failed == len(todays) else 0


if __name__ == "__main__":
    sys.exit(main())
