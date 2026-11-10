"""Publish the engine's view of each card for the website (Netlify).

For every Victorian card the harvester pulls, this works out, per runner:
  * the 0-100 score and the market-blended price (same maths as the app:
    rating_engine + pricing_engine + staking_engine),
  * the form rating in lengths vs the class par, ceiling, confidence and best
    prep stage (form_model over the history database),
  * the settling map and race tempo from real in-run positions,
  * the last runs with stewards' comments, and the result once it's run,
and writes it to public.edge_meetings / edge_races / edge_runners, which the
site reads with its public (read-only) key. No extra Form King credits: it
works on the cards harvest.py has already fetched.

The site can re-price on fresh odds itself: it gets each runner's model
probability (p_model) and the market weight, and repeats the blend.
"""

import datetime
import json
import re
from pathlib import Path

import angle_engine
import formking_client as fk
import speedmap_engine
import triggers_engine
from pricing_engine import calculate_blended_fair_prices, effective_odds, commission_for_state
from rating_engine import calculate_0_to_100_score, calculate_projected_score
from staking_engine import calculate_mao, calculate_stake, DEFAULT_MIN_EDGE
import plays
import upgrades

MARKET_WEIGHT = 0.70          # same default as the app's market anchoring
OVERLAY_EDGE = 0.20           # value flag: edge >= 20% and price at/above the minimum
VALUE_ODDS = (2.20, 18.00)    # ...and inside the odds band the app bets (roughies are noise)

FROZEN_AFTER_RESULT = ("projected", "signals", "p_model", "p_market", "p_blend", "fair_price",
                       "market_price", "best_price", "edge_pct", "mao", "value_flag", "stake",
                       "settle_rank", "map_zone", "map_lane", "map_tag", "form_gap_l", "ceiling_gap_l",
                       "form_confidence", "form_runs", "v2_static", "play_flag", "play_reasons",
                       "fade_flag", "form_rank", "play_checks")

# Set once, at the first pre-race publish, and never overwritten: the price and
# our numbers as they stood that morning, so the record can be graded honestly.
KEEP_FIRST = {"morning_price", "morning_fair", "morning_p", "morning_at"}

SITE_FUNCTIONS = Path(__file__).resolve().parent / "sql" / "site_functions.sql"

