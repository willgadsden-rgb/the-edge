"""Intraday track-adaptation & TSV loop for The Edge (Phase 7).

After each completed race we compute a Track Speed Variant (TSV = actual winning
time - benchmark par time), track where the placegetters settled, and auto-detect
a surface drift. If >=70% of placegetters are finishing wide (lane 4+), a
"Gutter Pattern" intraday bias is registered and applied to upcoming races.
Mock data only (see CLAUDE.md). This module also settles the mock results that
populate the historical archive columns.
"""

import random

import speedmap_engine

GUTTER_THRESHOLD = 0.70        # share of placegetters finishing wide to flag drift
INTRADAY_WIDE_BONUS = 1.5      # +pts to lanes 4+ when a gutter pattern is running
INTRADAY_RAIL_TAX = -1.5       # -pts to lanes 1-2 when a gutter pattern is running


def benchmark_par_time(distance):
    """Rough benchmark winning time (seconds) for a distance on a fair surface."""
    return round(distance * 0.0585 + 1.5, 2)


def _active(conn, race_id):
    return conn.execute(
        "SELECT entry_id, horse_name, barrier, fair_odds FROM race_entries "
        "WHERE race_id = ? AND scratched = 0 AND fair_odds IS NOT NULL ORDER BY entry_id",
        (race_id,)).fetchall()


def settle_results(conn, seed=99):
    """Simulate official finishing order/times/BSP for every race and mark completed.

    Populates finish_pos, beaten_lengths, official_time, result_bsp on race_entries
    and completed / benchmark_par_time / actual_win_time / tsv on races.
    """
    rng = random.Random(seed)
    import datetime as _dt
    today = _dt.date.today().isoformat()
    # Only PAST meetings are run and settled; today's and upcoming races stay open
    # (live / early market) with no results yet.
    races = conn.execute(
        "SELECT r.race_id, r.distance FROM races r JOIN meetings m ON m.meeting_id = r.meeting_id "
        "WHERE m.meeting_date < ? ORDER BY r.race_id", (today,)).fetchall()
    for r in races:
        rid, distance = r["race_id"], r["distance"]
        rows = _active(conn, rid)
        if not rows:
            continue
        ids = [x["entry_id"] for x in rows]
        weights = [1.0 / x["fair_odds"] for x in rows]

        # Draw a full finishing order without replacement, weighted by model prob.
        order, pool_ids, pool_w = [], ids[:], weights[:]
        while pool_ids:
            tot = sum(pool_w)
            draw = rng.random() * tot
            acc = 0.0
            for i, w in enumerate(pool_w):
                acc += w
                if draw <= acc:
                    order.append(pool_ids.pop(i))
                    pool_w.pop(i)
                    break
            else:
                order.append(pool_ids.pop())
                pool_w.pop()

        base = benchmark_par_time(distance)
        tsv = round(rng.uniform(-1.2, 2.2), 2)        # + = slow (track playing tough)
        win_time = round(base + tsv, 2)
        fair_by_id = {x["entry_id"]: x["fair_odds"] for x in rows}

        cum = 0.0
        for pos, eid in enumerate(order, start=1):
            if pos == 1:
                beaten, t = 0.0, win_time
            else:
                cum = round(cum + rng.uniform(0.1, 1.8), 2)
                beaten, t = cum, round(win_time + cum * 0.17, 2)
            bsp = round(max(1.04, fair_by_id[eid] * rng.uniform(0.85, 1.28)), 2)
            conn.execute(
                "UPDATE race_entries SET finish_pos=?, beaten_lengths=?, official_time=?, "
                "result_bsp=? WHERE entry_id=?", (pos, beaten, t, bsp, eid))
        conn.execute(
            "UPDATE races SET completed=1, benchmark_par_time=?, actual_win_time=?, tsv=? "
            "WHERE race_id=?", (base, win_time, tsv, rid))
    conn.commit()


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
    avg_tsv = round(sum(t for _, t in tsv_list) / len(tsv_list), 2) if tsv_list else None
    return {"completed_races": len(races), "tsv_list": tsv_list, "avg_tsv": avg_tsv,
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
    settle_results(c)
    print(analyze_intraday(c, 1))
    c.close()
