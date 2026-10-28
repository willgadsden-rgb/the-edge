"""Full system integrity audit for The Edge.

Rebuilds a clean mock card + settled ledger, then runs a diagnostic across every
module and prints a PASS/FAIL report. Mock data only (see CLAUDE.md).

Usage:  python system_audit.py
"""

import contextlib
import io

import ingest
import run_model
import ledger_tracker
import telegram_notifier
import nl_sql
import live_market_engine as lme
import angle_engine
import speedmap_engine as sm
import custom_rules as cr
import intraday_engine as ie
import weather_engine as we
import exotics_engine as ex
from database import get_connection, geometry_for, par_for
from pricing_engine import renormalize_after_scratching, fair_book_from_scores
from staking_engine import calculate_stake, calculate_mao, is_void, TARGET_PROFIT
from rating_engine import calculate_projected_score, classify_trajectory, clamp_modifier
from prep_engine import profile_runner

RESULTS = []


def check(name, fn):
    """Run one check; record PASS/FAIL plus a short detail string."""
    try:
        ok, detail = fn()
    except Exception as exc:  # a thrown check is a failure
        ok, detail = False, "exception: {}".format(exc)
    RESULTS.append((name, ok, detail))


# -- individual checks --------------------------------------------------------
EXPECTED = {
    "meetings": ["meeting_id", "track_id", "track_name", "rail_position", "condition", "track_variant"],
    "races": ["race_id", "meeting_id", "race_number", "distance", "class_name", "pace_pressure_index"],
    "race_entries": ["entry_id", "race_id", "horse_name", "barrier", "weight", "prep_run_num",
                     "wfa_rating", "speed_rating", "score_0_to_100", "fair_odds", "market_odds", "scratched"],
    "horse_prep_profiles": ["horse_name", "prep_stage", "starts", "wins", "avg_score"],
    "bets_ledger": ["bet_id", "entry_id", "taken_price", "fair_price", "bsp", "clv_percent",
                    "profit_units", "stake_dollars", "result"],
    "market_flucs": ["fluc_id", "entry_id", "ts", "price"],
}


def chk_schema():
    conn = get_connection()
    try:
        missing = []
        for table, cols in EXPECTED.items():
            have = {r["name"] for r in conn.execute("PRAGMA table_info({})".format(table))}
            for c in cols:
                if c not in have:
                    missing.append("{}.{}".format(table, c))
        return (not missing, "all {} tables/columns present".format(len(EXPECTED))
                if not missing else "missing: " + ", ".join(missing))
    finally:
        conn.close()


def chk_fair_book():
    conn = get_connection()
    try:
        worst = 0.0
        for row in conn.execute("SELECT race_id FROM races"):
            rid = row["race_id"]
            fairs = [r["fair_odds"] for r in conn.execute(
                "SELECT fair_odds FROM race_entries WHERE race_id=? AND scratched=0 AND fair_odds IS NOT NULL",
                (rid,))]
            book = sum(1.0 / f for f in fairs)
            worst = max(worst, abs(book - 1.0))
        return (worst < 0.01, "max book deviation {:.4f} from 1.0000".format(worst))
    finally:
        conn.close()


def chk_prep_peak():
    # Deterministic: Desert Mirage is a genuine 3rd-up target peak in the mock field.
    p = profile_runner("Desert Mirage", 3, 42.0)
    keys_ok = all(k in p for k in ("is_peak_target", "prep_adjustment", "tag", "stage_scores"))
    bounded = -6.0 <= p["prep_adjustment"] <= 6.0
    return (keys_ok and bounded and p["is_peak_target"],
            "peak_target={} adj={:+.2f} tag={}".format(
                p["is_peak_target"], p["prep_adjustment"], p["tag"]))