PUB_TABLES = {
    "edge_meetings": {
        "key": ["meeting_id"],
        "cols": [("meeting_id", "TEXT"), ("meeting_date", "TEXT"), ("track", "TEXT"),
                 ("state", "TEXT"), ("going", "TEXT"), ("rail", "TEXT"), ("penetrometer", "TEXT"),
                 ("rainfall", "TEXT"), ("race_count", "INTEGER"), ("published_at", "TEXT")],
    },
    "edge_races": {
        "key": ["race_id"],
        "cols": [("race_id", "TEXT"), ("meeting_id", "TEXT"), ("meeting_date", "TEXT"),
                 ("race_number", "INTEGER"), ("race_name", "TEXT"), ("distance", "INTEGER"),
                 ("class_name", "TEXT"), ("class_group", "TEXT"), ("form_par", "REAL"),
                 ("jump_time", "TEXT"), ("field_size", "INTEGER"), ("tempo", "TEXT"), ("lengths_per_point", "REAL"),
                 ("model_version", "TEXT"), ("v2_mkt", "REAL"), ("v2_fades", "INTEGER"),
                 ("leaders", "INTEGER"), ("market_weight", "REAL"), ("commission", "REAL"),
                 ("betfair_market_id", "TEXT"), ("result_in", "INTEGER"), ("published_at", "TEXT")],
    },
    "edge_runners": {
        "key": ["race_id", "horse_name"],
        "cols": [("race_id", "TEXT"), ("horse_name", "TEXT"), ("saddlecloth", "INTEGER"),
                 ("barrier", "INTEGER"), ("weight", "REAL"), ("apprentice_claim", "REAL"),
                 ("jockey", "TEXT"), ("trainer", "TEXT"), ("age", "INTEGER"), ("sex", "TEXT"),
                 ("sire", "TEXT"), ("career", "TEXT"), ("prep_run", "INTEGER"), ("prep_stage", "TEXT"),
                 ("best_stage", "TEXT"), ("days_since_run", "INTEGER"), ("distance_change", "TEXT"),
                 ("gear_changes", "TEXT"), ("base_score", "REAL"), ("projected", "REAL"),
                 ("signals", "TEXT"), ("form_gap_l", "REAL"), ("ceiling_gap_l", "REAL"),
                 ("form_confidence", "TEXT"), ("form_runs", "INTEGER"), ("form_badge", "TEXT"),
                 ("settle_rank", "INTEGER"), ("map_zone", "TEXT"), ("early_speed", "REAL"),
                 ("map_lane", "TEXT"), ("map_tag", "TEXT"), ("p_model", "REAL"), ("p_market", "REAL"),
                 ("p_blend", "REAL"), ("fair_price", "REAL"), ("market_price", "REAL"),
                 ("best_price", "REAL"), ("open_price", "REAL"), ("edge_pct", "REAL"), ("mao", "REAL"),
                 ("value_flag", "INTEGER"), ("stake", "REAL"), ("flucs", "TEXT"), ("last_runs", "TEXT"),
                 ("finish_pos", "INTEGER"), ("margin", "REAL"), ("result_bsp", "REAL"),
                 ("result_sp", "REAL"), ("result_rating", "REAL"), ("result_comment", "TEXT"),
                 ("published_at", "TEXT"), ("scratched", "INTEGER"), ("going_form", "TEXT"), ("v2_static", "REAL"),
                 # rider / stable / trials / class (straight from the feed)
                 ("jockey_win_pct", "REAL"), ("jockey_place_pct", "REAL"), ("jockey_rides", "INTEGER"),
                 ("trainer_win_pct", "REAL"), ("tj_form", "TEXT"), ("tj_win_pct", "REAL"), ("jh_form", "TEXT"),
                 ("jockey_track", "TEXT"), ("trainer_track", "TEXT"), ("first_starter", "INTEGER"),
                 ("fk_exp", "REAL"), ("fk_peak", "REAL"), ("fk_neural", "REAL"), ("trials", "TEXT"),
                 ("class_move", "TEXT"), ("class_move_pts", "REAL"), ("form_rank", "INTEGER"),
                 # plays / fades and the locked morning numbers
                 ("play_flag", "INTEGER"), ("play_reasons", "TEXT"), ("fade_flag", "INTEGER"), ("play_checks", "TEXT"),
                 ("morning_price", "REAL"), ("morning_fair", "REAL"), ("morning_p", "REAL"), ("morning_at", "TEXT"),
                 ("upgrade_up", "INTEGER"), ("upgrade_down", "INTEGER"), ("upgrade_note", "TEXT")],
    },
    # Paper-bet ledger: a row is written the first time a runner is flagged before
    # its race and never changed. kind = play | value | fade | top.
    "edge_paper_bets": {
        "key": ["race_id", "horse_name", "kind"],
        "cols": [("race_id", "TEXT"), ("horse_name", "TEXT"), ("kind", "TEXT"), ("meeting_date", "TEXT"),
                 ("track", "TEXT"), ("race_number", "INTEGER"), ("saddlecloth", "INTEGER"), ("flagged_at", "TEXT"),
                 ("price", "REAL"), ("fair_price", "REAL"), ("p", "REAL"), ("p_market", "REAL"),
                 ("model_version", "TEXT"), ("reasons", "TEXT")],
    },
    "edge_stars": {
        "key": ["horse_name"],
        "cols": [("horse_name", "TEXT"), ("score", "REAL"), ("career_starts", "INTEGER"), ("wins", "INTEGER"),
                 ("last_date", "TEXT"), ("last_track", "TEXT"), ("last_distance", "INTEGER"), ("last_class", "TEXT"),
                 ("last_pos", "INTEGER"), ("last_rating", "REAL"), ("prev_best", "REAL"), ("vs_par_l", "REAL"),
                 ("trend", "REAL"), ("next_wins", "INTEGER"), ("reasons", "TEXT"), ("ratings", "TEXT"),
                 ("sire", "TEXT"), ("trainer", "TEXT"), ("foal_date", "TEXT"), ("updated_at", "TEXT")],
    },
}

