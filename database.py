"""Database layer for the Punting Intelligence Engine (PIE).

Phase 1: SQLite only, mock data. No outbound API calls (see CLAUDE.md).
Provides the connection helper and schema creation matching the table
specifications in CLAUDE.md.
"""

import math
import sqlite3
from pathlib import Path

# Single source of truth for the database file location, resolved next to
# this module so it is stable regardless of the current working directory.
DB_PATH = Path(__file__).resolve().parent / "racing.db"


def get_connection():
    """Return a SQLite connection to racing.db.

    Rows are returned as sqlite3.Row so callers can access columns by name,
    and foreign-key enforcement is turned on for referential integrity.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Schema statements, one per table, matching the CLAUDE.md spec. meetings and
# races carry explicit integer primary keys to anchor the relational links
# (races.meeting_id -> meetings.meeting_id, race_entries.race_id -> races.race_id).
SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS meetings (
        meeting_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        track_id        TEXT    NOT NULL,
        track_name      TEXT    NOT NULL,
        rail_position   TEXT,
        condition       TEXT,
        track_variant   REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS races (
        race_id              INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id           INTEGER NOT NULL,
        race_number          INTEGER NOT NULL,
        distance             INTEGER NOT NULL,
        class_name           TEXT    NOT NULL,
        pace_pressure_index  REAL,
        FOREIGN KEY (meeting_id) REFERENCES meetings (meeting_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS race_entries (
        entry_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        race_id         INTEGER NOT NULL,
        horse_name      TEXT    NOT NULL,
        barrier         INTEGER NOT NULL,
        weight          REAL    NOT NULL,
        prep_run_num    INTEGER NOT NULL,
        wfa_rating      REAL,
        speed_rating    REAL,
        score_0_to_100  REAL,
        fair_odds       REAL,
        market_odds     REAL,
        scratched       INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (race_id) REFERENCES races (race_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS horse_prep_profiles (
        horse_name   TEXT    PRIMARY KEY,
        prep_stage   TEXT,
        starts       INTEGER,
        wins         INTEGER,
        avg_score    REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bets_ledger (
        bet_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_id      INTEGER NOT NULL,
        taken_price   REAL,
        fair_price    REAL,
        bsp           REAL,
        clv_percent   REAL,
        profit_units  REAL,
        stake_dollars REAL,
        result        TEXT,
        FOREIGN KEY (entry_id) REFERENCES race_entries (entry_id)
    )
    """,
]

# Live market fluctuation history (Phase 4 live-betting engine). Each row is one
# recorded price tick for a runner, used to build opening/current flucs.
MARKET_FLUCS_SQL = """
    CREATE TABLE IF NOT EXISTS market_flucs (
        fluc_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_id  INTEGER NOT NULL,
        ts        REAL    NOT NULL,
        price     REAL    NOT NULL,
        FOREIGN KEY (entry_id) REFERENCES race_entries (entry_id)
    )
"""
SCHEMA.append(MARKET_FLUCS_SQL)

