"""CLV ledger + settlement for The Edge - Target-Profit ($) model.

Logs qualifying value overlays into bets_ledger, simulates the race jump
(market movement toward fair price), simulates the official finish weighted by
model probabilities, computes Closing Line Value, and prints an audited P&L in
AUD dollars. Mock data only (see CLAUDE.md).

Qualifying bet = value overlay with Edge >= 20% AND market price at/above MAO
(not VOID). Stake is the To-Win-$100 target-profit amount.
"""

import random

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


def _simulate_winner(conn, race_id, rng):
    """Pick a winning entry_id for race_id, weighted by model probabilities."""
    rows = conn.execute(
        """
        SELECT entry_id, fair_odds FROM race_entries
        WHERE race_id = ? AND scratched = 0 AND fair_odds IS NOT NULL
        """,
        (race_id,),
    ).fetchall()
    ids = [r["entry_id"] for r in rows]
    weights = [1.0 / r["fair_odds"] for r in rows]
    total = sum(weights)
    probs = [w / total for w in weights]

    draw = rng.random()
    cumulative = 0.0
    for eid, p in zip(ids, probs):
        cumulative += p
        if draw <= cumulative:
            return eid
    return ids[-1]


def simulate_results_and_clv(conn=None, seed=7):
    """Settle every open bet: simulate BSP, finish, CLV and dollar profit.

    Profit on a winner = stake * (taken_price - 1) dollars (~= TARGET_PROFIT by
    construction); a loser forfeits the stake; a scratched runner is VOID with
    the stake returned.
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        ensure_schema(conn)
        rng = random.Random(seed)

        open_bets = conn.execute(
            """
            SELECT b.bet_id, b.entry_id, b.taken_price, b.fair_price, b.stake_dollars,
                   e.race_id, e.horse_name, e.scratched
            FROM bets_ledger b
            JOIN race_entries e ON e.entry_id = b.entry_id
            WHERE b.result IS NULL
            ORDER BY e.race_id, b.bet_id
            """
        ).fetchall()

        race_ids = sorted({b["race_id"] for b in open_bets})
        winners = {rid: _simulate_winner(conn, rid, rng) for rid in race_ids}

        settled = 0
        for b in open_bets:
            if b["scratched"]:
                conn.execute(
                    """
                    UPDATE bets_ledger
                    SET result = 'VOID', profit_units = 0.0, bsp = NULL, clv_percent = NULL
                    WHERE bet_id = ?
                    """,
                    (b["bet_id"],),
                )
                settled += 1
                continue

            taken, fair, stake = b["taken_price"], b["fair_price"], b["stake_dollars"]

            convergence = rng.uniform(0.5, 0.9)
            bsp = taken - convergence * (taken - fair)
            bsp = round(max(1.01, bsp), 2)
            clv = ((taken / bsp) - 1.0) * 100.0

            won = (b["entry_id"] == winners[b["race_id"]])
            result = "WIN" if won else "LOSS"
            profit = stake * (taken - 1.0) if won else -stake

            conn.execute(
                """
                UPDATE bets_ledger
                SET bsp = ?, clv_percent = ?, result = ?, profit_units = ?
                WHERE bet_id = ?
                """,
                (bsp, round(clv, 2), result, round(profit, 2), b["bet_id"]),
            )
            settled += 1

        conn.commit()
        return settled
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
    simulate_results_and_clv()
    print_syndicate_pnl()