STAGES = {1: "1st-up", 2: "2nd-up", 3: "3rd-up", 4: "4th-up"}


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _tname(db, table):
    return ("public." + table) if db.kind == "postgres" else table


def ensure_pub_schema(db):
    cur = db.conn.cursor()
    for name, spec in PUB_TABLES.items():
        cols = []
        for col, typ in spec["cols"]:
            if db.kind == "postgres" and typ == "REAL":
                typ = "DOUBLE PRECISION"
            cols.append("{} {}".format(col, typ))
        cols.append("PRIMARY KEY ({})".format(", ".join(spec["key"])))
        cur.execute("CREATE TABLE IF NOT EXISTS {} ({})".format(_tname(db, name), ", ".join(cols)))
        # Columns added after a table was first created.
        for col, typ in spec["cols"]:
            if db.kind == "postgres":
                cur.execute("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} {}".format(
                    _tname(db, name), col, "DOUBLE PRECISION" if typ == "REAL" else typ))
            else:
                try:
                    cur.execute("ALTER TABLE {} ADD COLUMN {} {}".format(_tname(db, name), col, typ))
                except Exception:
                    pass
        if db.kind == "postgres":
            # The site reads these with Supabase's public key: allow SELECT only.
            # (Supabase grants anon write access on new public tables by default,
            # so RLS must be on with a read-only policy and writes revoked.)
            t = _tname(db, name)
            cur.execute("ALTER TABLE {} ENABLE ROW LEVEL SECURITY".format(t))
            cur.execute("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {} FROM anon, authenticated".format(t))
            cur.execute("GRANT SELECT ON {} TO anon, authenticated".format(t))
            cur.execute(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public' "
                "AND tablename = '{n}' AND policyname = 'site can read') THEN "
                "CREATE POLICY \"site can read\" ON {t} FOR SELECT TO anon, authenticated USING (true); "
                "END IF; END $$".format(n=name, t=t))
    if db.kind == "postgres":
        # Read-only RPCs the site uses for the horse page and the Pattern Lab.
        cur.execute(SITE_FUNCTIONS.read_text())
    db.commit()


def _upsert(db, table, rows, insert_only=False):
    """Replace each row by key (a publish is the latest snapshot), keeping the
    previous value of a column only when the new one is empty."""
    if not rows:
        return 0
    spec = PUB_TABLES[table]
    cols = [c for c, _ in spec["cols"]]
    keys = spec["key"]
    t = _tname(db, table)
    short = table
    sets = ", ".join(("{c} = COALESCE({s}.{c}, excluded.{c})" if c in KEEP_FIRST else
                      "{c} = COALESCE(excluded.{c}, {s}.{c})").format(c=c, s=short)
                     for c in cols if c not in keys)
    ph = "%s" if db.kind == "postgres" else "?"
    action = "NOTHING" if insert_only else "UPDATE SET " + sets
    sql = "INSERT INTO {t} AS {s} ({cols}) VALUES ({vals}) ON CONFLICT ({keys}) DO {action}".format(
        t=t, s=short, cols=", ".join(cols), vals=", ".join([ph] * len(cols)), keys=", ".join(keys), action=action)
    if db.kind == "sqlite":
        sql = sql.replace(" AS {} ".format(short), " ", 1)
    db.conn.cursor().executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
    return len(rows)


def _class_group(label):
    try:
        from form_model import class_group
        return class_group(label)
    except Exception:
        return None


def winning_margin(race_raw):
    """Winner's margin = the runner-up's beaten margin (horseResult gives the
    winner 0.0)."""
    for e in race_raw.get("entries") or []:
        hr = e.get("horseResult") or {}
        if fk._as_int(hr.get("finishPosition")) == 2:
            return fk._as_float(hr.get("margin"))
    return None


