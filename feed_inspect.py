"""One-off live-feed inspector for The Edge (temporary diagnostic).

Fetches a single upcoming meeting's raw Form King summary and returns a field
INVENTORY — key names and python types, plus presence probes — WITHOUT dumping
full values. It exists so we can see exactly which fields the live feed carries
before building features on them (flucs/steam, speedRating, claimWeight, sire,
completed-race results / Betfair SP). Costs ~6 credits per call (1 upcoming +
5 summary). Remove once the field audit is done.
"""

import formking_client as fk


def _types(d):
    """Shallow {key: type} map; dict/list show their size, scalars their type."""
    if not isinstance(d, dict):
        return {"_type": type(d).__name__, "_value": d if isinstance(d, (int, float, str, bool)) else None}
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = "dict{{{}}}".format(len(v))
        elif isinstance(v, list):
            out[k] = "list[{}]".format(len(v))
        else:
            out[k] = type(v).__name__
    return out


def _has(d, *keys):
    """Presence flags for specific keys on a dict (case-sensitive)."""
    d = d or {}
    return {k: (k in d) for k in keys}


def inspect_live_feed():
    """Return a field inventory of the first upcoming meeting's raw summary."""
    session = fk._session()
    upcoming = fk._get(session, fk._UPCOMING_PATH)
    if isinstance(upcoming, dict):
        upcoming = upcoming.get("meetings", [])
    if not upcoming:
        return {"error": "upcoming feed returned no meetings"}

    first = upcoming[0]
    mid = first.get("id")
    summary = fk._get(session, fk._SUMMARY_PATH.format(meeting_id=mid))

    races = summary.get("races") or []
    race0 = races[0] if races else {}
    entries = race0.get("entries") or []
    entry0 = entries[0] if entries else {}
    odds0 = entry0.get("odds") or {}
    horse0 = entry0.get("horse") or {}
    past = entry0.get("pastEvents") or []
    past0 = past[0] if past else {}

    probes = {
        # #3 steam/drift — is there a fluc time-series, or only snapshots?
        "odds_flucs": _has(odds0, "flucs", "ticks", "history", "fluctuations", "movements"),
        # #3 lone leader / pace duel — real speed figure per runner?
        "entry_speed": _has(entry0, "speedRating", "speedRatings", "speed", "sectional", "earlySpeed", "settlePosition"),
        # #3 apprentice claim
        "entry_claim": _has(entry0, "claimWeight", "claim", "apprenticeClaim", "allowance", "jockeyClaim"),
        # #3 wet sire index
        "pedigree": {**_has(entry0, "sire", "sireName", "damSire"), **{"horse." + k: v for k, v in _has(horse0, "sire", "sireName", "damSire", "dam").items()}},
        # #3 auto-settle / CLV — results + BSP on the (completed) entry?
        "entry_result": _has(entry0, "finishPosition", "result", "betfairSp", "sp", "bsp", "scratched", "margin"),
        # #1/#2 — any results/status at the race level (completed-race data)?
        "race_result": _has(race0, "status", "resulted", "results", "finished", "winner", "resultStatus"),
    }

    return {
        "upcoming_count": len(upcoming),
        "upcoming_item_keys": _types(first),
        "meeting_keys": _types(summary),
        "race_keys": _types(race0),
        "entry_keys": _types(entry0),
        "odds_keys": _types(odds0),
        "horse_keys": _types(horse0),
        "pastEvent_keys": _types(past0),
        "PROBES": probes,
    }


def inspect_results(max_meetings=3):
    """Find a race that has already run today and report whether the feed exposes
    live results on it — the open question for intraday bias (#2) and auto-settle.

    Scans the few soonest meetings, lists every race's status, and for the first
    race that looks resulted (status not open, or an entry carrying a result
    field) dumps the race + entry shapes and the actual result values. Costs
    ~1 + 5*scanned credits.
    """
    session = fk._session()
    upcoming = fk._get(session, fk._UPCOMING_PATH)
    if isinstance(upcoming, dict):
        upcoming = upcoming.get("meetings", [])
    if not upcoming:
        return {"error": "upcoming feed returned no meetings"}
    upcoming.sort(key=lambda m: (m.get("date") or 0, not m.get("tabMeeting", False)))

    _OPEN = {"", "OPEN", "ACCEPTANCES", "FINAL_FIELD", "FINALFIELD", "CLOSED", "NORMAL", "UPCOMING"}
    scanned, found = [], None
    for m in upcoming[:max_meetings]:
        summary = fk._get(session, fk._SUMMARY_PATH.format(meeting_id=m.get("id")))
        races = summary.get("races") or []
        scanned.append({"track": m.get("trackName"),
                        "race_status": [[r.get("number"), r.get("status")] for r in races]})
        if found is None:
            for r in races:
                ents = r.get("entries") or []
                e0 = ents[0] if ents else {}
                has_result = any(k in e0 for k in ("finishPosition", "result", "bsp", "betfairSp", "margin", "startingPrice"))
                if has_result or str(r.get("status") or "").upper() not in _OPEN:
                    found = (m.get("trackName"), r, e0)
                    break

    if found is None:
        return {"scanned": scanned,
                "note": "No resulted race found in the scanned meetings — all still open. "
                        "Try again later in the day once early races have run."}

    track, race, e0 = found
    result_vals = {k: e0.get(k) for k in
                   ("number", "scratched", "finishPosition", "result", "margin", "bsp",
                    "betfairSp", "sp", "startingPrice") if k in e0}
    return {
        "scanned": scanned,
        "found_track": track,
        "race_number": race.get("number"),
        "race_status": race.get("status"),
        "race_keys": _types(race),
        "race_result_fields": _has(race, "winner", "results", "result", "placings",
                                   "dividends", "exotics", "resultStatus"),
        "resulted_entry_keys": _types(e0),
        "resulted_entry_result_values": result_vals,
    }