def chk_scratch_renorm():
    probs = {1: 0.50, 2: 0.30, 3: 0.20}
    new = renormalize_after_scratching(probs, [3])
    total = sum(new.values())
    expected_1 = 0.50 / (1 - 0.20)
    ok = abs(total - 1.0) < 1e-9 and abs(new[1] - expected_1) < 1e-9 and 3 not in new
    return (ok, "renormalised book sums to {:.6f}; P1 {:.4f}->{:.4f}".format(
        total, probs[1], new[1]))


def chk_target_staking():
    stake = calculate_stake(5.0)["dollars"]          # 100 / (5-1) = 25
    win_profit = stake * (5.0 - 1.0)
    ok = abs(stake - 25.0) < 1e-6 and abs(win_profit - TARGET_PROFIT) < 1e-6
    return (ok, "odds $5.00 -> stake ${:.2f}, wins ${:.2f}".format(stake, win_profit))


def chk_mao():
    mao = calculate_mao(10.0)                          # 11.5
    ok = abs(mao - 11.5) < 1e-6 and is_void(11.0, 10.0) and not is_void(12.0, 10.0)
    return (ok, "MAO(10.00)=${:.2f}; $11.00 void={}, $12.00 void={}".format(
        mao, is_void(11.0, 10.0), is_void(12.0, 10.0)))


def chk_telegram():
    alert = {
        "track_name": "Flemington", "race_num": 1, "horse_name": "Audit Runner",
        "barrier": 3, "weight": 57.0, "score_0_to_100": 72.0, "trend_str": "UP +1.0/run",
        "prep_status": "[PEAK TARGET 3RD-UP]", "market_odds": 5.00, "fair_odds": 4.00,
        "edge_pct": 25.0, "mao": 4.60, "stake_dollars": 25.0, "to_win": 100,
    }
    card = telegram_notifier.format_alert_card(alert)
    with contextlib.redirect_stdout(io.StringIO()):
        mode = telegram_notifier.send_alerts([alert])
    ok = "THE EDGE" in card and "to win $100" in card and mode == "dry-run"
    return (ok, "card branded + dry-run dispatch (mode={})".format(mode))


def chk_clv_pnl():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT stake_dollars, profit_units, clv_percent, taken_price, bsp, result "
            "FROM bets_ledger WHERE result IN ('WIN','LOSS')").fetchall()
        if not rows:
            return (False, "no graded bets to audit")
        # Recompute CLV for one row and compare to the stored value.
        r = rows[0]
        recomputed = round(((r["taken_price"] / r["bsp"]) - 1.0) * 100.0, 2)
        clv_ok = abs(recomputed - r["clv_percent"]) < 0.05
        pl = sum(x["profit_units"] for x in rows)
        staked = sum(x["stake_dollars"] for x in rows)
        dollars = all(x["stake_dollars"] is not None for x in rows)
        return (clv_ok and dollars,
                "{} graded; staked ${:,.2f}; P/L ${:+,.2f}; CLV recompute matches".format(
                    len(rows), staked, pl))
    finally:
        conn.close()


def chk_nl_assistant():
    sql = nl_sql.generate_sql("Find all 3rd-up runners with score > 40")
    cols, data = nl_sql.run_query(sql)
    unsafe_blocked = not nl_sql.is_safe_select("DELETE FROM race_entries")
    return (len(cols) > 0 and unsafe_blocked,
            "query returned {} rows; write-SQL correctly blocked".format(len(data)))


def chk_geometry():
    straight = geometry_for("Flemington", 1200)
    bend = geometry_for("Flemington", 1600)
    ok = (straight["turn_direction"] == "straight"
          and bend["turn_direction"] == "left" and bend["run_to_turn_m"] == 600)
    return (ok, "1200m={}, 1600m bend@{}m {}".format(
        straight["turn_direction"], bend["run_to_turn_m"], bend["turn_direction"]))


def chk_benchmark_par():
    bm84 = par_for("Open Benchmark 84")
    maiden = par_for("Maiden Plate")
    g1 = par_for("Group 1 Classic")
    ok = abs(bm84 - 78.0) < 1e-6 and abs(maiden - 42.0) < 1e-6 and abs(g1 - 90.0) < 1e-6
    return (ok, "BM84 par={}, Maiden par={}, G1 par={}".format(bm84, maiden, g1))