def _result_for(entry_raw, race_id, win_margin=None):
    """The runner's result for this race. Form King puts it on the card itself
    (entry.horseResult) once the race is run; the runner's past runs pick it up
    later with the rating and stewards report, which we add when present.
    Margin convention: winner +winning margin, others -lengths beaten."""
    hr = entry_raw.get("horseResult") or {}
    past = next((ev for ev in entry_raw.get("pastEvents") or []
                 if ev.get("raceId") == race_id and ev.get("finishPosition")), None)
    pos = fk._as_int(hr.get("finishPosition"))
    if not pos:
        return past
    m = fk._as_float(hr.get("margin"))
    margin = (win_margin if pos == 1 else (-abs(m) if m is not None else None))
    return {
        "finishPosition": pos, "margin": margin,
        "bsp": hr.get("betfairStartingPrice") or (past or {}).get("bsp"),
        "startingPrice": hr.get("startingPrice") or (past or {}).get("startingPrice"),
        "weightForAgeRating": (past or {}).get("weightForAgeRating"),
        "stewardsComment": (past or {}).get("stewardsComment"),
    }


def _last_runs(runs):
    out = []
    for r in (runs or [])[:8]:
        out.append({
            "date": fk._date_str(r.get("date")) if isinstance(r.get("date"), (int, float)) else r.get("date"),
            "track": r.get("track"), "dist": r.get("dist"), "going": r.get("going"),
            "pos": r.get("pos"), "field": r.get("nrun"), "margin": r.get("margin"),
            "rating": r.get("rating"), "prep": r.get("prep"), "sp": r.get("sp"), "bsp": r.get("bsp"),
            "settle": r.get("settle"), "jockey": r.get("jockey"), "comment": r.get("comment"),
            "class": r.get("class"), "rname": r.get("rname"), "next_wins": r.get("next_wins"),
            "next_runs": r.get("next_runs"), "pos800": r.get("pos800"), "pos400": r.get("pos400"),
            "wt": r.get("wt"), "barrier": r.get("barrier"), "rid": r.get("rid"), "mid": r.get("mid"),
        })
    return out


