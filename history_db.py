"""History database for The Edge v2.

One store for every race run we can see in the Form King feed. Every card pull
explodes each runner's past runs (`pastEvents`, up to 12 per horse) into the
`runs` table, so the history grows by roughly 1,000 runs per meeting pulled.

Backends
--------
- Postgres (Supabase): set DATABASE_URL (env var or .streamlit/secrets.toml).
  Tables live in the `edge` schema so nothing in `public` is touched.
- SQLite fallback: `history.db` next to this file when DATABASE_URL is unset,
  so the harvester and tests run anywhere with no setup.

All writes are upserts that only fill gaps or take newer non-null values, so
re-pulling a card never duplicates a run or wipes a value with a blank.
"""

import os
import sqlite3
from pathlib import Path

SQLITE_PATH = Path(__file__).resolve().parent / "history.db"
PG_SCHEMA = "edge"

# Column lists drive both the DDL and the upserts. (name, type)
TABLES = {
    "raw_payloads": {
        "key": ["endpoint", "ref", "pulled_at"],
        "cols": [("endpoint", "TEXT"), ("ref", "TEXT"), ("pulled_at", "TEXT"),
                 ("body_zlib", "BYTEA")],
    },
    "meetings": {
        "key": ["meeting_id"],
        "cols": [("meeting_id", "TEXT"), ("meeting_date", "TEXT"), ("track", "TEXT"),
                 ("state", "TEXT"), ("going", "TEXT"), ("going_number", "INTEGER"),
                 ("rail", "TEXT"), ("rail_metres", "REAL"), ("penetrometer", "TEXT"),
                 ("rainfall", "TEXT"), ("irrigation", "TEXT"), ("tab_meeting", "INTEGER"),
                 ("updated_at", "TEXT")],
    },
    "races": {
        "key": ["race_id"],
        "cols": [("race_id", "TEXT"), ("meeting_id", "TEXT"), ("race_date", "TEXT"),
                 ("track", "TEXT"), ("state", "TEXT"), ("race_number", "INTEGER"),
                 ("race_name", "TEXT"), ("distance", "INTEGER"), ("restrictions", "TEXT"),
                 ("class_band", "TEXT"), ("going", "TEXT"), ("rail", "TEXT"),
                 ("prize_money", "REAL"), ("field_size", "INTEGER"), ("jump_time", "TEXT"),
                 ("race_time_ms", "INTEGER"), ("betfair_market_id", "TEXT"),
                 ("tab_meeting", "INTEGER"), ("updated_at", "TEXT")],
    },
    "horses": {
        "key": ["horse_name"],
        "cols": [("horse_name", "TEXT"), ("breeding_id", "TEXT"), ("sire", "TEXT"),
                 ("dam", "TEXT"), ("dam_sire", "TEXT"), ("foal_date", "TEXT"),
                 ("sex", "TEXT"), ("country", "TEXT"), ("trainer", "TEXT"),
                 ("training_location", "TEXT"), ("last_seen", "TEXT")],
    },
    "runs": {
        "key": ["race_id", "horse_name"],
        # margin: winner = +winning margin (lengths), others = -lengths beaten.
        "cols": [("race_id", "TEXT"), ("horse_name", "TEXT"), ("runner_number", "INTEGER"),
                 ("barrier", "INTEGER"), ("weight", "REAL"), ("jockey", "TEXT"),
                 ("finish_pos", "INTEGER"), ("margin", "REAL"), ("field_size", "INTEGER"),
                 ("settle_pos", "INTEGER"), ("pos_800", "INTEGER"), ("pos_400", "INTEGER"),
                 ("sp", "REAL"), ("bsp", "REAL"), ("track_speed", "REAL"),
                 ("wfa_rating", "REAL"), ("lws", "REAL"), ("wfa_diff", "REAL"),
                 ("field_strength", "REAL"), ("race_in_prep", "INTEGER"),
                 ("race_in_career", "INTEGER"), ("days_since_prev", "INTEGER"),
                 ("stewards_comment", "TEXT"), ("gear", "TEXT"),
                 ("next_runs", "INTEGER"), ("next_wins", "INTEGER"), ("next_woe", "REAL"),
                 ("source", "TEXT"), ("updated_at", "TEXT"),
                 # Bookmaker price moves on the day (opening fluc -> ... -> SP) and tote.
                 ("open_fluc", "REAL"), ("top_fluc", "REAL"), ("flucs", "TEXT"), ("tote_win", "REAL")],
    },
    "trials": {
        # Jump-outs and official trials shown on a runner's card (before that race).
        "key": ["trial_id", "horse_name"],
        "cols": [("trial_id", "TEXT"), ("horse_name", "TEXT"), ("trial_date", "TEXT"), ("track", "TEXT"),
                 ("state", "TEXT"), ("distance", "INTEGER"), ("going", "TEXT"), ("trial_name", "TEXT"),
                 ("finish_pos", "INTEGER"), ("margin", "REAL"), ("field_size", "INTEGER"),
                 ("jockey", "TEXT"), ("time_ms", "INTEGER"), ("updated_at", "TEXT")],
    },
    "entries": {
        "key": ["race_id", "horse_name"],
        "cols": [("race_id", "TEXT"), ("horse_name", "TEXT"), ("saddlecloth", "INTEGER"),
                 ("barrier", "INTEGER"), ("weight", "REAL"), ("apprentice_claim", "REAL"),
                 ("jockey", "TEXT"), ("trainer", "TEXT"), ("race_in_prep", "INTEGER"),
                 ("days_since_run", "INTEGER"), ("distance_change", "TEXT"),
                 ("gear_changes", "TEXT"), ("scratched", "INTEGER"), ("emergency", "INTEGER"),
                 ("fk_exp", "REAL"), ("fk_peak", "REAL"), ("fk_peak12m", "REAL"),
                 ("fk_neural", "REAL"), ("profile_json", "TEXT"), ("updated_at", "TEXT")],
    },
    "odds_snapshots": {
        "key": ["race_id", "horse_name", "pulled_at"],
        "cols": [("race_id", "TEXT"), ("horse_name", "TEXT"), ("pulled_at", "TEXT"),
                 ("feed_timestamp", "TEXT"), ("avg_open", "REAL"), ("avg_now", "REAL"),
                 ("best_now", "REAL"), ("firm_or_drift", "REAL")],
    },
}

