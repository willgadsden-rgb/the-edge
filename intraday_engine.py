"""Intraday track-adaptation loop for The Edge (strict live-only).

After each completed race today we track where the placegetters settled and
auto-detect a surface drift from the REAL results (race_entries.finish_pos,
populated from the live feed's pastEvents — see sync_formking.ingest_live_results).
If >=70% of placegetters are finishing wide (lane 4+), a "Gutter Pattern"
intraday bias is registered and applied to the remaining races. There is no
simulated settlement — a meeting with fewer than two finished races reports
CALCULATING and applies nothing.
"""

import speedmap_engine

# Confidence by number of finished races today (more results = more trust).
CONFIDENCE_BY_RACES = {2: 0.35, 3: 0.65}      # 4+ -> 0.90

GUTTER_THRESHOLD = 0.70        # share of placegetters finishing wide to flag drift
INTRADAY_WIDE_BONUS = 1.5      # +pts to lanes 4+ when a gutter pattern is running
INTRADAY_RAIL_TAX = -1.5       # -pts to lanes 1-2 when a gutter pattern is running


def benchmark_par_time(distance):
    """Rough benchmark winning time (seconds) for a distance on a fair surface."""
    return round(distance * 0.0585 + 1.5, 2)


def analyze_intraday(conn, meeting_id, up_to_race_number=None):
    """Analyse completed races for a meeting and detect intraday surface drift.

    Only races before up_to_race_number count as 'completed earlier today'. Returns
    a dict with the TSV list, placegetter lanes, and whether a gutter pattern is on.
    """
    q = ("SELECT race_id, race_number, tsv FROM races WHERE meeting_id=? AND completed=1")
    params = [meeting_id]
    if up_to_race_number is not None:
        q += " AND race_number < ?"
        params.append(up_to_race_number)
    races = conn.execute(q + " ORDER BY race_number", params).fetchall()

    tsv_list, placer_lanes = [], []
    for r in races:
        tsv_list.append((r["race_number"], r["tsv"]))
        ents = conn.execute(
            "SELECT entry_id, horse_name, barrier, finish_pos FROM race_entries "
            "WHERE race_id=? AND scratched=0 AND finish_pos IS NOT NULL", (r["race_id"],)).fetchall()
        tmap = speedmap_engine.build_tactical_map([dict(e) for e in ents])["runners"]
        for e in sorted(ents, key=lambda x: x["finish_pos"])[:3]:
            lane = tmap.get(e["horse_name"], {}).get("lane")
            if lane:
                placer_lanes.append(lane)

    wide = sum(1 for l in placer_lanes if l >= 4)
    share = (wide / len(placer_lanes)) if placer_lanes else 0.0
    gutter = len(placer_lanes) >= 3 and share >= GUTTER_THRESHOLD
    _tsv = [t for _, t in tsv_list if t is not None]
    avg_tsv = round(sum(_tsv) / len(_tsv), 2) if _tsv else None
    n = len(races)
    status = "LIVE" if n >= 2 else "CALCULATING"
    confidence = 0.90 if n >= 4 else CONFIDENCE_BY_RACES.get(n, 0.0)
    return {"completed_races": n, "status": status, "confidence": confidence,
            "tsv_list": tsv_list, "avg_tsv": avg_tsv,
            "placer_lanes": placer_lanes, "wide_share": round(share, 2),
            "gutter_detected": gutter}


def intraday_modifier(lane, gutter_detected):
    """Return (points, badge-or-None) for a runner given the intraday drift state."""
    if not gutter_detected or lane is None:
        return 0.0, None
    if lane >= 4:
        return INTRADAY_WIDE_BONUS, {"name": "Intraday Gutter Drift",
                                     "points": INTRADAY_WIDE_BONUS, "type": "bonus"}
    if lane <= 2:
        return INTRADAY_RAIL_TAX, {"name": "Intraday Rail Tax",
                                   "points": INTRADAY_RAIL_TAX, "type": "penalty"}
    return 0.0, None


if __name__ == "__main__":
    from database import get_connection
    c = get_connection()
    print(analyze_intraday(c, 1))
    c.close()
