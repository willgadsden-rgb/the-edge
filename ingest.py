"""Ingestion for the Punting Intelligence Engine (PIE).

Strict live-only: fetches the card from Form King and writes it into racing.db,
rebuilding the schema each run. There is no mock/synthetic fallback — a feed
failure raises so the dashboard shows a live error, never fabricated runners.
"""

import json

import formking_client
from database import get_connection, init_db


def load_meetings():
    """Fetch the live Form King card.

    Strict live-only: raises on any failure (missing key, API/network error, or
    an empty feed). There is no mock fallback — the dashboard must show a live
    feed error rather than fabricated runners (see MASTER INSTRUCTION step 1).
    """
    meetings = formking_client.fetch_live_meetings()
    if not meetings:
        raise RuntimeError("Form King returned no meetings for the current window.")
    formking_client.LAST_FETCH_ERROR = None
    print(f"  data source: Form King (live) — {len(meetings)} meetings")
    return meetings


def ingest_meeting(data, conn):
    """Insert one generated meeting (and its races + entries) into the db.

    Also derives a simple horse_prep_profiles row per runner from its
    prep_run_num so the table is populated in Phase 1. Returns a small summary
    dict of how many rows were written.
    """
    meeting = data["meeting"]
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO meetings (track_id, track_name, rail_position, condition, track_variant, meeting_date)
        VALUES (:track_id, :track_name, :rail_position, :condition, :track_variant, :meeting_date)
        """,
        {**meeting, "meeting_date": meeting.get("meeting_date")},
    )
    meeting_id = cur.lastrowid

    race_count = 0
    entry_count = 0
    for race in data["races"]:
        cur.execute(
            """
            INSERT INTO races (meeting_id, race_number, distance, class_name, pace_pressure_index, jump_time)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (meeting_id, race["race_number"], race["distance"],
             race["class_name"], race["pace_pressure_index"], race.get("jump_time")),
        )
        race_id = cur.lastrowid
        race_count += 1

        for entry in race["entries"]:
            cs = entry.get("career_starts")
            last5_json = json.dumps(entry.get("last5") or [])
            cur.execute(
                """
                INSERT INTO race_entries
                    (race_id, horse_name, barrier, weight, prep_run_num, wfa_rating, market_odds,
                     career_starts, last5_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (race_id, entry["horse_name"], entry["barrier"], entry["weight"],
                 entry["prep_run_num"], entry["wfa_rating"], entry["market_odds"], cs, last5_json),
            )
            entry_count += 1

            # Seed the prep profile. A debutant (career_starts == 0) is tagged so
            # the card can suppress fabricated form and show a clean DEBUT badge.
            if cs == 0:
                prep_stage = "debut"
            elif entry["prep_run_num"] == 1:
                prep_stage = "first-up"
            else:
                prep_stage = "in-work"
            starts = cs if cs is not None else entry["prep_run_num"]
            cur.execute(
                """
                INSERT OR REPLACE INTO horse_prep_profiles
                    (horse_name, prep_stage, starts, wins, avg_score)
                VALUES (?, ?, ?, ?, ?)
                """,
                (entry["horse_name"], prep_stage, starts, 0, None),
            )

    conn.commit()
    return {"meetings": 1, "races": race_count, "entries": entry_count}


def _dedupe_meetings(meetings):
    """Collapse meetings that resolve to the same canonical (track, date).

    The Form King feed can list one physical meeting under more than one id,
    sometimes with differing `date` values, so a feed-level id/date dedupe misses
    them. After mapping, those twins share the same track_name + meeting_date
    (which is exactly what the card shows), so dedupe on that ground truth here —
    a track never holds two meetings on one date. Keeps the first occurrence.
    """
    seen, unique = set(), []
    for data in meetings:
        m = data["meeting"]
        key = ((m.get("track_name") or "").strip().lower(), m.get("meeting_date"))
        if key[0] and key in seen:
            continue
        seen.add(key)
        unique.append(data)
    return unique


def main():
    # Reset so each ingest run starts from a clean, known state.
    init_db(reset=True)
    meetings = _dedupe_meetings(load_meetings())

    totals = {"meetings": 0, "races": 0, "entries": 0}
    conn = get_connection()
    try:
        for data in meetings:
            summary = ingest_meeting(data, conn)
            for k in totals:
                totals[k] += summary[k]
    finally:
        conn.close()

    print("Ingestion complete:")
    print(f"  meetings inserted: {totals['meetings']}")
    print(f"  races inserted:    {totals['races']}")
    print(f"  entries inserted:  {totals['entries']}")


if __name__ == "__main__":
    main()
