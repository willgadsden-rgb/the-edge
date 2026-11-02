"""Phase 2 orchestrator for PIE.

Runs the rating engine, prep profiler and pricing model across every race in
racing.db, persists score_0_to_100 and fair_odds back to race_entries, and
prints a styled terminal card per race. Mock data only (see CLAUDE.md).

Usage:
    python run_model.py
"""

import json

from database import get_connection
from rating_engine import (
    calculate_0_to_100_score,
    generate_trajectory,
    trajectory_trend,
)
from prep_engine import profile_runner
from pricing_engine import price_race, OVERLAY_EDGE

# --- Minimal ANSI styling (no external dependency) ---------------------------
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"


def _color(text, *codes):
    return "".join(codes) + text + RESET


def _pad(text, width, align="<"):
    """Pad plain text to a visible width (apply colour AFTER padding)."""
    return "{:{a}{w}}".format(text, a=align, w=width)


def _trend_cell(trend):
    """Arrow + signed slope, coloured by direction."""
    if trend > 0.1:
        return _pad("UP  {:+.1f}".format(trend), 9), GREEN
    if trend < -0.1:
        return _pad("DN  {:+.1f}".format(trend), 9), RED
    return _pad("--  {:+.1f}".format(trend), 9), DIM


def _tag_color(tag):
    if "PEAK TARGET" in tag:
        return MAGENTA + BOLD
    if "TAPERING" in tag:
        return YELLOW
    return DIM  # conditioning


def _value_cell(edge, flag):
    """Rich value flag string, e.g. '+EV OVERLAY (+35%)' or 'UNDERLAY (-12%)'."""
    pct = "{:+.0f}%".format(edge * 100)
    if flag == "overlay":
        return _color("{} +EV OVERLAY ({})".format("\U0001F525", pct), GREEN, BOLD)
    if flag == "fair":
        return _color("FAIR ({})".format(pct), CYAN)
    return _color("UNDERLAY ({})".format(pct), RED)


# Column layout: (header, width, alignment). Value column is intentionally last
# so the emoji's terminal width can't knock earlier columns out of alignment.
COLUMNS = [
    ("Horse", 18, "<"),
    ("Bar", 3, ">"),
    ("Wt", 5, ">"),
    ("Prep", 7, "<"),
    ("Score", 6, ">"),
    ("Trend", 9, "<"),
    ("Prep Target", 22, "<"),
    ("Fair", 8, ">"),
    ("Mkt", 7, ">"),
    ("Value", 20, "<"),
]


def _print_header(race, meeting):
    title = "RACE {}  |  {}m  {}".format(
        race["race_number"], race["distance"], race["class_name"])
    sub = "{} ({})  Rail: {}  {}".format(
        meeting["track_name"], meeting["track_id"],
        meeting["rail_position"], meeting["condition"])

    header_cells = [_pad(h, w, a) for (h, w, a) in COLUMNS]
    header_line = " ".join(header_cells)
    width = len(header_line)

    print()
    print(_color(title.ljust(width), BOLD, BLUE))
    print(_color(sub, DIM))
    print(_color("-" * width, DIM))
    print(_color(header_line, BOLD))
    print(_color("-" * width, DIM))
    return width


def evaluate_race(conn, race, meeting):
    """Rate, prep-profile, price and print one race. Returns pricing results."""
    entries = conn.execute(
        "SELECT * FROM race_entries WHERE race_id = ? ORDER BY entry_id",
        (race["race_id"],),
    ).fetchall()

    # 1) Rating + prep adjustment per runner; persist score_0_to_100.
    meta = {}  # entry_id -> display/intermediate values
    for e in entries:
        try:
            last5 = json.loads(e["last5_json"] or "[]")
        except Exception:
            last5 = []
        base_score = calculate_0_to_100_score(
            e["wfa_rating"], e["weight"], race["distance"], race["class_name"],
            last_ratings=[r.get("rating") for r in last5],     # newest first
            barrier=e["barrier"],
            last_positions=[r.get("pos") for r in last5])

        traj = generate_trajectory(e["horse_name"], base_score)
        trend = trajectory_trend(traj)

        prep = profile_runner(e["horse_name"], e["prep_run_num"], base_score)
        adjusted = round(max(0.0, min(100.0, base_score + prep["prep_adjustment"])), 1)

        conn.execute(
            "UPDATE race_entries SET score_0_to_100 = ? WHERE entry_id = ?",
            (adjusted, e["entry_id"]),
        )

        # Persist the prep profile row for this horse's current stage.
        p = prep["profile"]
        conn.execute(
            """
            INSERT OR REPLACE INTO horse_prep_profiles
                (horse_name, prep_stage, starts, wins, avg_score)
            VALUES (?, ?, ?, ?, ?)
            """,
            (p["horse_name"], p["prep_stage"], p["starts"], p["wins"], p["avg_score"]),
        )

        meta[e["entry_id"]] = {
            "barrier": e["barrier"],
            "weight": e["weight"],
            "prep_stage": prep["prep_stage"],
            "trend": trend,
            "tag": prep["tag"],
        }
    conn.commit()

    # 2) Price the race from the freshly written scores.
    results = price_race(race["race_id"], conn=conn)

    # 3) Render the card.
    width = _print_header(race, meeting)
    for r in results:
        m = meta[r["entry_id"]]
        trend_text, trend_code = _trend_cell(m["trend"])

        cells = []
        cells.append(_pad(r["horse_name"], 18, "<"))
        cells.append(_pad(str(m["barrier"]), 3, ">"))
        cells.append(_pad("{:.1f}".format(m["weight"]), 5, ">"))
        cells.append(_pad(m["prep_stage"], 7, "<"))
        cells.append(_color(_pad("{:.1f}".format(r["score_0_to_100"]), 6, ">"), BOLD))
        cells.append(_color(trend_text, trend_code))
        cells.append(_color(_pad(m["tag"], 22, "<"), _tag_color(m["tag"])))
        cells.append(_pad("${:.2f}".format(r["fair_odds"]) if r["fair_odds"] is not None else "—", 8, ">"))
        cells.append(_pad("${:.2f}".format(r["market_odds"]) if r["market_odds"] is not None else "—", 7, ">"))
        cells.append(_value_cell(r["edge"], r["flag"]))
        print(" ".join(cells))

    print(_color("-" * width, DIM))
    overlays = [r for r in results if r["flag"] == "overlay"]
    if overlays:
        names = ", ".join("{} (+{:.0f}%)".format(r["horse_name"], r["edge"] * 100)
                          for r in overlays)
        print(_color("  {} VALUE OVERLAYS (edge >= {:.0f}%): ".format(
            "\U0001F525", OVERLAY_EDGE * 100), GREEN, BOLD) + names)
    else:
        print(_color("  No value overlays in this market.", DIM))
    return results


def main():
    conn = get_connection()
    try:
        meetings = conn.execute("SELECT * FROM meetings ORDER BY meeting_id").fetchall()
        if not meetings:
            print("No data in racing.db. Run ingest.py first.")
            return

        print(_color("\n=== PIE :: MATHEMATICAL ENGINE & 100% FAIR PRICING ===", BOLD, CYAN))
        for meeting in meetings:
            races = conn.execute(
                "SELECT * FROM races WHERE meeting_id = ? ORDER BY race_number",
                (meeting["meeting_id"],),
            ).fetchall()
            for race in races:
                evaluate_race(conn, race, meeting)
        print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
