"""Read racing.db and print clean ASCII tables of each race.

Phase 1 verification tool: shows horse names, barriers, weights, prep runs and
raw ratings (wfa_rating) for every race in the database.
"""

from database import get_connection

# (header, row_key, width, alignment) for each column in the runner table.
COLUMNS = [
    ("Horse", "horse_name", 18, "<"),
    ("Barrier", "barrier", 7, ">"),
    ("Weight", "weight", 8, ">"),
    ("Prep Run", "prep_run_num", 8, ">"),
    ("WFA Rating", "wfa_rating", 10, ">"),
    ("Market $", "market_odds", 9, ">"),
]


def _format_cell(value, width, align):
    """Format a single cell value, rendering None as a dash."""
    text = "-" if value is None else str(value)
    return f"{text:{align}{width}}"


def _print_race_table(race, entries):
    """Print one race as a bordered ASCII table."""
    title = (f"Race {race['race_number']}: {race['distance']}m "
             f"{race['class_name']}  ({len(entries)} runners)")

    header_cells = [_format_cell(h, w, a) for (h, _, w, a) in COLUMNS]
    header_line = " | ".join(header_cells)
    separator = "-+-".join("-" * w for (_, _, w, _) in COLUMNS)

    print()
    print(title)
    print("=" * len(separator))
    print(header_line)
    print(separator)

    # Barrier order makes the race card read naturally.
    for entry in sorted(entries, key=lambda e: e["barrier"]):
        cells = [_format_cell(entry[key], w, a) for (_, key, w, a) in COLUMNS]
        print(" | ".join(cells))
    print("=" * len(separator))


def main():
    conn = get_connection()
    try:
        meetings = conn.execute("SELECT * FROM meetings ORDER BY meeting_id").fetchall()
        if not meetings:
            print("No meetings found in racing.db. Run ingest.py first.")
            return

        for meeting in meetings:
            print()
            print(f"MEETING: {meeting['track_name']} ({meeting['track_id']})  "
                  f"Rail: {meeting['rail_position']}  Track: {meeting['condition']}")

            races = conn.execute(
                "SELECT * FROM races WHERE meeting_id = ? ORDER BY race_number",
                (meeting["meeting_id"],),
            ).fetchall()

            for race in races:
                entries = conn.execute(
                    "SELECT * FROM race_entries WHERE race_id = ?",
                    (race["race_id"],),
                ).fetchall()
                _print_race_table(race, entries)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
