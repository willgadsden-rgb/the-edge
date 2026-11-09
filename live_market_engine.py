"""Live betting market engine & fluc tracker for The Edge (Phase 4).

Tracks price fluctuation history in SQLite (market_flucs), computes firm/drift
trends, renders fluc strings, and assigns market-sentiment badges. Price history
comes from the Form King card's real `flucs` series; nothing is simulated.
"""

import json
import time

from database import get_connection, ensure_schema

STEAMER_THRESHOLD = 0.12   # firmed >= 12% from opening
DRIFTER_THRESHOLD = 0.15   # drifted >= 15% from opening
MIN_PRICE = 1.04


def seed_if_empty(conn):
    """Record the REAL Form King price history for any runner with no flucs:
    each point of the card's `flucs` series (time, price), then the current
    average price. Nothing is simulated."""
    ensure_schema(conn)
    now = time.time()
    rows = conn.execute(
        "SELECT entry_id, market_odds, flucs_json FROM race_entries "
        "WHERE scratched = 0 AND market_odds IS NOT NULL"
    ).fetchall()
    for r in rows:
        exists = conn.execute(
            "SELECT 1 FROM market_flucs WHERE entry_id = ? LIMIT 1", (r["entry_id"],)
        ).fetchone()
        if exists:
            continue
        try:
            flucs = json.loads(r["flucs_json"] or "[]") or []
        except Exception:
            flucs = []
        for f in flucs:
            price, t = f.get("price"), f.get("time")
            if isinstance(price, (int, float)) and price > 1.0:
                ts = t / 1000.0 if isinstance(t, (int, float)) else now
                conn.execute("INSERT INTO market_flucs (entry_id, ts, price) VALUES (?, ?, ?)",
                             (r["entry_id"], ts, price))
        conn.execute("INSERT INTO market_flucs (entry_id, ts, price) VALUES (?, ?, ?)",
                     (r["entry_id"], now, r["market_odds"]))
    conn.commit()


def current_price(conn, entry_id):
    row = conn.execute(
        "SELECT price FROM market_flucs WHERE entry_id = ? ORDER BY ts DESC, fluc_id DESC LIMIT 1",
        (entry_id,)).fetchone()
    return row["price"] if row else None


def history(conn, entry_id):
    rows = conn.execute(
        "SELECT price FROM market_flucs WHERE entry_id = ? ORDER BY ts ASC, fluc_id ASC",
        (entry_id,)).fetchall()
    return [r["price"] for r in rows]


def market_summary(conn, entry_id):
    """Return opening/current price, fluc string and sentiment for a runner."""
    prices = history(conn, entry_id)
    if not prices:
        return None
    opening, current = prices[0], prices[-1]
    pct = (current - opening) / opening if opening else 0.0   # + drift, - firm
    firm = -pct

    if firm >= STEAMER_THRESHOLD:
        sentiment, label = "steamer", "🔥 STEAMER"
    elif pct >= DRIFTER_THRESHOLD:
        sentiment, label = "drifter", "❄️ DRIFTER"
    else:
        sentiment, label = "stable", "• STABLE"

    trail = prices[-4:] if len(prices) > 4 else prices
    fluc = " ➔ ".join("${:.2f}".format(p) for p in trail) + " ({:+.0f}%)".format(pct * 100)

    return {"opening": opening, "current": current, "history": prices,
            "pct": pct, "firm": firm, "sentiment": sentiment,
            "sentiment_label": label, "fluc_string": fluc}


def summaries_for_race(conn, race_id):
    """Return {entry_id: market_summary} for a race's active runners."""
    seed_if_empty(conn)
    out = {}
    for r in conn.execute(
            "SELECT entry_id FROM race_entries WHERE race_id = ? AND scratched = 0", (race_id,)):
        s = market_summary(conn, r["entry_id"])
        if s:
            out[r["entry_id"]] = s
    return out


if __name__ == "__main__":
    conn = get_connection()
    try:
        seed_if_empty(conn)
        row = conn.execute(
            "SELECT entry_id FROM race_entries WHERE scratched = 0 LIMIT 1").fetchone()
        print(market_summary(conn, row["entry_id"]))
    finally:
        conn.close()
