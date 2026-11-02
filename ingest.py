"""Ingestion for the Punting Intelligence Engine (PIE).

Phase 1: takes the mock meeting from mock_data_generator and writes it into
racing.db. Running this module rebuilds the schema and re-inserts the data so
it is safe to run repeatedly during development.
"""

import formking_client
from database import get_connection, init_db
from mock_data_generator import generate_meetings


def load_meetings():
    """Return the meetings to ingest, from Form King (live) or mock data.

    Honours DATA_SOURCE (see formking_client). In "live" mode a failed fetch
    falls back to mock data so the dashboard always has something to show, and
    the reason is printed. "mock" mode (the default) makes no outbound calls.
    """
    if formking_client.is_live():
        try:
            meetings = formking_client.fetch_live_meetings()
            if meetings:
                print(f"  data source:       Form King (live) — {len(meetings)} meetings")
                return meetings
            print("  data source:       live returned no meetings — using mock data")
        except Exception as exc:  # network / auth / mapping error: degrade gracefully
            print(f"  data source:       live fetch failed ({exc}) — using mock data")
    return generate_meetings()


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
            INSERT INTO races (meeting_id, race_number, distance, class_name, pace_pressure_index)
            VALUES (?, ?, ?, ?, ?)
            """,
            (meeting_id, race["race_number"], race["distance"],
             race["class_name"], race["pace_pressure_index"]),
        )
        race_id = cur.lastrowid
        race_count += 1

        for entry in race["entries"]:
            cur.execute(
                """
                INSERT INTO race_entries
                    (race_id, horse_name, barrier, weight, prep_run_num, wfa_rating, market_odds)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (race_id, entry["horse_name"], entry["barrier"], entry["weight"],
                 entry["prep_run_num"], entry["wfa_rating"], entry["market_odds"]),
            )
            entry_count += 1

            # Seed a minimal prep profile from the runner's prep run number.
            # prep_stage buckets the campaign; starts/wins/avg_score are mock.
            prep_stage = "first-up" if entry["prep_run_num"] == 1 else "in-work"
            cur.execute(
                """
                INSERT OR REPLACE INTO horse_prep_profiles
                    (horse_name, prep_stage, starts, wins, avg_score)
                VALUES (?, ?, ?, ?, ?)
                """,
                (entry["horse_name"], prep_stage, entry["prep_run_num"], 0, None),
            )

    conn.commit()
    return {"meetings": 1, "races": race_count, "entries": entry_count}


def main():
    # Reset so each ingest run starts from a clean, known state.
    init_db(reset=True)
    meetings = load_meetings()

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
