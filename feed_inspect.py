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
