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

MARKET_WEIGHT = 0.70          # same default as the app's market anchoring
OVERLAY_EDGE = 0.20           # value flag: edge >= 20% and price at/above the minimum
VALUE_ODDS = (2.20, 18.00)    # ...and inside the odds band the app bets (roughies are noise)

FROZEN_AFTER_RESULT = ("projected", "signals", "p_model", "p_market", "p_blend", "fair_price",
                       "market_price", "best_price", "edge_pct", "mao", "value_flag", "stake",
                       "settle_rank", "map_zone", "map_lane", "map_tag", "form_gap_l", "ceiling_gap_l",
                       "form_confidence", "form_runs")

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
                 ("jump_time", "TEXT"), ("field_size", "INTEGER"), ("tempo", "TEXT"),
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
                 ("published_at", "TEXT")],
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


def _upsert(db, table, rows):
    """Replace each row by key (a publish is the latest snapshot), keeping the
    previous value of a column only when the new one is empty."""
    if not rows:
        return 0
    spec = PUB_TABLES[table]
    cols = [c for c, _ in spec["cols"]]
    keys = spec["key"]
    t = _tname(db, table)
    short = table
    sets = ", ".join("{c} = COALESCE(excluded.{c}, {s}.{c})".format(c=c, s=short)
                     for c in cols if c not in keys)
    ph = "%s" if db.kind == "postgres" else "?"
    sql = "INSERT INTO {t} AS {s} ({cols}) VALUES ({vals}) ON CONFLICT ({keys}) DO UPDATE SET {sets}".format(
        t=t, s=short, cols=", ".join(cols), vals=", ".join([ph] * len(cols)), keys=", ".join(keys), sets=sets)
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


def _result_for(entry_raw, race_id):
    """The runner's own result for this race, once it is in its past runs."""
    for ev in entry_raw.get("pastEvents") or []:
        if ev.get("raceId") == race_id and ev.get("finishPosition"):
            return ev
    return None


def _last_runs(runs):
    out = []
    for r in (runs or [])[:8]:
        out.append({
            "date": fk._date_str(r.get("date")) if isinstance(r.get("date"), (int, float)) else r.get("date"),
            "track": r.get("track"), "dist": r.get("dist"), "going": r.get("going"),
            "pos": r.get("pos"), "field": r.get("nrun"), "margin": r.get("margin"),
            "rating": r.get("rating"), "prep": r.get("prep"), "sp": r.get("sp"), "bsp": r.get("bsp"),
            "settle": r.get("settle"), "jockey": r.get("jockey"), "comment": r.get("comment"),
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
    r_rows, e_rows = [], []

    for race in mapped["races"]:
        raw = raw_races.get(race["race_number"]) or {}
        race_id = raw.get("raceId") or "{}_R{}".format(card.get("id"), race["race_number"])
        raw_entries = {(e.get("horse") or {}).get("name"): e for e in raw.get("entries") or []}
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

        par = None
        if model is not None:
            try:
                par = model.par(race["class_name"], track)[2]
            except Exception:
                par = None
        result_in = 0
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
            fm = model.rate(name, race["distance"], cond, race["class_name"], track, mdate) if model else {}
            best = model.best_stage(name) if model else None
            res = _result_for(raw_entries.get(name) or {}, race_id)
            result_in = result_in or (1 if res else 0)
            odds = (raw_entries.get(name) or {}).get("odds") or {}
            prep = e.get("prep_run_num") or 1
            e_rows.append({
                "race_id": race_id, "horse_name": name, "saddlecloth": e.get("saddlecloth"),
                "barrier": e["barrier"], "weight": e["weight"], "apprentice_claim": e.get("apprentice_claim"),
                "jockey": prof.get("jockey"), "trainer": prof.get("trainer"), "age": prof.get("age"),
                "sex": prof.get("sex"), "sire": prof.get("sire"),
                "career": (prof.get("form") or {}).get("career"),
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
                "flucs": json.dumps(e.get("flucs") or []), "last_runs": json.dumps(_last_runs(e.get("runs_all"))),
                "finish_pos": fk._as_int(res.get("finishPosition")) if res else None,
                "margin": fk._as_float(res.get("margin")) if res else None,
                "result_bsp": fk._as_float(res.get("bsp")) if res else None,
                "result_sp": fk._as_float(res.get("startingPrice")) if res else None,
                "result_rating": fk._as_float(res.get("weightForAgeRating")) if res else None,
                "result_comment": (res.get("stewardsComment") or None) if res else None,
                "published_at": published_at,
            })
            if res:
                # Race is over: keep the pre-race book (the upsert keeps the stored
                # value when the new one is empty), so the track record grades the
                # prices and flags we actually published before the jump.
                for k in FROZEN_AFTER_RESULT:
                    e_rows[-1][k] = None

        betfair = next((x.get("id") for x in ((raw.get("thirdPartyIds") or {}).get("BETFAIR") or [])
                        if x.get("type") == "WIN"), None)
        r_rows.append({
            "race_id": race_id, "meeting_id": card.get("id"), "meeting_date": mdate,
            "race_number": race["race_number"], "race_name": raw.get("name"),
            "distance": race["distance"], "class_name": race["class_name"],
            "class_group": _class_group(race["class_name"]),
            "form_par": round(par["par"], 1) if par else None,
            "jump_time": datetime.datetime.fromtimestamp(race["jump_time"] / 1000, datetime.timezone.utc).isoformat()
            if race.get("jump_time") else None,
            "field_size": len(scored), "tempo": tempo_tier, "leaders": n_leaders,
            "market_weight": MARKET_WEIGHT, "commission": commission, "betfair_market_id": betfair,
            "result_in": result_in, "published_at": published_at,
        })

    counts = {"edge_meetings": _upsert(db, "edge_meetings", m_rows),
              "edge_races": _upsert(db, "edge_races", r_rows),
              "edge_runners": _upsert(db, "edge_runners", e_rows)}
    db.commit()
    return counts


def load_model(db):
    """The form model over the history database, or None if it can't load."""
    try:
        import form_model
        hist = form_model.load_history(db)
        return form_model.FormModel(hist) if len(hist) else None
    except Exception as exc:
        print("Form model unavailable: {}".format(re.sub(r":[^:@\s]+@", ":****@", str(exc))))
        return None
