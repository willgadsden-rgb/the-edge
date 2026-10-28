"""Phase 3 end-to-end test for PIE: Syndicate Execution, Staking, Alerts & CLV.

Runs the full live-execution flow against the mock Flemington card:
    1. Price the model and find qualifying value overlays.
    2. Generate and display the Telegram syndicate alert cards.
    3. Log the qualifying bets into bets_ledger.
    4. Demonstrate the scratching engine (real-time re-normalised fair prices).
    5. Simulate results + CLV and print the audited syndicate P&L ledger.

Mock data only (see CLAUDE.md). Usage: python run_phase3_test.py
"""

import ingest
import run_model
from database import get_connection
from rating_engine import calculate_0_to_100_score, generate_trajectory, trajectory_trend
from prep_engine import profile_runner
from staking_engine import calculate_mao
from scratching_engine import scratch_runner
from ledger_tracker import (
    find_qualifiers,
    log_recommended_bets,
    simulate_results_and_clv,
    print_syndicate_pnl,
)
import telegram_notifier


def _banner(step, title):
    line = "#" * 70
    print("\n" + line)
    print("# STEP {}: {}".format(step, title))
    print(line)


def _trend_str(horse_name, base_score):
    """Recompute the recent-form trend as a card-ready string."""
    trend = trajectory_trend(generate_trajectory(horse_name, base_score))
    tag = "UP" if trend > 0.1 else ("DN" if trend < -0.1 else "FLAT")
    return "{} {:+.1f}/run".format(tag, trend)


def main():
    print("=" * 70)
    print("  PIE :: PHASE 3 - SYNDICATE EXECUTION, STAKING, ALERTS & CLV")
    print("=" * 70)

    # Fresh, coherent card each run (also guarantees the Phase 3 columns exist).
    ingest.main()

    # -- Step 1: price the model and find qualifiers --------------------------
    _banner(1, "PRICE MODEL & FIND VALUE QUALIFIERS")
    run_model.main()

    conn = get_connection()
    try:
        # Per-race distance/class, needed to recompute the base rating for cards.
        race_meta = {
            r["race_id"]: (r["distance"], r["class_name"])
            for r in conn.execute("SELECT race_id, distance, class_name FROM races")
        }

        qualifiers = find_qualifiers(conn)
        print("\nFound {} qualifying +EV overlays "
              "(Edge >= 20%, price >= MAO):".format(len(qualifiers)))
        for q in qualifiers:
            print("  R{} {:<18} edge +{:.1f}%  stake ${:,.2f} (to win ${:.0f})  (MAO ${:.2f})".format(
                q["race_number"], q["horse_name"], q["edge_pct"],
                q["stake_dollars"], q["to_win"], q["mao"]))

        # -- Step 2: build and dispatch the Telegram alert cards --------------
        _banner(2, "SYNDICATE TELEGRAM ALERTS")
        alerts = []
        for q in qualifiers:
            distance, class_name = race_meta[q["race_id"]]
            base_score = calculate_0_to_100_score(
                # Re-derive base rating from stored runner attributes.
                conn.execute("SELECT wfa_rating FROM race_entries WHERE entry_id=?",
                             (q["entry_id"],)).fetchone()["wfa_rating"],
                q["weight"], distance, class_name)
            prep = profile_runner(q["horse_name"], _prep_run(conn, q["entry_id"]), base_score)
            alerts.append({
                "track_name": q["track_name"],
                "race_num": q["race_number"],
                "horse_name": q["horse_name"],
                "barrier": q["barrier"],
                "weight": q["weight"],
                "score_0_to_100": q["score_0_to_100"],
                "trend_str": _trend_str(q["horse_name"], base_score),
                "prep_status": prep["tag"],
                "market_odds": q["market_odds"],
                "fair_odds": q["fair_odds"],
                "edge_pct": q["edge_pct"],
                "mao": q["mao"],
                "stake_dollars": q["stake_dollars"],
                "to_win": q["to_win"],
            })
        telegram_notifier.send_alerts(alerts)

        # -- Step 3: log the bets ---------------------------------------------
        _banner(3, "LOG RECOMMENDED BETS -> bets_ledger")
        logged = log_recommended_bets(qualifiers, conn=conn)
        print("Logged {} bets into bets_ledger (open / unsettled).".format(logged))

        # -- Step 4: scratching demo -----------------------------------------
        _banner(4, "SCRATCHING ENGINE - REAL-TIME RE-NORMALISATION")
        target_race = conn.execute(
            "SELECT race_id, race_number FROM races ORDER BY race_number DESC LIMIT 1"
        ).fetchone()
        fav = conn.execute(
            """
            SELECT horse_name FROM race_entries
            WHERE race_id = ? AND scratched = 0 AND fair_odds IS NOT NULL
            ORDER BY fair_odds ASC LIMIT 1
            """,
            (target_race["race_id"],),
        ).fetchone()

        print("Scratching the Race {} favourite: {}\n".format(
            target_race["race_number"], fav["horse_name"]))
        result = scratch_runner(target_race["race_id"], fav["horse_name"], conn=conn)
        print("Removed {:.1f}% of the book. Re-normalised fair prices:".format(
            result["scratched"]["removed_prob"] * 100.0))
        print("  {:<18} {:>10} {:>10} {:>8} {:>10}".format(
            "Horse", "Old Fair", "New Fair", "Market", "New Edge"))
        print("  " + "-" * 58)
        for r in result["runners"]:
            print("  {:<18} {:>9} {:>9} {:>8} {:>+9.1f}%".format(
                r["horse_name"], "${:.2f}".format(r["old_fair_odds"]),
                "${:.2f}".format(r["new_fair_odds"]),
                "${:.2f}".format(r["market_odds"]), r["edge"] * 100.0))

        # -- Step 5: settle, CLV, audited P&L ---------------------------------
        _banner(5, "SIMULATE RESULTS, CLV & AUDITED SYNDICATE P&L")
        # Fixed seed keeps the simulated day reproducible for the demo.
        settled = simulate_results_and_clv(conn=conn, seed=24)
        print("Settled {} bets (simulated jump + finish).\n".format(settled))
        print_syndicate_pnl(conn=conn)
    finally:
        conn.close()


def _prep_run(conn, entry_id):
    return conn.execute(
        "SELECT prep_run_num FROM race_entries WHERE entry_id = ?",
        (entry_id,),
    ).fetchone()["prep_run_num"]


if __name__ == "__main__":
    main()
