"""CLV ledger + settlement for The Edge - Target-Profit ($) model.

Logs qualifying value overlays into bets_ledger and prints an audited P&L in AUD
dollars. Results and CLV come only from official Form King results
(sync_formking.py); nothing is simulated.

Qualifying bet = value overlay with Edge >= 20% AND market price at/above MAO
(not VOID). Stake is the To-Win-$100 target-profit amount.
"""

from database import get_connection, ensure_schema
from staking_engine import calculate_stake, calculate_mao, is_void, TARGET_PROFIT

OVERLAY_EDGE = 0.20


def find_qualifiers(conn):
    """Scan all active (un-scratched, priced) runners and return qualifiers.

    Each qualifier dict carries the numbers the alert, staking and ledger layers
    all need, with the stake expressed in dollars (To-Win $100).
    """
    rows = conn.execute(
        """
        SELECT e.entry_id, e.race_id, e.horse_name, e.barrier, e.weight,
               e.score_0_to_100, e.fair_odds, e.market_odds,
               r.race_number, m.track_name
        FROM race_entries e
        JOIN races r    ON r.race_id = e.race_id
        JOIN meetings m ON m.meeting_id = r.meeting_id
        WHERE e.scratched = 0 AND e.fair_odds IS NOT NULL AND e.market_odds IS NOT NULL
        ORDER BY e.race_id, e.entry_id
        """
    ).fetchall()

    qualifiers = []
    for r in rows:
        fair, market = r["fair_odds"], r["market_odds"]
        edge = (market / fair) - 1.0
        stake = calculate_stake(market)
        mao = calculate_mao(fair)
        void = is_void(market, fair)

        if edge >= OVERLAY_EDGE and stake["bet"] and not void:
            qualifiers.append({
                "entry_id": r["entry_id"],
                "race_id": r["race_id"],
                "race_number": r["race_number"],
                "track_name": r["track_name"],
                "horse_name": r["horse_name"],
                "barrier": r["barrier"],
                "weight": r["weight"],
                "score_0_to_100": r["score_0_to_100"],
                "fair_odds": fair,
                "market_odds": market,
                "model_prob": 1.0 / fair,
                "edge": edge,
                "edge_pct": edge * 100.0,
                "mao": mao,
                "stake_dollars": stake["dollars"],
                "to_win": stake["to_win"],
            })
    return qualifiers


def log_recommended_bets(qualifiers=None, conn=None):
    """Record qualifying overlays into bets_ledger as open (unsettled) bets."""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        ensure_schema(conn)
        if qualifiers is None:
            qualifiers = find_qualifiers(conn)

        for q in qualifiers:
            conn.execute(
                """
                INSERT INTO bets_ledger
                    (entry_id, taken_price, fair_price, stake_dollars,
                     bsp, clv_percent, profit_units, result)
                VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL)
                """,
                (q["entry_id"], q["market_odds"], q["fair_odds"], q["stake_dollars"]),
            )
        conn.commit()
        return len(qualifiers)
    finally:
        if own_conn:
            conn.close()


def print_syndicate_pnl(conn=None):
    """Print the audited performance table from bets_ledger, in dollars."""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT b.result, b.stake_dollars, b.profit_units, b.clv_percent,
                   b.taken_price, b.bsp, e.horse_name
            FROM bets_ledger b
            JOIN race_entries e ON e.entry_id = b.entry_id
            WHERE b.result IS NOT NULL
            ORDER BY b.bet_id
            """
        ).fetchall()

        graded = [r for r in rows if r["result"] in ("WIN", "LOSS")]
        voids = [r for r in rows if r["result"] == "VOID"]

        total_bets = len(graded)
        wins = sum(1 for r in graded if r["result"] == "WIN")
        total_staked = sum(r["stake_dollars"] for r in graded)
        total_pl = sum(r["profit_units"] for r in graded)
        clvs = [r["clv_percent"] for r in graded if r["clv_percent"] is not None]
        avg_clv = sum(clvs) / len(clvs) if clvs else 0.0
        clv_beat = sum(1 for c in clvs if c > 0)

        strike = (wins / total_bets * 100.0) if total_bets else 0.0
        roi = (total_pl / total_staked * 100.0) if total_staked else 0.0
        beat_rate = (clv_beat / len(clvs) * 100.0) if clvs else 0.0

        width = 56
        print("=" * width)
        print("  THE EDGE :: AUDITED P&L LEDGER  (To-Win ${:.0f} model)".format(TARGET_PROFIT))
        print("=" * width)
        print("  {:<34}{:>20}".format("Total Bets:", total_bets))
        print("  {:<34}{:>20}".format("Winning Bets:", wins))
        print("  {:<34}{:>19.1f}%".format("Strike Rate:", strike))
        print("-" * width)
        print("  {:<34}{:>19}".format("Total Staked:", "${:,.2f}".format(total_staked)))
        print("  {:<34}{:>19}".format("Total Profit/Loss:", "${:+,.2f}".format(total_pl)))
        print("  {:<34}{:>19.1f}%".format("Return on Investment (ROI):", roi))
        print("-" * width)
        print("  {:<34}{:>18.2f}%".format("Average Closing Line Value (CLV):", avg_clv))
        print("  {:<34}{:>19.1f}%".format("CLV Beat Rate:", beat_rate))
        if voids:
            print("-" * width)
            print("  {:<34}{:>20}".format("Voided (scratched) bets:", len(voids)))
        print("=" * width)

        if graded:
            print()
            print("  {:<18} {:>6} {:>7} {:>7} {:>8} {:>10}".format(
                "Horse", "Result", "Taken", "BSP", "CLV%", "P/L ($)"))
            print("  " + "-" * 62)
            for r in graded:
                print("  {:<18} {:>6} {:>7} {:>7} {:>+7.1f}% {:>10}".format(
                    r["horse_name"], r["result"],
                    "${:.2f}".format(r["taken_price"]),
                    "${:.2f}".format(r["bsp"]) if r["bsp"] else "-",
                    r["clv_percent"] if r["clv_percent"] is not None else 0.0,
                    "${:+,.2f}".format(r["profit_units"])))
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    n = log_recommended_bets()
    print("Logged {} bets".format(n))
    print_syndicate_pnl()