def chk_projected_score():
    proj = calculate_projected_score("Desert Mirage", 42.0, 3, "Good")
    ok = isinstance(proj, float) and 0.0 <= proj <= 100.0
    return (ok, "projected score = {} (0-100, blends form+prep+condition)".format(proj))


def chk_live_market():
    conn = get_connection()
    try:
        lme.seed_if_empty(conn)
        before = conn.execute("SELECT COUNT(*) FROM market_flucs").fetchone()[0]
        lme.simulate_tick(conn, seed=1)
        after = conn.execute("SELECT COUNT(*) FROM market_flucs").fetchone()[0]
        eid = conn.execute("SELECT entry_id FROM race_entries WHERE scratched=0 LIMIT 1").fetchone()[0]
        summ = lme.market_summary(conn, eid)
        ok = (after > before and summ is not None
              and all(k in summ for k in ("opening", "current", "fluc_string", "sentiment_label")))
        return (ok, "{} flucs after a tick; sample sentiment '{}'".format(
            after, summ["sentiment_label"] if summ else "n/a"))
    finally:
        conn.close()


def chk_angle_triggers():
    weight_stop = angle_engine.check_weight_stopper(60.5, True)
    no_stop = angle_engine.check_weight_stopper(55.0, True)
    hangover = angle_engine.check_heavy_hangover("Good", "Heavy", 14)
    no_hangover = angle_engine.check_heavy_hangover("Good", "Good", 14)
    lead_suit = angle_engine.check_speed_map_bias(1, angle_engine.TRACK_BIAS_LEADER)
    swoop_suit = angle_engine.check_speed_map_bias(7, angle_engine.TRACK_BIAS_SWOOPER)
    dist_cond = angle_engine.check_distance_conditioner(2000, True, 400)
    mudlark = angle_engine.check_lightweight_mudlark(54.0, "Heavy", True)
    fires = (weight_stop and weight_stop["points"] == -1.5 and no_stop is None
             and hangover and hangover["points"] == -1.5 and no_hangover is None
             and lead_suit and lead_suit["points"] == 1.5
             and swoop_suit and swoop_suit["points"] == 1.5
             and dist_cond and dist_cond["points"] == 2.0
             and mudlark and mudlark["points"] == 2.0)
    return (bool(fires), "weight-stopper/heavy-hangover/bias/distance/mudlark all fire on "
                         "qualifying profiles; non-qualifying return None")


def chk_manual_override():
    # Manual override must raise the projected score and keep the book at 100%.
    base = calculate_projected_score("Shadow Dancer", 68.0, 3, "Good", 1600, 0.0, 0.0)
    bumped = calculate_projected_score("Shadow Dancer", 68.0, 3, "Good", 1600, 0.0, 5.0)
    raised = abs((bumped - base) - 5.0) < 1e-6
    book = fair_book_from_scores({1: 70.0, 2: 60.0, 3: 55.0})
    before = book[1]
    book2 = fair_book_from_scores({1: 78.0, 2: 60.0, 3: 55.0})  # bump runner 1
    total_ok = abs(sum(book2.values()) - 1.0) < 1e-9
    increased = book2[1] > before
    return (raised and total_ok and increased,
            "override +5 -> projected {:.1f}->{:.1f}; book re-normalised to 1.0, P1 {:.3f}->{:.3f}".format(
                base, bumped, before, book2[1]))


