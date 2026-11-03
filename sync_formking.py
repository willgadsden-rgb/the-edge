"""Live result settlement for The Edge syndicate ledger (user_bets).

When official results land (race_entries.finish_pos populated from the live
Form King feed), settle every still-PENDING bet on that race from the real
outcome. There is no simulated settlement — a bet stays PENDING until its
runner has an official result.

Matching is by race + horse name (user_bets stores the race_entries race_id as
text). Winner (finish_pos == 1) -> WON, a scratched runner -> SCRATCHED (stake
returned), everyone else with a result -> LOST.
"""

import datetime
import json
from zoneinfo import ZoneInfo

from database import get_connection, ensure_schema

MELBOURNE = ZoneInfo("Australia/Melbourne")


def _melb_date(epoch_ms):
    """Melbourne calendar date (YYYY-MM-DD) for an epoch-ms timestamp, or None."""
    if not isinstance(epoch_ms, (int, float)):
        return None
    return datetime.datetime.fromtimestamp(epoch_ms / 1000.0, MELBOURNE).date().isoformat()


def ingest_live_results(conn=None):
    """Populate real results for races that have already run TODAY.

    Form King has no results endpoint on the upcoming card, but once a race is
    run its outcome appears in each runner's pastEvents. So for every runner we
    look for a past run at THIS meeting's track dated today (Melbourne) and, when
    found, write its finishing position and Betfair SP onto the entry and mark the
    race completed. Strict live-only: nothing is fabricated — a race with no such
    runs in the feed yet simply stays open. Returns the number of entries filled.
    """
    own = conn is None
    conn = conn or get_connection()
    filled = 0
    try:
        today = datetime.datetime.now(MELBOURNE).date().isoformat()
        rows = conn.execute(
            "SELECT e.entry_id, e.last5_json, e.finish_pos, m.track_name "
            "FROM race_entries e JOIN races r ON r.race_id = e.race_id "
            "JOIN meetings m ON m.meeting_id = r.meeting_id "
            "WHERE e.scratched = 0 AND e.finish_pos IS NULL AND e.last5_json IS NOT NULL").fetchall()
        for e in rows:
            try:
                runs = json.loads(e["last5_json"] or "[]")
            except Exception:
                continue
            for run in runs:
                if run.get("track") == e["track_name"] and _melb_date(run.get("date")) == today \
                        and isinstance(run.get("pos"), int):
                    conn.execute(
                        "UPDATE race_entries SET finish_pos = ?, result_bsp = ?, beaten_lengths = ? "
                        "WHERE entry_id = ?",
                        (run["pos"], run.get("bsp"), run.get("margin"), e["entry_id"]))
                    filled += 1
                    break
        if filled:
            conn.execute(
                "UPDATE races SET completed = 1 WHERE race_id IN "
                "(SELECT DISTINCT race_id FROM race_entries WHERE finish_pos IS NOT NULL)")
        conn.commit()
    finally:
        if own:
            conn.close()
    return filled


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

            # Closing-line value: how the price taken compares to the Betfair SP.
            # clv% = (odds_taken / official_bsp - 1) * 100 (positive = beat the close).
            bsp = row["result_bsp"]
            clv = round((odds / bsp - 1.0) * 100.0, 1) if (bsp and odds and not row["scratched"]) else None

            conn.execute(
                "UPDATE user_bets SET status = ?, payout = ?, net_pnl = ?, bsp_settled = ?, clv_percent = ? "
                "WHERE bet_id = ?",
                (status, round(payout, 2), round(pnl, 2), bsp, clv, b["bet_id"]))
            settled += 1
        conn.commit()
    finally:
        if own:
            conn.close()
    return settled


if __name__ == "__main__":
    print("Settled {} pending bet(s) from live results.".format(settle_pending_bets()))