# Columns a later pull may overwrite even when the stored value is set (the rest
# only fill gaps). Results, odds and late changes move; history doesn't.
OVERWRITE = {
    "meetings": {"going", "going_number", "rail", "rail_metres", "penetrometer", "rainfall",
                 "irrigation", "updated_at"},
    "races": {"going", "rail", "field_size", "jump_time", "updated_at"},
    "horses": {"trainer", "training_location", "last_seen"},
    "runs": {"finish_pos", "margin", "settle_pos", "pos_800", "pos_400", "sp", "bsp",
             "open_fluc", "top_fluc", "flucs", "tote_win",
             "track_speed", "wfa_rating", "lws", "wfa_diff", "field_strength",
             "stewards_comment", "next_runs", "next_wins", "next_woe", "updated_at"},
    "entries": {"barrier", "weight", "apprentice_claim", "jockey", "scratched", "emergency",
                "fk_exp", "fk_peak", "fk_peak12m", "fk_neural", "profile_json", "updated_at",
                "gear_changes"},
}


def _cfg(name):
    if os.environ.get(name):
        return os.environ[name]
    try:
        import streamlit as st
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return None


class HistoryDB:
    """Thin wrapper so the same code runs on Postgres or SQLite."""

    def __init__(self, url=None, sqlite_path=None):
        url = url if url is not None else _cfg("DATABASE_URL")
        if url:
            url = url.strip().strip('"').strip("'")
            # Accept a string pasted without its scheme ("postgres.xxx:pw@host:5432/db").
            if "://" not in url and "@" in url:
                url = "postgresql://" + url
            import psycopg  # psycopg 3; only needed for Postgres
            self.kind = "postgres"
            self.conn = psycopg.connect(url, autocommit=False,
                                        options="-c search_path={}".format(PG_SCHEMA))
        else:
            self.kind = "sqlite"
            self.conn = sqlite3.connect(str(sqlite_path or SQLITE_PATH))
            self.conn.row_factory = sqlite3.Row

    # -- schema ---------------------------------------------------------------
    @staticmethod
    def ddl(kind="postgres"):
        """CREATE statements for every table (and the schema on Postgres)."""
        out = []
        if kind == "postgres":
            out.append("CREATE SCHEMA IF NOT EXISTS {}".format(PG_SCHEMA))
        for name, spec in TABLES.items():
            cols = []
            for col, typ in spec["cols"]:
                if kind == "sqlite" and typ == "BYTEA":
                    typ = "BLOB"
                if kind == "postgres" and typ == "REAL":
                    typ = "DOUBLE PRECISION"
                cols.append("{} {}".format(col, typ))
            cols.append("PRIMARY KEY ({})".format(", ".join(spec["key"])))
            prefix = PG_SCHEMA + "." if kind == "postgres" else ""
            out.append("CREATE TABLE IF NOT EXISTS {}{} ({})".format(prefix, name, ", ".join(cols)))
        # Columns added after a table was first created.
        for name, spec in TABLES.items():
            prefix = PG_SCHEMA + "." if kind == "postgres" else ""
            for col, typ in spec["cols"]:
                if kind == "postgres":
                    out.append("ALTER TABLE {}{} ADD COLUMN IF NOT EXISTS {} {}".format(
                        prefix, name, col, "DOUBLE PRECISION" if typ == "REAL" else typ))
        idx = [("runs", "horse_name"), ("runs", "race_in_prep"), ("races", "race_date"),
               ("races", "track"), ("entries", "horse_name"), ("odds_snapshots", "race_id"),
               ("races", "meeting_id"), ("trials", "horse_name")]
        for table, col in idx:
            prefix = PG_SCHEMA + "." if kind == "postgres" else ""
            out.append("CREATE INDEX IF NOT EXISTS {t}_{c}_idx ON {p}{t} ({c})".format(
                t=table, c=col, p=prefix))
        return out

    def ensure_schema(self):
        cur = self.conn.cursor()
        for stmt in self.ddl(self.kind):
            cur.execute(stmt)
        if self.kind == "sqlite":
            for name, spec in TABLES.items():
                have = {r[1] for r in cur.execute("PRAGMA table_info({})".format(name)).fetchall()}
                for col, typ in spec["cols"]:
                    if col not in have:
                        cur.execute("ALTER TABLE {} ADD COLUMN {} {}".format(name, col, "BLOB" if typ == "BYTEA" else typ))
        self.conn.commit()

    # -- writes ---------------------------------------------------------------
    def upsert(self, table, rows):
        """Insert rows; on key conflict fill gaps and refresh OVERWRITE columns."""
        if not rows:
            return 0
        spec = TABLES[table]
        cols = [c for c, _ in spec["cols"]]
        keys = spec["key"]
        over = OVERWRITE.get(table, set())
        sets = []
        for c in cols:
            if c in keys:
                continue
            if table == "runs" and c == "source":
                # A full past-run record outranks a partial one (placings/import).
                sets.append("source = CASE WHEN excluded.source = 'pastEvents' THEN excluded.source "
                            "ELSE COALESCE(runs.source, excluded.source) END")
            elif c in over:
                sets.append("{c} = COALESCE(excluded.{c}, {t}.{c})".format(c=c, t=table))
            else:
                sets.append("{c} = COALESCE({t}.{c}, excluded.{c})".format(c=c, t=table))
        ph = "%s" if self.kind == "postgres" else "?"
        sql = "INSERT INTO {t} ({cols}) VALUES ({vals}) ON CONFLICT ({keys}) DO {action}".format(
            t=table, cols=", ".join(cols), vals=", ".join([ph] * len(cols)),
            keys=", ".join(keys),
            action=("UPDATE SET " + ", ".join(sets)) if sets else "NOTHING")
        data = [tuple(r.get(c) for c in cols) for r in rows]
        cur = self.conn.cursor()
        cur.executemany(sql, data)
        return len(data)

    def query(self, sql, params=()):
        if self.kind == "postgres":
            sql = sql.replace("?", "%s")
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()

    def prune_raw(self, keep_days):
        """Delete raw payloads older than keep_days (they are the bulk of storage)."""
        if self.kind == "postgres":
            cur = self.conn.cursor()
            cur.execute("DELETE FROM raw_payloads WHERE pulled_at::timestamptz < now() - make_interval(days => %s)",
                        (int(keep_days),))
        else:
            self.conn.execute("DELETE FROM raw_payloads WHERE pulled_at < datetime('now', ?)",
                              ("-{} days".format(int(keep_days)),))

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


if __name__ == "__main__":
    for stmt in HistoryDB.ddl("postgres"):
        print(stmt + ";")