def chk_tactical_map():
    # Short run / straight: wide traps retained.
    lane_in = sm._lane(2, 8.0, sm.ZONE_HANDY, True, None, 10)      # fast inside -> rail
    lane_wide = sm._lane(10, 3.0, sm.ZONE_BACK, False, None, 10)   # slow wide -> 4-wide
    # Long run (>=350m) 600m slotting rule: wide backmarker eases to the rail;
    # only a pressing/handy runner caught wide stays 3-wide.
    slot = sm._lane(9, 3.0, sm.ZONE_BACK, False, 600, 10)
    caught = sm._lane(8, 6.0, sm.ZONE_HANDY, False, 600, 10)
    z_lead = sm._zone(1, 10, True)
    z_back = sm._zone(9, 10, False)
    t_3wnc = sm._tag(3, sm.ZONE_MIDFIELD, False)
    t_box = sm._tag(1, sm.ZONE_HANDY, False)
    t_duel = sm._tag(1, sm.ZONE_LEADER, True)
    tm = sm.build_tactical_map([{"horse_name": "X", "barrier": 1},
                                {"horse_name": "Y", "barrier": 9},
                                {"horse_name": "Z", "barrier": 5}])
    valid = all(r["lane"] in (1, 2, 3, 4) for r in tm["runners"].values())
    ok = (lane_in == 1 and lane_wide == 4 and slot == 1 and caught == 3
          and z_lead == sm.ZONE_LEADER and z_back == sm.ZONE_BACK and t_3wnc == sm.TAG_3WNC
          and t_box == sm.TAG_BOXSEAT and t_duel == sm.TAG_DUEL and valid)
    return (ok, "600m slotting: wide backmarker->Rail, pressing-wide->3-Wide; short-run traps retained; tags correct")


def chk_custom_rules():
    mgr = cr.RuleManager()
    rid = mgr.add_rule(cr.CustomRule("Lanes 4-7 (+2.5)", 2.5, "lane_range",
                                     {"min_lane": 4, "max_lane": 7}, cr.SCOPE_MEETING, [1, 2]))
    meeting_scope = len(mgr.get_active_rules(1)) == 1 and len(mgr.get_active_rules(2)) == 1
    mgr.add_rule(cr.CustomRule("3WNC (-2)", -2.0, "tactical_tag", {"tag": "3WNC"}, cr.SCOPE_THIS, [1]))
    race_scope = len(mgr.get_active_rules(1)) == 2 and len(mgr.get_active_rules(2)) == 1
    pts, badges = mgr.evaluate_runner_rules({"lane": 4, "tactical_tag": "3WNC", "barrier": 10}, 1)
    applied = abs(pts - 0.5) < 1e-9 and len(badges) == 2
    single_del = mgr.remove_rule(rid) and len(mgr.all_rules()) == 1
    wiped = mgr.clear_all_rules() == 1 and len(mgr.all_rules()) == 0
    ok = meeting_scope and race_scope and applied and single_del and wiped
    return (ok, "meeting/race scoping, +2.5-2.0=+0.5 applied, single delete & global wipe all pass")


def chk_pricing_under_rules():
    from pricing_engine import fair_book_from_scores
    base = fair_book_from_scores({1: 70.0, 2: 65.0, 3: 60.0})
    bumped = fair_book_from_scores({1: 72.5, 2: 65.0, 3: 60.0})   # a +2.5 custom-rule bump
    ok = abs(sum(bumped.values()) - 1.0) < 1e-9 and bumped[1] > base[1]
    return (ok, "book stays 100% under a custom-rule score change; P1 {:.3f}->{:.3f}".format(
        base[1], bumped[1]))


def chk_intraday():
    bonus = ie.intraday_modifier(4, True)
    tax = ie.intraday_modifier(1, True)
    off = ie.intraday_modifier(4, False)
    par = ie.benchmark_par_time(1200)
    ok = (bonus[0] == 1.5 and tax[0] == -1.5 and off[0] == 0.0 and par > 0)
    return (ok, "par_time(1200)={:.1f}s; TSV loop ok; gutter drift lane4 +1.5 / lane1-2 -1.5 / off when fair".format(par))