def publish_card(db, card, model=None, published_at=None):
    """Score, price and publish one Form King meeting card. Returns row counts."""
    published_at = published_at or _now_iso()
    mapped = fk._map_meeting(card)
    meeting = mapped["meeting"]
    cond = meeting.get("condition") or "Good"
    cond_word = cond.split()[0]
    track = meeting.get("track_name")
    mdate = meeting.get("meeting_date")
    raw_races = {r.get("number"): r for r in card.get("races") or []}

    m_rows = [{"meeting_id": card.get("id"), "meeting_date": mdate, "track": track,
               "state": card.get("state"), "going": cond, "rail": meeting.get("rail_position"),
               "penetrometer": meeting.get("penetrometer"), "rainfall": meeting.get("rainfall"),
               "race_count": len(mapped["races"]), "published_at": published_at}]
    r_rows, e_rows, paper = [], [], []

    for race in mapped["races"]:
        raw = raw_races.get(race["race_number"]) or {}
        race_id = raw.get("raceId") or "{}_R{}".format(card.get("id"), race["race_number"])
        raw_entries = {(e.get("horse") or {}).get("name"): e for e in raw.get("entries") or []}
        win_m = winning_margin(raw)
        entries = []
        for e in race["entries"]:
            d = dict(e)
            d["last5_json"] = json.dumps(e.get("last5") or [])
            d["runs_json"] = json.dumps(e.get("runs_all") or [])
            d["fk_json"] = json.dumps(e.get("fk_profile") or {})
            d["scratched"] = 0
            entries.append(d)
        if not entries:
            continue

        tmap = speedmap_engine.build_tactical_map(entries)["runners"]
        n_leaders = sum(1 for v in tmap.values() if v.get("is_leader_group"))
        tempo_tier, tempo_badge = speedmap_engine.classify_tempo(n_leaders, race.get("pace_pressure_index"))
        settling = angle_engine.settling_positions(entries)
        pace = triggers_engine.pace_signals(
            {e["horse_name"]: triggers_engine.speed_figure(e.get("last5") or []) for e in entries})
        race_obj = {"distance": race["distance"], "class_name": race["class_name"]}
        meet_obj = {"condition": cond, "track_name": track}

        scored = []
        for e in entries:
            last5 = e.get("last5") or []
            claim = e.get("apprentice_claim") or 0.0
            base = calculate_0_to_100_score(
                e["wfa_rating"], max(float(e["weight"]) - float(claim), 40.0), race["distance"],
                race["class_name"], last_ratings=[r.get("rating") for r in last5],
                barrier=e["barrier"], last_positions=[r.get("pos") for r in last5])
            signals = []
            pts = 0.0
            for a in angle_engine.calculate_angles(e, race_obj, meet_obj, settling.get(e["horse_name"], 99),
                                                   angle_engine.TRACK_BIAS_FAIR):
                pts += a["points"]; signals.append({"name": a["name"], "points": a["points"]})
            pp, pn = pace.get(e["horse_name"], (0.0, None))
            if pn:
                pts += pp; signals.append({"name": pn, "points": pp})
            wp, wn = triggers_engine.wet_form_signal(last5, cond_word)
            if wn:
                pts += wp; signals.append({"name": wn, "points": wp})
            tac = tmap.get(e["horse_name"], {})
            tp, tb = speedmap_engine.tempo_modifier(tempo_tier, tac.get("zone"))
            if tb:
                pts += tp; signals.append({"name": tb["name"], "points": tp})
            projected = calculate_projected_score(e["horse_name"], base, e["prep_run_num"], cond_word,
                                                  race["distance"], situational_points=pts)
            scored.append((e, base, projected, signals, tac))

        commission = commission_for_state(card.get("state"))
        book = calculate_blended_fair_prices(
            [{"id": e["horse_name"], "score": proj, "market_odds": e["market_odds"],
              "effective_odds": effective_odds(e["market_odds"], commission) if e["market_odds"] else None}
             for e, _, proj, _, _ in scored], market_weight=MARKET_WEIGHT)

        # Model v2 (fitted on results, see model_v2.py) replaces the 70/30 blend
        # once it has beaten the market on races it never saw. It needs a price
        # for every runner (the market is one of its inputs).
        v2 = getattr(model, "v2", None) if model is not None else None
        v3 = getattr(model, "v3", None) if model is not None else None
        v2_static, v2_on, mver = {}, False, "blend"
        priced = all((e.get("market_odds") or 0) > 1 for e, _, _, _, _ in scored)
        raw_restr = str(raw.get("restrictions") or "").upper()
        for cand, label in ((v3, "v3"), (v2, "v2")):
            if v2_on or not cand or not priced or not (cand.get("use_for_pricing") or cand.get("prices_fk_cards") or cand.get("validated")):
                continue
            try:
                import math
                import model_v2
                statics = {}
                for e, _, _, _, _ in scored:
                    prof = e.get("fk_profile") or {}
                    f = model_v2.runner_features(model, e["horse_name"], {
                        "distance": race["distance"], "going": cond, "class_label": race["class_name"],
                        "track": track, "race_date": mdate, "barrier": e.get("barrier"),
                        "field_size": len(scored), "prep": e.get("prep_run_num"),
                        "days_since": prof.get("days_since_run")})
                    if label == "v2":
                        statics[e["horse_name"]] = model_v2.static_logit(cand, f)
                    else:
                        import model_v3
                        c = _rec3((prof.get("form") or {}).get("career"))
                        f.update(model_v3.live_bf_features(
                            e.get("runs_all"), mdate, race["distance"], track, raw_restr.startswith("MDN"),
                            {t.lower() for t in fk.VIC_TRACKS}, (c[0], c[1]) if c else None))
                        f["has_fk"] = 1.0
                        statics[e["horse_name"]] = model_v3.static_score(cand, f)
                z = {e["horse_name"]: statics[e["horse_name"]] + cand["market_coef"] * math.log(1.0 / e["market_odds"])
                     for e, _, _, _, _ in scored}
                top = max(z.values())
                wts = {n: math.exp(v - top) for n, v in z.items()}
                tot = sum(wts.values())
                for e, _, _, _, _ in scored:
                    n = e["horse_name"]
                    p = wts[n] / tot
                    fair = round(1.0 / p, 2)
                    eff = effective_odds(e["market_odds"], commission)
                    book[n] = dict(book.get(n, {}), p_blended=p, my_price=fair,
                                   edge_pct=(eff / fair - 1.0) * 100.0)
                v2_static, v2_on, mver, v2 = statics, True, label, cand
            except Exception as exc:
                print("Model {} skipped for {}: {}".format(label, race_id, exc))

        par = None
        if model is not None:
            try:
                par = model.par(race["class_name"], track)[2]
            except Exception:
                par = None
        result_in = 0
        fms = {e["horse_name"]: (model.rate(e["horse_name"], race["distance"], cond, race["class_name"], track, mdate)
                                 if model else {}) for e, _, _, _, _ in scored}
        order = sorted((n for n, f in fms.items() if f.get("gap_l") is not None), key=lambda n: -fms[n]["gap_l"])
        form_rank = {n: i + 1 for i, n in enumerate(order)}
        top_name = max(book, key=lambda n: book[n].get("p_blended") or 0) if book else None
        band_today = plays.going_band(cond)
        fades_on = bool(v2_on and v2 and v2.get("fades_proven"))
        for e, base, proj, signals, tac in scored:
            name = e["horse_name"]
            b = book.get(name, {})
            fair = b.get("my_price")
            mkt = e["market_odds"]
            mao = calculate_mao(fair, DEFAULT_MIN_EDGE) if fair else None
            edge = (b.get("edge_pct") or 0.0) / 100.0 if b.get("edge_pct") is not None else None
            value = bool(edge is not None and edge >= OVERLAY_EDGE and mao and mkt and mkt >= mao
                         and VALUE_ODDS[0] <= mkt <= VALUE_ODDS[1])
            prof = e.get("fk_profile") or {}
            fm = fms.get(name) or {}
            best = model.best_stage(name) if model else None
            res = _result_for(raw_entries.get(name) or {}, race_id, win_m)
            result_in = result_in or (1 if res else 0)
            odds = (raw_entries.get(name) or {}).get("odds") or {}
            prep = e.get("prep_run_num") or 1
            lruns = _last_runs(e.get("runs_all"))
            gform = {k: (prof.get("form") or {}).get(k) for k in
                     ("good", "soft", "heavy", "synthetic", "dead", "slow", "fast", "todays_going")}
            cmove = cpts = None
            if model is not None and par and lruns and lruns[0].get("class"):
                try:
                    pl = model.par(lruns[0]["class"], lruns[0].get("track"))[2]
                    cmove, cpts = plays.class_move(par["par"], pl["par"] if pl else None)
                except Exception:
                    pass
            p_now, p_mkt = b.get("p_blended"), b.get("p_market")
            fade = plays.is_fade(p_now, p_mkt, mkt, fades_on)
            is_play, why, _miss = plays.play_check({
                "p": p_now, "p_market": p_mkt, "price": mkt, "fair": fair, "map_zone": tac.get("zone"),
                "map_tag": tac.get("tag"), "form_rank": form_rank.get(name), "form_conf": fm.get("confidence"),
                "going": plays.going_verdict(gform, band_today), "tags": plays.last_start_tags(lruns, race["distance"]),
                "fade": fade})
            if not res and mkt and fair:
                common = {"race_id": race_id, "horse_name": name, "meeting_date": mdate, "track": track,
                          "race_number": race["race_number"], "saddlecloth": e.get("saddlecloth"),
                          "flagged_at": published_at, "price": mkt, "fair_price": fair, "p": p_now,
                          "p_market": p_mkt, "model_version": mver}
                if is_play:
                    paper.append(dict(common, kind="play", reasons="; ".join(why)))
                if value:
                    paper.append(dict(common, kind="value", reasons="edge {:.0f}%".format((edge or 0) * 100)))
                if fade:
                    paper.append(dict(common, kind="fade", reasons="model {:.0f}% vs market {:.0f}%".format(
                        (p_now or 0) * 100, (p_mkt or 0) * 100)))
                if name == top_name:
                    paper.append(dict(common, kind="top", reasons="top of our book"))
            e_rows.append({
                "jockey_win_pct": prof.get("jockey_12m_win_pct"), "jockey_place_pct": prof.get("jockey_12m_place_pct"),
                "jockey_rides": prof.get("jockey_12m_rides"), "trainer_win_pct": prof.get("trainer_12m_win_pct"),
                "tj_form": prof.get("trainer_jockey"), "tj_win_pct": prof.get("trainer_jockey_win_pct"),
                "jh_form": prof.get("jockey_horse"), "jockey_track": prof.get("jockey_track"),
                "trainer_track": prof.get("trainer_track"), "first_starter": int(bool(prof.get("first_starter"))),
                "fk_exp": prof.get("fk_rating_exp"), "fk_peak": prof.get("fk_rating_peak"),
                "fk_neural": prof.get("fk_rating_neural"),
                "trials": json.dumps([dict(t, date=fk._date_str(t["date"]) if isinstance(t.get("date"), (int, float)) else t.get("date"))
                                      for t in (e.get("trials") or [])]),
                "class_move": cmove, "class_move_pts": cpts, "form_rank": form_rank.get(name),
                "play_flag": int(is_play), "play_reasons": "; ".join(why) if is_play else None, "fade_flag": int(fade),
                "play_checks": json.dumps({"ok": why, "miss": _miss}) if (p_now or 0) >= 0.20 else None,
                "morning_price": None if res else mkt, "morning_fair": None if res else fair,
                "morning_p": None if res else p_now, "morning_at": None if res else published_at,
                "race_id": race_id, "horse_name": name, "saddlecloth": e.get("saddlecloth"),
                "barrier": e["barrier"], "weight": e["weight"], "apprentice_claim": e.get("apprentice_claim"),
                "jockey": prof.get("jockey"), "trainer": prof.get("trainer"), "age": prof.get("age"),
                "sex": prof.get("sex"), "sire": prof.get("sire"),
                "career": (prof.get("form") or {}).get("career"),
                "going_form": json.dumps(gform),
                "prep_run": prep, "prep_stage": STAGES.get(prep, "5th-up+"), "best_stage": best,
                "days_since_run": prof.get("days_since_run"), "distance_change": prof.get("distance_change"),
                "gear_changes": prof.get("gear_changes"), "base_score": round(base, 1),
                "projected": proj, "signals": json.dumps(signals),
                "form_gap_l": fm.get("gap_l"), "ceiling_gap_l": fm.get("ceiling_gap_l"),
                "form_confidence": fm.get("confidence"), "form_runs": fm.get("runs_used"),
                "form_badge": fm.get("badge") or None,
                "settle_rank": tac.get("rank"), "map_zone": tac.get("zone"),
                "early_speed": e.get("_es10"), "map_lane": tac.get("lane_name"), "map_tag": tac.get("tag"),
                "p_model": b.get("p_model"), "p_market": b.get("p_market"), "p_blend": b.get("p_blended"),
                "fair_price": fair, "market_price": mkt, "best_price": fk._as_float(odds.get("bestNow")),
                "open_price": fk._as_float(odds.get("avgOpen")),
                "edge_pct": round(edge * 100, 1) if edge is not None else None, "mao": mao,
                "value_flag": int(value), "stake": calculate_stake(mkt)["dollars"] if (value and mkt) else None,
                "flucs": json.dumps(e.get("flucs") or []), "last_runs": json.dumps(lruns),
                "finish_pos": fk._as_int(res.get("finishPosition")) if res else None,
                "margin": fk._as_float(res.get("margin")) if res else None,
                "result_bsp": fk._as_float(res.get("bsp")) if res else None,
                "result_sp": fk._as_float(res.get("startingPrice")) if res else None,
                "result_rating": fk._as_float(res.get("weightForAgeRating")) if res else None,
                "result_comment": (res.get("stewardsComment") or None) if res else None,
                "published_at": published_at,
                "v2_static": round(v2_static[name], 5) if name in v2_static else None,
            })
            if res:
                # Race is over: keep the pre-race book (the upsert keeps the stored
                # value when the new one is empty), so the track record grades the
                # prices and flags we actually published before the jump.
                for k in FROZEN_AFTER_RESULT:
                    e_rows[-1][k] = None

        # Runners scratched since an earlier publish: flag them so the site drops
        # them from the map and the book (the mapping skips scratched runners, so
        # without this their old row would linger).
        for sname, se in raw_entries.items():
            if sname and se.get("scratched"):
                e_rows.append({"race_id": race_id, "horse_name": sname, "scratched": 1,
                               "saddlecloth": fk._as_int(se.get("number")), "barrier": fk._as_int(se.get("barrier")),
                               "published_at": published_at})

        betfair = next((x.get("id") for x in ((raw.get("thirdPartyIds") or {}).get("BETFAIR") or [])
                        if x.get("type") == "WIN"), None)
        r_rows.append({
            "race_id": race_id, "meeting_id": card.get("id"), "meeting_date": mdate,
            "race_number": race["race_number"], "race_name": raw.get("name"),
            "distance": race["distance"], "class_name": race["class_name"],
            "class_group": _class_group(race["class_name"]),
            "form_par": round(par["par"], 1) if par else None,
            "lengths_per_point": round(model.lengths_per_point(race["distance"]), 3) if model is not None else None,
            "jump_time": datetime.datetime.fromtimestamp(race["jump_time"] / 1000, datetime.timezone.utc).isoformat()
            if race.get("jump_time") else None,
            "field_size": len(scored), "tempo": tempo_tier, "leaders": n_leaders,
            "market_weight": MARKET_WEIGHT, "commission": commission, "betfair_market_id": betfair,
            "result_in": result_in, "published_at": published_at,
            "model_version": mver, "v2_mkt": v2["market_coef"] if v2_on else None,
            "v2_fades": 1 if fades_on else 0,
        })

    for row in e_rows:
        row.setdefault("scratched", 0)

    # Read every last start against the day it was run: a horse that beat the
    # bias is better than its placing, one that got every favour is worse.
    try:
        parsed = {}
        rids = []
        for row in e_rows:
            if not row.get("last_runs"):
                continue
            runs = json.loads(row["last_runs"])
            parsed[id(row)] = runs
            rids.extend(r.get("rid") for r in runs)
        ctx = upgrades.load_context(db, rids)
        for row in e_rows:
            runs = parsed.get(id(row))
            if runs is None:
                continue
            summary = upgrades.annotate(runs, ctx)
            row["last_runs"] = json.dumps(runs)
            row["upgrade_up"] = summary["up"]
            row["upgrade_down"] = summary["down"]
            row["upgrade_note"] = summary["summary"]
    except Exception as exc:
        print("last-start upgrades skipped: {}".format(exc))
    counts = {"edge_meetings": _upsert(db, "edge_meetings", m_rows),
              "edge_races": _upsert(db, "edge_races", r_rows),
              "edge_runners": _upsert(db, "edge_runners", e_rows)}
    _upsert(db, "edge_paper_bets", paper, insert_only=True)
    db.commit()
    return counts


