"""Local natural-language -> SQL helper for the PIE dashboard (Phase 4).

A small, dependency-free rule-based generator. It is NOT an LLM: it maps a set
of sample questions and a few common patterns to parameter-free SELECT
statements, then runs them read-only against racing.db. Raw SELECT queries typed
by the user are allowed too, but every query is validated to be read-only first.
"""

import re
import sqlite3

from database import DB_PATH

# Tokens that must never appear - keeps the assistant strictly read-only.
FORBIDDEN = (
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "attach", "detach", "pragma", "vacuum", "reindex", "trigger", "grant",
)

SAMPLE_QUESTIONS = [
    "Find all 3rd-up runners with score > 70",
    "Show all +EV bets today",
    "List all value overlays (edge >= 20%)",
    "Top 5 rated runners overall",
    "Show the Race 2 field by score",
    "Which runners are 1st-up?",
    "Show the full bets ledger with P/L",
]

# Base projections shared by the generated runner / ledger queries.
RUNNER_BASE = (
    "SELECT r.race_number AS race, e.horse_name AS horse, e.barrier AS bar, "
    "e.weight AS wt, e.prep_run_num AS prep_run, COALESCE(p.prep_stage,'') AS prep_stage, "
    "e.score_0_to_100 AS score, e.fair_odds, e.market_odds, "
    "ROUND((e.market_odds/e.fair_odds - 1.0)*100, 1) AS edge_pct "
    "FROM race_entries e "
    "JOIN races r ON r.race_id = e.race_id "
    "LEFT JOIN horse_prep_profiles p ON p.horse_name = e.horse_name "
    "WHERE e.scratched = 0 AND e.fair_odds IS NOT NULL"
)

LEDGER_BASE = (
    "SELECT r.race_number AS race, e.horse_name AS horse, b.stake_dollars, "
    "b.taken_price, b.fair_price, b.bsp, b.clv_percent, b.result, b.profit_units "
    "FROM bets_ledger b "
    "JOIN race_entries e ON e.entry_id = b.entry_id "
    "JOIN races r ON r.race_id = e.race_id"
)

_WORD_TO_NUM = {
    "first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4, "fifth": 5, "5th": 5,
}


def _nth_up(text):
    """Return the prep-run number referenced by an 'Nth-up' phrase, or None."""
    m = re.search(r'(\d+)\s*(?:st|nd|rd|th)?[-\s]*up', text)
    if m:
        return int(m.group(1))
    for word, num in _WORD_TO_NUM.items():
        if word + "-up" in text or word + " up" in text:
            return num
    return None


def generate_sql(question):
    """Translate a natural-language question into a read-only SELECT string."""
    q = (question or "").strip()
    low = q.lower()
    if not low:
        return RUNNER_BASE + " ORDER BY e.score_0_to_100 DESC"

    # Allow a user to type raw SQL; it is still safety-checked before running.
    if low.startswith("select"):
        return q.rstrip(";")

    # Ledger / P&L intent.
    if any(k in low for k in ("bet", "ledger", "p&l", "pnl", "profit", "clv", "roi", "staked")):
        sql = LEDGER_BASE
        if "win" in low and "winning" in low or low.strip().endswith("wins"):
            sql += " WHERE b.result = 'WIN'"
        return sql + " ORDER BY b.bet_id"

    # Otherwise build a runner query.
    conditions = []
    order = " ORDER BY e.score_0_to_100 DESC"
    limit = ""

    nth = _nth_up(low)
    if nth is not None:
        if nth >= 5:
            conditions.append("e.prep_run_num >= 5")
        else:
            conditions.append("e.prep_run_num = {}".format(nth))

    m = re.search(r'(?:score|rating)\s*(>=|<=|>|<|=)\s*(\d+(?:\.\d+)?)', low)
    if m:
        conditions.append("e.score_0_to_100 {} {}".format(m.group(1), m.group(2)))

    if "+ev" in low or "overlay" in low or "value" in low:
        conditions.append("(e.market_odds/e.fair_odds - 1.0) >= 0.20")
    if "underlay" in low:
        conditions.append("(e.market_odds/e.fair_odds - 1.0) < 0")

    if "race 1" in low or "maiden" in low:
        conditions.append("r.race_number = 1")
    if "race 2" in low or "bm84" in low or "benchmark 84" in low:
        conditions.append("r.race_number = 2")

    m = re.search(r'top\s+(\d+)', low)
    if m:
        limit = " LIMIT {}".format(int(m.group(1)))
    elif any(k in low for k in ("top", "best", "highest")):
        limit = " LIMIT 10"

    where = (" AND " + " AND ".join(conditions)) if conditions else ""
    return RUNNER_BASE + where + order + limit


def is_safe_select(sql):
    """True only for a single read-only SELECT statement."""
    s = sql.strip().rstrip(";").strip()
    if ";" in s:  # no stacked statements
        return False
    if not s.lower().startswith("select"):
        return False
    lowered = s.lower()
    return not any(re.search(r'\b' + tok + r'\b', lowered) for tok in FORBIDDEN)


def run_query(sql):
    """Run a validated read-only SELECT. Returns (columns, rows).

    Opens racing.db in read-only mode so a malformed query can never mutate it.
    """
    if not is_safe_select(sql):
        raise ValueError("Only read-only SELECT queries are allowed.")

    uri = "file:{}?mode=ro".format(DB_PATH)
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return columns, rows
    finally:
        conn.close()


if __name__ == "__main__":
    for question in SAMPLE_QUESTIONS:
        sql = generate_sql(question)
        cols, rows = run_query(sql)
        print("Q:", question)
        print("  SQL:", sql)
        print("  -> {} rows".format(len(rows)))
