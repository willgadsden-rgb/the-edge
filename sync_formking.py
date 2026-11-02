"""Live result settlement for The Edge syndicate ledger (user_bets).

When official results land (race_entries.finish_pos populated from the live
Form King feed), settle every still-PENDING bet on that race from the real
outcome. There is no simulated settlement — a bet stays PENDING until its
runner has an official result.

Matching is by race + horse name (user_bets stores the race_entries race_id as
text). Winner (finish_pos == 1) -> WON, a scratched runner -> SCRATCHED (stake
returned), everyone else with a result -> LOST.
"""

from database import get_connection, ensure_schema


def settle_pending_bets(conn=None):
    """Settle PENDING user_bets whose runner now has an official result.

    Returns the number of bets settled this pass. Safe to call repeatedly: a bet
    with no result yet is left PENDING.
    """
    own = conn is None
    conn = conn or get_connection()
    settled = 0
    try:
        if own:
            try:
                ensure_schema(conn)   # tolerate a legacy DB without user_bets
            except Exception:
                pass
        pending = conn.execute("SELECT * FROM user_bets WHERE status = 'PENDING'").fetchall()
        for b in pending:
            row = conn.execute(
                "SELECT finish_pos, scratched, result_bsp FROM race_entries "
                "WHERE race_id = CAST(? AS INTEGER) AND horse_name = ?",
                (b["race_id"], b["horse_name"])).fetchone()
            # No result yet (unraced): leave it PENDING.
            if row is None or (row["finish_pos"] is None and not row["scratched"]):
                continue

            stake = b["stake"] or 0.0
            odds = b["odds_taken"] or 0.0
            if row["scratched"]:
                status, payout, pnl = "SCRATCHED", stake, 0.0           # stake returned
            elif row["finish_pos"] == 1:
                payout = stake * odds
                status, pnl = "WON", payout - stake
            else:
                status, payout, pnl = "LOST", 0.0, -stake

            conn.execute(
                "UPDATE user_bets SET status = ?, payout = ?, net_pnl = ?, bsp_settled = ? "
                "WHERE bet_id = ?",
                (status, round(payout, 2), round(pnl, 2), row["result_bsp"], b["bet_id"]))
            settled += 1
        conn.commit()
    finally:
        if own:
            conn.close()
    return settled


if __name__ == "__main__":
    print("Settled {} pending bet(s) from live results.".format(settle_pending_bets()))