def _rec3(text):
    m = re.match(r"^(\d+):(\d+)-(\d+)-(\d+)", str(text or ""))
    return tuple(int(x) for x in m.groups()) if m else None


def publish_stars(db, model, today=None):
    """Rebuild the Rising Stars list (public.edge_stars) from the history."""
    import stars
    try:
        horses = {r[0]: {"sire": r[1], "trainer": r[2], "foal_date": r[3]}
                  for r in db.query("SELECT horse_name, sire, trainer, foal_date FROM horses")}
    except Exception:
        db.conn.rollback()
        horses = {}
    rows = stars.find_stars(model, today, horses)
    now = _now_iso()
    for r in rows:
        r["updated_at"] = now
    db.conn.cursor().execute("DELETE FROM {}".format(_tname(db, "edge_stars")))
    _upsert(db, "edge_stars", rows)
    db.commit()
    return len(rows)


def load_model(db):
    """The form model over the history database, or None if it can't load."""
    try:
        import form_model
        hist = form_model.load_history(db)
        if not len(hist):
            return None
        m = form_model.FormModel(hist)
        try:
            import model_v2
            m.v2 = model_v2.load(db)
            m.v3 = model_v2.load(db, "v3")
        except Exception:
            m.v2 = m.v3 = None
        return m
    except Exception as exc:
        print("Form model unavailable: {}".format(re.sub(r":[^:@\s]+@", ":****@", str(exc))))
        return None