# Interactive syndicate bet ledger (Phase 4 live). Distinct from bets_ledger
# (model recommendations) — these are bets the operator actually logs. It starts
# empty: 0 bets, $0 outlay, $0 P&L, and is settled from live results.
USER_BETS_SQL = """
    CREATE TABLE IF NOT EXISTS user_bets (
        bet_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id  TEXT,
        race_id     TEXT,
        track_name  TEXT,
        race_number INTEGER,
        runner_id   TEXT,
        horse_name  TEXT,
        saddlecloth INTEGER,
        bet_mode    TEXT,          -- 'TO_WIN' or 'STAKE'
        target_win  REAL,
        stake       REAL,
        odds_taken  REAL,
        fair_odds   REAL,
        edge_at_bet REAL,
        bsp_settled REAL,
        status      TEXT DEFAULT 'PENDING',  -- 'PENDING','WON','LOST','SCRATCHED'
        payout      REAL DEFAULT 0.0,
        net_pnl     REAL DEFAULT 0.0,
        placed_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""
SCHEMA.append(USER_BETS_SQL)


# -----------------------------------------------------------------------------
# Benchmark "par score to win" by class (absolute 0-100 scale)
# -----------------------------------------------------------------------------
# First keyword matched in class_name wins. Values are the model score a horse
# typically needs to win that grade of race.
BENCHMARK_PAR = [
    ("group 1", 90.0), ("group 2", 86.0), ("group 3", 82.0),
    ("listed", 80.0), ("stakes", 80.0),
    ("benchmark 84", 78.0), ("open", 76.0),
    ("benchmark 78", 74.0), ("saturday", 74.0), ("metro", 74.0),
    ("benchmark 70", 69.0), ("midweek", 69.0),
    ("benchmark 64", 56.0), ("provincial", 56.0),
    ("benchmark 58", 48.0), ("country", 48.0),
    ("maiden", 42.0),
]
DEFAULT_PAR = 60.0


def par_for(class_name):
    """Return the benchmark par-score-to-win for a race class."""
    name = (class_name or "").lower()
    for keyword, par in BENCHMARK_PAR:
        if keyword in name:
            return par
    return DEFAULT_PAR


# Operational columns added after Phase 1. These are kept out of the core
# CREATE-TABLE list in CLAUDE.md's logical spec but are required for live
# execution (scratchings in Phase 3, bet settlement in the ledger). ensure_schema
# adds any that are missing so an older racing.db keeps working without a reset.
MIGRATIONS = {
    "meetings": [("meeting_date", "TEXT")],
    "races": [("completed", "INTEGER NOT NULL DEFAULT 0"),
              ("benchmark_par_time", "REAL"), ("actual_win_time", "REAL"), ("tsv", "REAL"),
              ("jump_time", "INTEGER")],  # live jump time, epoch milliseconds
    "race_entries": [("scratched", "INTEGER NOT NULL DEFAULT 0"),
                     ("finish_pos", "INTEGER"), ("beaten_lengths", "REAL"),
                     ("official_time", "REAL"), ("result_bsp", "REAL"),
                     ("saddlecloth", "INTEGER"), ("silk_url", "TEXT"), ("silk_svg", "TEXT"),
                     ("career_starts", "INTEGER"),  # live career start count; 0 = debut
                     ("last5_json", "TEXT")],       # last 5 ACTUAL runs (trials excluded), JSON
    "bets_ledger": [("stake_dollars", "REAL"), ("result", "TEXT")],
}


# -----------------------------------------------------------------------------
# Track geometry (Phase 4 realistic speed map)
# -----------------------------------------------------------------------------
# Each entry describes the shape of the run from the jump for a given
# (track_name, distance). Parameters:
#   run_to_turn_m  - metres of straight running before the bend (None = all straight)
#   turn_direction - 'left', 'right' or 'straight'
#   turn_radius    - radius of the inside rail through the bend, in metres
#   shown_m        - how many metres of the run the speed map animates
TRACK_GEOMETRY = {
    ("Flemington", 1200): {
        "label": "Flemington 1200m — Straight Six (pure sprint corridor, no bends)",
        "run_to_turn_m": None, "turn_direction": "straight",
        "turn_radius": None, "shown_m": 600,
    },
    ("Flemington", 1600): {
        "label": "Flemington 1600m — ~600m to the first turn, sweeping bend, 450m home straight",
        "run_to_turn_m": 600, "turn_direction": "left", "turn_radius": 286,
        "shown_m": 1200, "total_m": 1600, "straighten_m": 1050, "home_straight_m": 450,
    },
}


# NSW and QLD race clockwise (right-handed); VIC / SA / WA / TAS race
# anti-clockwise (left-handed). Direction is by state, applied by track name.
CLOCKWISE_TRACKS = {
    # NSW
    "Rosehill", "Randwick", "Warwick Farm", "Canterbury", "Kembla Grange",
    "Newcastle", "Hawkesbury", "Gosford", "Wyong",
    # QLD
    "Eagle Farm", "Doomben", "Gold Coast", "Sunshine Coast", "Toowoomba", "Ipswich",
}


# Per-track shape (metres): home-straight length and home-turn radius, so each
# course has its own geometry (tight Moonee Valley vs roomy Flemington).
TRACK_HOME_STRAIGHT = {"Flemington": 450, "Caulfield": 367, "Rosehill": 408, "Eagle Farm": 410,
                       "Moonee Valley": 173, "Randwick": 410, "Doomben": 320, "Ballarat": 450}
TRACK_RADIUS = {"Flemington": 286, "Caulfield": 205, "Rosehill": 220, "Eagle Farm": 215,
                "Moonee Valley": 118, "Randwick": 240, "Doomben": 150, "Ballarat": 200}
# Distance from the jump to the FIRST turn, per (track, distance) — the key bit a
# punter needs to read the early race. (Flemington's straight-course sprints and
# its 1600m live in TRACK_GEOMETRY above.)
FIRST_TURN = {
    ("Caulfield", 1100): 350, ("Caulfield", 2400): 720,
    ("Rosehill", 1100): 400, ("Rosehill", 1400): 450, ("Rosehill", 2000): 420,
    ("Eagle Farm", 1000): 250, ("Eagle Farm", 1200): 420,
    ("Moonee Valley", 1500): 300, ("Moonee Valley", 2040): 260,
    ("Randwick", 1300): 460, ("Randwick", 1600): 560,
}
DEFAULT_HOME_STRAIGHT = 350.0
DEFAULT_RADIUS = 215.0


def geometry_for(track_name, distance):
    """Return the track-geometry spec for a race.

    Explicit entries in TRACK_GEOMETRY win (e.g. Flemington's straight six). Any
    other race gets its own course shape: the state-correct turn direction (NSW &
    QLD clockwise, elsewhere anti-clockwise), the track's home-turn radius and home
    straight, and the real distance from the jump to the first turn.
    """
    geom = TRACK_GEOMETRY.get((track_name, distance))
    if geom is not None:
        return geom
    direction = "right" if track_name in CLOCKWISE_TRACKS else "left"
    radius = float(TRACK_RADIUS.get(track_name, DEFAULT_RADIUS))
    home = float(TRACK_HOME_STRAIGHT.get(track_name, DEFAULT_HOME_STRAIGHT))
    run_to_turn = float(FIRST_TURN.get((track_name, distance), max(260.0, min(520.0, distance * 0.3))))
    # Ballarat (~1,900m circuit, 450m home straight): a 1000m-ish sprint jumps in a
    # side chute and runs straight ~380m before the sweeping home turn — it must
    # not bend out of the stalls.
    if track_name == "Ballarat" and distance <= 1100:
        run_to_turn = 380.0
    arc = radius * math.pi / 2.0
    straighten = run_to_turn + arc
    return {
        "label": "{} {}m — ~{:.0f}m to the first turn, {:.0f}m home straight".format(
            track_name, distance, run_to_turn, home),
        "run_to_turn_m": run_to_turn, "turn_direction": direction,
        "turn_radius": radius, "shown_m": straighten + max(300.0, home * 0.8),
        "total_m": distance, "straighten_m": straighten, "home_straight_m": home,
    }


def _table_columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def ensure_schema(conn):
    """Add any missing operational columns/tables to an existing database."""
    conn.execute(MARKET_FLUCS_SQL)  # create the flucs table if it predates this build
    conn.execute(USER_BETS_SQL)     # create the user bet ledger if it predates this build
    for table, columns in MIGRATIONS.items():
        existing = _table_columns(conn, table)
        for name, decl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    conn.commit()


def init_db(reset: bool = False):
    """Create all tables if they do not exist.

    When reset is True the existing racing.db file is removed first so the
    schema is rebuilt from scratch (useful while iterating in Phase 1).
    """
    if reset and DB_PATH.exists():
        DB_PATH.unlink()

    conn = get_connection()
    try:
        for statement in SCHEMA:
            conn.execute(statement)
        conn.commit()
        # Bring any pre-existing tables up to the current column set.
        ensure_schema(conn)
    finally:
        conn.close()

    return DB_PATH


if __name__ == "__main__":
    path = init_db()
    print(f"Initialized database and schema at {path}")