def chk_wind():
    bearing = we.bearing_for("Flemington")
    head = we.classify_wind({"speed_kmh": 25, "from_deg": bearing}, "Flemington")
    tail = we.classify_wind({"speed_kmh": 25, "from_deg": (bearing + 180) % 360}, "Flemington")
    drag = we.wind_modifier(head, {"settle_zone": "Leader", "tactical_tag": "Clear Run", "lane": 1})
    slip = we.wind_modifier(head, {"settle_zone": "Midfield", "tactical_tag": "Clear Run", "lane": 1})
    prop = we.wind_modifier(tail, {"settle_zone": "Leader", "tactical_tag": "Clear Run", "lane": 1})
    ok = (head["kind"] == "headwind" and tail["kind"] == "tailwind"
          and drag[0] == -2.0 and slip[0] == 1.5 and prop[0] == 1.5
          and abs(head["v_parallel"] - 25.0) < 0.1)
    return (ok, "V_parallel=+25 headwind; drag -2.0 (leader), slipstream +1.5 (covered), tailwind +1.5 (on-pace)")


def chk_exotics():
    s_ex, s_tri = ex.exotic_prob_sums({1: 0.5, 2: 0.3, 3: 0.15, 4: 0.05})
    fd = ex.fair_dividend(0.25)
    ok = abs(s_ex - 1.0) < 1e-9 and abs(s_tri - 1.0) < 1e-9 and abs(fd - 4.0) < 1e-6
    return (ok, "Harville exacta sum {:.6f}, trifecta sum {:.6f}; fair dividend(25%)=$4.00".format(s_ex, s_tri))


def chk_hangover_lifecycle():
    fires = angle_engine.check_heavy_hangover("Good", "Heavy", 10, 10, 0)
    expired = angle_engine.check_heavy_hangover("Good", "Heavy", 10, 10, 1)
    too_old = angle_engine.check_heavy_hangover("Good", "Heavy", 30, 10, 0)
    ok = fires and fires["points"] == -1.5 and expired is None and too_old is None
    return (ok, "fires -1.5 on the immediate 1st-up run; retired after 1 run; none beyond 21 days")


def chk_net_commission():
    from pricing_engine import effective_odds, commission_for_state
    eff = effective_odds(5.0, 0.08)
    eff_nsw = effective_odds(5.0, 0.10)
    ok = (abs(eff - 4.68) < 1e-6 and abs(eff_nsw - 4.60) < 1e-6
          and commission_for_state("NSW") == 0.10 and commission_for_state("VIC") == 0.08)
    return (ok, "effective $5.00 @8%=$4.68, @10% NSW=$4.60; state lookup correct")


def chk_track_geometry_stages():
    import math as _m
    g = geometry_for("Flemington", 1600)
    L1, R = g["run_to_turn_m"], g["turn_radius"]
    L2 = L1 + R * _m.pi / 2
    a1, a2 = sm.track_point(L1 - 0.01, 12, g), sm.track_point(L1 + 0.01, 12, g)
    b1, b2 = sm.track_point(L2 - 0.01, 12, g), sm.track_point(L2 + 0.01, 12, g)
    cont = (abs(a1[0] - a2[0]) < 0.2 and abs(a1[1] - a2[1]) < 0.2
            and abs(b1[0] - b2[0]) < 0.2 and abs(b1[1] - b2[1]) < 0.2)
    jump = sm.track_point(0, 0, g)
    home = sm.track_point(L2 + 150, 0, g)        # should run north up the home straight
    stages_ok = jump[0] < 10 and home[1] > R + 100 and sm.fan_lane(1, sm.ZONE_BACK, "", 9, 10) >= 4
    return (cont and stages_ok,
            "back straight -> bend -> home straight continuous; backmarkers fan wide off corner")


def chk_hard_cap():
    base = calculate_projected_score("Bold Horizon", 72.0, 3, "Good", 1600, 0.0, 0.0)
    huge = calculate_projected_score("Bold Horizon", 72.0, 3, "Good", 1600, 10.0, 0.0)
    neg = calculate_projected_score("Bold Horizon", 72.0, 3, "Good", 1600, -10.0, 0.0)
    cap_ok = abs((huge - base) - 2.5) < 1e-6 and abs((neg - base) + 2.5) < 1e-6
    clamp_ok = (clamp_modifier(10) == 2.5 and clamp_modifier(-10) == -2.5
                and clamp_modifier(1.2) == 1.2)
    return (cap_ok and clamp_ok,
            "situational +10 -> +2.5 cap, -10 -> -2.5 cap; clamp_modifier correct")


def chk_trajectory():
    cb = classify_trajectory([79, 76, 76, 75, 72])     # Coastal Breeze (newest-first)
    rising = classify_trajectory([80, 70, 68, 66, 64])  # genuine breakout
    easing = classify_trajectory([55, 62, 63, 64, 66])  # genuine collapse (non-metro)
    stable = classify_trajectory([73, 72, 74, 73, 72])  # tight band -> stable
    ok = (cb["label"] in ("STABLE", "RISING") and rising["label"] == "RISING"
          and easing["label"] == "EASING" and stable["label"] == "STABLE")
    return (ok, "Coastal Breeze [79,76,76,75,72] -> {}; breakout->RISING; collapse->EASING; "
                "tight band->STABLE".format(cb["label"]))


def main():
    print("Rebuilding a clean mock card + settled ledger for the audit...")
    with contextlib.redirect_stdout(io.StringIO()):
        ingest.main()
        run_model.main()
        ledger_tracker.log_recommended_bets()
        ledger_tracker.simulate_results_and_clv(seed=24)

    check("SQLite schema consistency", chk_schema)
    check("100% fair pricing normalization", chk_fair_book)
    check("Prep peak detection & adjustment", chk_prep_peak)
    check("Dynamic scratching re-normalization", chk_scratch_renorm)
    check("Target-Profit ($) staking model", chk_target_staking)
    check("Minimum Acceptable Odds (MAO) gating", chk_mao)
    check("Telegram formatting + dry-run dispatch", chk_telegram)
    check("CLV% and P&L ledger ($ denominated)", chk_clv_pnl)
    check("Natural-language AI DB assistant", chk_nl_assistant)
    check("Realistic track geometry defs", chk_geometry)
    check("Benchmark par-to-win lookup", chk_benchmark_par)
    check("Projected score (form+prep+cond)", chk_projected_score)
    check("Live market engine & fluc tracker", chk_live_market)
    check("Situational angle triggers", chk_angle_triggers)
    check("Manual override + 100% re-normalization", chk_manual_override)
    check("Tactical speed-map settling logic", chk_tactical_map)
    check("Custom rule scope / apply / delete / wipe", chk_custom_rules)
    check("100% fair pricing under custom rules", chk_pricing_under_rules)
    check("Intraday TSV & gutter drift triggers", chk_intraday)
    check("BOM wind vectors & headwind/tailwind", chk_wind)
    check("Harville exotic probability sums", chk_exotics)
    check("Heavy-hangover 1-run lifecycle expiry", chk_hangover_lifecycle)
    check("Net-of-commission effective odds", chk_net_commission)
    check("Syndicate hard cap (+/-2.5 modifiers)", chk_hard_cap)
    check("Form trajectory direction & stability band", chk_trajectory)
    check("Full track geometry (back/bend/home straight)", chk_track_geometry_stages)

    width = 72
    print("=" * width)
    print("  THE EDGE :: FULL SYSTEM INTEGRITY AUDIT")
    print("=" * width)
    passed = 0
    for name, ok, detail in RESULTS:
        flag = "PASS" if ok else "FAIL"
        passed += 1 if ok else 0
        print("  [{}]  {:<38} {}".format(flag, name, detail))
    print("-" * width)
    print("  {}/{} checks passed.".format(passed, len(RESULTS)))
    print("=" * width)
    if passed == len(RESULTS):
        print("  ✅ ALL SYSTEMS FULLY INTACT AND FUNCTIONAL.")
    else:
        print("  ❌ {} check(s) need attention.".format(len(RESULTS) - passed))
    print("=" * width)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
