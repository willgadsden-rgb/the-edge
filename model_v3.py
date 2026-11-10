"""Model v3: trained on complete fields as they stood on race day.

Data: every Victorian card we hold with results (the backfill pulls old meetings
exactly as they were before the jump): all runners, each runner's form as of
that day, Form King's pre-race ratings, the bookmakers' early and final prices,
the Betfair SP and the result. No survivorship, no look-ahead.

Model: conditional logit (one winner per race)

    score = b_mkt * log(market chance) + sum(b_k * feature_k),  P = softmax over the field

fitted three ways - against the EARLY bookmaker price, the FINAL bookmaker price
and the Betfair SP - and tested on the most recent 30% of race days, which the
fit never sees. The early-price model is the one used live (the site prices the
card off morning bookmaker prices).

    python model_v3.py --fit       fit, test, print the report, save to model_params 'v3'
    python model_v3.py --report    print the saved report
"""

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import model_v2
from form_model import FormModel, load_history

TEST_SHARE = 0.30
L2 = 5.0
BAND = (2.0, 15.0)              # prices we would actually bet
EV_PRIMARY = 0.10               # the pre-set rule that decides "overlays proven"
BETFAIR_COMMISSION = 0.08
PLAY_MIN_P = 0.28               # high-percentage play: at least this chance ...
FORM_NAMES = [n for n in model_v2.NAMES if n != "mkt"]
EXTRA = ["fk_exp", "fk_peak12m", "fk_neural", "fk_missing", "weight_rel", "claim", "jockey_win", "trainer_win",
         "tj_win", "first_blinkers", "gear_change", "first_starter", "has_trial", "career_log",
         "track_place", "dist_place", "going_place"]
FEATS = FORM_NAMES + EXTRA
DESC = dict(model_v2.FEATURES, fk_exp="Form King expected rating (vs the field)", fk_peak12m="Form King 12-month peak (vs the field)",
            fk_neural="Form King neural score (vs the field)", fk_missing="no Form King rating", weight_rel="weight vs the field (kg)",
            claim="apprentice claim (kg)", jockey_win="jockey 12-month win %", trainer_win="trainer 12-month win %",
            tj_win="trainer-jockey combo win %", first_blinkers="blinkers first time", gear_change="any gear change",
            first_starter="first starter", has_trial="has a recent trial / jump-out", career_log="career starts (log)",
            track_place="place rate at this track", dist_place="place rate at this distance", going_place="place rate on this going")


# ------------------------------------------------------------------ features
def _rec(s):
    m = re.match(r"^(\d+):(\d+)-(\d+)-(\d+)", str(s or ""))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))) if m else (0, 0, 0, 0)


def _place_edge(s):
    """Place rate from a 'starts:1st-2nd-3rd' record, shrunk to a third, centred at 0."""
    n, w, s2, t = _rec(s)
    return ((w + s2 + t + 1.0) / (n + 3.0) - 1.0 / 3.0) if n else 0.0


def entry_features(fm, e, race):
    """Features for one runner from what was known before the race.
    e: horse_name, barrier, weight, apprentice_claim, race_in_prep, days_since_run,
       gear_changes, fk_exp, fk_peak12m, fk_neural, profile (dict)
    race: distance, going, class_label, track, race_date, field_size."""
    prof = e.get("profile") or {}
    f = model_v2.runner_features(fm, e["horse_name"], {
        "distance": race.get("distance"), "going": race.get("going"), "class_label": race.get("class_label"),
        "track": race.get("track"), "race_date": race["race_date"], "barrier": e.get("barrier"),
        "field_size": race.get("field_size"), "prep": e.get("race_in_prep"), "days_since": e.get("days_since_run")})
    f.pop("mkt", None)
    num = lambda v: float(v) if v is not None and not (isinstance(v, float) and math.isnan(v)) else None
    fx, fp, fn = num(e.get("fk_exp")), num(e.get("fk_peak12m")), num(e.get("fk_neural"))
    f["fk_exp"], f["fk_peak12m"], f["fk_neural"] = fx, fp, fn          # centred on the field later
    f["fk_missing"] = float(fx is None)
    f["weight_rel"] = num(e.get("weight"))
    f["claim"] = num(e.get("apprentice_claim")) or 0.0
    f["jockey_win"] = num(prof.get("jockey_12m_win_pct")) or 0.0
    f["trainer_win"] = num(prof.get("trainer_12m_win_pct")) or 0.0
    f["tj_win"] = num(prof.get("trainer_jockey_win_pct")) or 0.0
    g = str(e.get("gear_changes") or "")
    f["first_blinkers"] = float("blinkers first" in g.lower())
    f["gear_change"] = float(bool(g.strip()))
    form = prof.get("form") or {}
    starts = _rec(form.get("career"))[0]
    f["first_starter"] = float(bool(prof.get("first_starter")) or starts == 0)
    f["has_trial"] = float((prof.get("trials") or 0) > 0)
    f["career_log"] = math.log1p(starts)
    f["track_place"] = _place_edge(form.get("track"))
    f["dist_place"] = _place_edge(form.get("distance"))
    f["going_place"] = _place_edge(form.get("todays_going"))
    return f


def centre_on_field(df):
    """Race-relative versions of the level features (missing -> field average)."""
    for c in ("fk_exp", "fk_peak12m", "fk_neural", "weight_rel"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
        m = df.groupby("race_id")[c].transform("mean")
        df[c] = (df[c] - m).fillna(0.0)
    return df


# ------------------------------------------------------------------ data
CARDS_SQL = """
SELECT e.race_id, e.horse_name, e.saddlecloth, e.barrier, e.weight, e.apprentice_claim, e.race_in_prep, e.days_since_run,
       e.gear_changes, e.fk_exp, e.fk_peak12m, e.fk_neural, e.profile_json, e.scratched,
       ra.race_date, ra.track, ra.state, ra.distance, ra.going, ra.restrictions, ra.race_name, ra.meeting_id, ra.jump_time,
       r.finish_pos, r.sp, r.bsp, r.open_fluc
FROM entries e JOIN races ra ON ra.race_id = e.race_id
LEFT JOIN runs r ON r.race_id = e.race_id AND r.horse_name = e.horse_name
WHERE ra.state = 'VIC'
"""
ODDS_SQL = "SELECT race_id, horse_name, pulled_at, avg_open, avg_now, best_now FROM odds_snapshots"


def load_cards(db):
    cols = ["race_id", "horse_name", "saddlecloth", "barrier", "weight", "apprentice_claim", "race_in_prep", "days_since_run",
            "gear_changes", "fk_exp", "fk_peak12m", "fk_neural", "profile_json", "scratched", "race_date", "track", "state",
            "distance", "going", "restrictions", "race_name", "meeting_id", "jump_time", "finish_pos", "sp", "bsp", "open_fluc"]
    c = pd.DataFrame([tuple(r) for r in db.query(CARDS_SQL)], columns=cols)
    o = pd.DataFrame([tuple(r) for r in db.query(ODDS_SQL)], columns=["race_id", "horse_name", "pulled_at", "avg_open", "avg_now", "best_now"])
    if len(o):
        o = o.sort_values("pulled_at")
        g = o.groupby(["race_id", "horse_name"])
        agg = pd.DataFrame({"avg_open": g["avg_open"].first(), "first_now": g["avg_now"].first(), "first_pull": g["pulled_at"].first(),
                            "last_now": g["avg_now"].last(), "best_now": g["best_now"].last(), "pulls": g.size()}).reset_index()
        c = c.merge(agg, on=["race_id", "horse_name"], how="left")
    else:
        for k in ("avg_open", "first_now", "first_pull", "last_now", "best_now", "pulls"):
            c[k] = np.nan
    for k in ("finish_pos", "sp", "bsp", "open_fluc", "avg_open", "first_now", "last_now", "best_now", "weight", "barrier",
              "distance", "fk_exp", "fk_peak12m", "fk_neural", "apprentice_claim", "race_in_prep", "days_since_run"):
        c[k] = pd.to_numeric(c[k], errors="coerce")
    c["race_date"] = pd.to_datetime(c["race_date"], errors="coerce")
    # Early price: a snapshot taken at least an hour before the jump when we have
    # one (the daily 9am pull), else the bookmakers' opening average, else the
    # official opening fluctuation.
    jump = pd.to_datetime(c["jump_time"], errors="coerce", utc=True)
    first = pd.to_datetime(c["first_pull"], errors="coerce", utc=True)
    early_snap = c["first_now"].where((jump - first).dt.total_seconds() >= 3600)
    c["p_early_raw"] = early_snap.fillna(c["avg_open"]).fillna(c["open_fluc"])
    c["p_final_raw"] = c["last_now"].fillna(c["sp"])
    return c


def build_dataset(db, log=print):
    h = load_history(db)
    fm = FormModel(h)
    c = load_cards(db)
    c = c[(c["scratched"].fillna(0) == 0) & c["finish_pos"].notna() & (c["bsp"] > 1)]
    g = c.groupby("race_id")
    ok = (g["finish_pos"].transform(lambda s: (s == 1).sum()) == 1) & (g["finish_pos"].transform("size") >= 4)
    c = c[ok].copy()
    c["field_size"] = c.groupby("race_id")["horse_name"].transform("size")
    rows = []
    for x in c.itertuples(index=False):
        prof = {}
        try:
            prof = json.loads(x.profile_json) if x.profile_json else {}
        except Exception:
            prof = {}
        e = {"horse_name": x.horse_name, "barrier": x.barrier, "weight": x.weight, "apprentice_claim": x.apprentice_claim,
             "race_in_prep": x.race_in_prep, "days_since_run": x.days_since_run, "gear_changes": x.gear_changes,
             "fk_exp": x.fk_exp, "fk_peak12m": x.fk_peak12m, "fk_neural": x.fk_neural, "profile": prof}
        race = {"distance": x.distance, "going": x.going, "class_label": x.restrictions or x.race_name, "track": x.track,
                "race_date": x.race_date, "field_size": x.field_size}
        rows.append(entry_features(fm, e, race))
    f = pd.DataFrame(rows, index=c.index)
    d = pd.concat([c[["race_id", "horse_name", "race_date", "track", "finish_pos", "sp", "bsp", "open_fluc", "avg_open",
                      "best_now", "p_early_raw", "p_final_raw", "field_size", "restrictions", "race_name"]], f], axis=1)
    d["win"] = (d["finish_pos"] == 1).astype(float)
    d = centre_on_field(d)
    d = d.sort_values(["race_date", "race_id", "horse_name"]).reset_index(drop=True)
    log("Dataset: {:,} runners in {:,} races, {} to {}".format(len(d), d["race_id"].nunique(), d["race_date"].min().date(), d["race_date"].max().date()))
    return d


# ------------------------------------------------------------------ conditional logit
def _starts(ids):
    return np.r_[0, np.flatnonzero(ids[1:] != ids[:-1]) + 1]


def clogit(X, y, starts, pen):
    k = X.shape[1]
    w = np.zeros(k)
    n = np.diff(np.append(starts, len(y)))
    for _ in range(60):
        u = X @ w
        u = u - np.maximum.reduceat(u, starts).repeat(n)
        e = np.exp(u)
        p = e / np.add.reduceat(e, starts).repeat(n)
        g = X.T @ (p - y) + pen * w
        PX = X * p[:, None]
        Xp = np.add.reduceat(PX, starts, axis=0)
        H = X.T @ PX - Xp.T @ Xp + np.diag(pen) + 1e-8 * np.eye(k)
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


def softmax_by_race(u, starts):
    n = np.diff(np.append(starts, len(u)))
    u = u - np.maximum.reduceat(u, starts).repeat(n)
    e = np.exp(u)
    return e / np.add.reduceat(e, starts).repeat(n)


def _with_market(d, col):
    """Rows whose whole race has this price; adds the normalised market chance."""
    x = d[d[col] > 1].copy()
    full = x.groupby("race_id")["horse_name"].transform("size") == x["field_size"]
    x = x[full].copy()
    inv = 1.0 / x[col]
    x["pm"] = inv / inv.groupby(x["race_id"]).transform("sum")
    x["price"] = x[col]
    return x.sort_values(["race_date", "race_id", "horse_name"]).reset_index(drop=True)


def fit_one(train, feats):
    mu, sd = train[feats].mean(), train[feats].std().replace(0, 1.0)
    X = np.column_stack([np.log(train["pm"].values)] + [((train[f] - mu[f]) / sd[f]).values for f in feats])
    pen = np.r_[0.0, np.full(len(feats), L2)]
    st = _starts(train["race_id"].values)
    w = clogit(X, train["win"].values, st, pen)
    w0 = clogit(X[:, :1], train["win"].values, st, np.zeros(1))
    return {"w": w, "w0": float(w0[0]), "mu": mu, "sd": sd, "feats": feats}


def predict(m, d):
    X = np.column_stack([np.log(d["pm"].values)] + [((d[f] - m["mu"][f]) / m["sd"][f]).values for f in m["feats"]])
    st = _starts(d["race_id"].values)
    return softmax_by_race(X @ m["w"], st), softmax_by_race(X[:, 0] * m["w0"], st)


def _roi(win, price, commission=0.0):
    return float(np.where(win == 1, (price - 1) * (1 - commission), -1).mean()) if len(win) else float("nan")


def _boot_days(t, stat, n=400, seed=11):
    rng = np.random.default_rng(seed)
    days = {k: g for k, g in t.groupby(t["race_date"].dt.normalize())}
    keys = list(days)
    if len(keys) < 5:
        return (float("nan"), float("nan"))
    vals = []
    for _ in range(n):
        s = stat(pd.concat([days[keys[i]] for i in rng.integers(0, len(keys), len(keys))]))
        if s is not None and not np.isnan(s):
            vals.append(s)
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))) if vals else (float("nan"), float("nan"))


def evaluate(d, col, label, out):
    x = _with_market(d, col)
    days = np.sort(x["race_date"].unique())
    if len(days) < 20:
        out.append("{}: not enough race days yet ({}).".format(label, len(days)))
        return None
    cut = days[int(len(days) * (1 - TEST_SHARE))]
    train, test = x[x["race_date"] < cut], x[x["race_date"] >= cut].copy()
    m = fit_one(train, FEATS)
    p, p0 = predict(m, test)
    test["p"], test["p0"] = p, p0
    y = test["win"].values
    llm, ll0, llf = -np.log(test["pm"].values[y == 1]).mean(), -np.log(p0[y == 1]).mean(), -np.log(p[y == 1]).mean()
    test["gain"] = np.where(y == 1, np.log(test["p"]) - np.log(test["p0"]), 0.0)
    lo, hi = _boot_days(test, lambda t: t["gain"].sum() / max(1, (t["win"] == 1).sum()))
    out.append("")
    out.append("== {} ==  train {:,} races to {}, test {:,} races after".format(
        label, train["race_id"].nunique(), pd.Timestamp(cut).date(), test["race_id"].nunique()))
    out.append("Log-loss per race: market {:.4f} | market recalibrated {:.4f} (weight {:.2f}) | + form {:.4f}".format(llm, ll0, m["w0"], llf))
    out.append("Form adds over the recalibrated market: {:+.4f} per race ({:+.2f}%), 95% CI [{:+.4f}, {:+.4f}]".format(
        ll0 - llf, (ll0 - llf) / ll0 * 100, lo, hi))
    res = {"label": label, "n_train_races": int(train["race_id"].nunique()), "n_test_races": int(test["race_id"].nunique()),
           "gain": float(ll0 - llf), "gain_lo": lo, "gain_hi": hi, "market_weight": m["w0"], "bets": {}}
    band = test["price"].between(*BAND)
    for thr in (0.05, EV_PRIMARY, 0.20):
        b = test[band & (test["p"] * test["price"] - 1 >= thr)]
        if len(b) < 20:
            out.append("  Model says {:.0%}+ value at this price (${}-${}): only {} bets".format(thr, BAND[0], BAND[1], len(b)))
            continue
        roi = _roi(b["win"].values, b["price"].values)
        rlo, rhi = _boot_days(test, lambda t, thr=thr: (lambda z: _roi(z["win"].values, z["price"].values) if len(z) >= 5 else None)(
            t[t["price"].between(*BAND) & (t["p"] * t["price"] - 1 >= thr)]))
        roi_bsp = _roi(b["win"].values, b["bsp"].values, BETFAIR_COMMISSION)
        clv = float((b["price"] / b["bsp"]).median())
        out.append("  Model says {:.0%}+ value at this price (${}-${}): {} bets, strike {:.1%}, ROI {:+.1%} (95% CI {:+.1%} to {:+.1%}); "
                   "same bets at Betfair SP after commission {:+.1%}; price taken vs BSP x{:.2f}".format(
                       thr, BAND[0], BAND[1], len(b), b["win"].mean(), roi, rlo, rhi, roi_bsp, clv))
        res["bets"][str(thr)] = {"n": int(len(b)), "strike": float(b["win"].mean()), "roi": roi, "roi_lo": rlo, "roi_hi": rhi,
                                 "roi_bsp_net": roi_bsp, "clv": clv}
    allb = test[band]
    out.append("  Every runner ${}-${} at this price: {} bets, ROI {:+.1%}; at Betfair SP after commission {:+.1%}".format(
        BAND[0], BAND[1], len(allb), _roi(allb["win"].values, allb["price"].values), _roi(allb["win"].values, allb["bsp"].values, BETFAIR_COMMISSION)))
    fade = test[band & (test["p"] <= test["p0"] / 1.2)]
    if len(fade) >= 20:
        out.append("  Fades (model 20%+ below the market): {} runners, won {:.1%} vs {:.1%} the market expected (A/E {:.2f}), ROI if backed {:+.1%}".format(
            len(fade), fade["win"].mean(), fade["p0"].mean(), fade["win"].sum() / fade["p0"].sum(), _roi(fade["win"].values, fade["price"].values)))
        res["fade"] = {"n": int(len(fade)), "ae": float(fade["win"].sum() / fade["p0"].sum())}
    hp = test[test["p"] >= PLAY_MIN_P]
    if len(hp) >= 20:
        out.append("  High-percentage runners (model chance {:.0%}+): {} runners, won {:.1%} (model said {:.1%}, market {:.1%}), ROI at this price {:+.1%}, at BSP after commission {:+.1%}".format(
            PLAY_MIN_P, len(hp), hp["win"].mean(), hp["p"].mean(), hp["p0"].mean(), _roi(hp["win"].values, hp["price"].values),
            _roi(hp["win"].values, hp["bsp"].values, BETFAIR_COMMISSION)))
        res["plays"] = {"n": int(len(hp)), "strike": float(hp["win"].mean()), "model": float(hp["p"].mean()),
                        "roi": _roi(hp["win"].values, hp["price"].values), "roi_bsp_net": _roi(hp["win"].values, hp["bsp"].values, BETFAIR_COMMISSION)}
    res["test"] = test
    return res


def factor_table(d, out):
    """What each form signal is worth on clean data: winners vs what the Betfair SP
    expected (A/E), and the return backing every such runner at the early price / BSP."""
    x = _with_market(d, "bsp")
    x["price_early"] = x["p_early_raw"]
    rk = lambda c, asc=False: x.groupby("race_id")[c].rank(ascending=asc, method="min")
    F = [("Market favourite (BSP)", rk("bsp", True) == 1),
         ("Top Form King expected rating", (rk("fk_exp") == 1) & (x["fk_missing"] == 0)),
         ("Top Form King neural score", (rk("fk_neural") == 1) & (x["fk_missing"] == 0)),
         ("Top Form L (our rating vs par)", (rk("gap_l") == 1) & (x["no_form"] == 0)),
         ("Top last-start rating", (rk("last_l") == 1) & (x["no_form"] == 0)),
         ("Won last start", x["won_last"] == 1), ("Beaten 1L or less last start", x["close_last"] == 1),
         ("Stewards excuse last start", x["excuse_last"] == 1),
         ("1st-up", x["first_up"] == 1), ("2nd-up", x["second_up"] == 1), ("3rd-up", x["third_up"] == 1),
         ("Up 200m+ in trip", x["up_trip"] == 1), ("Down 200m+ in trip", x["down_trip"] == 1),
         ("Blinkers first time", x["first_blinkers"] == 1), ("First starter", x["first_starter"] == 1),
         ("First starter with a trial/jump-out", (x["first_starter"] == 1) & (x["has_trial"] == 1)),
         ("Jockey 15%+ winners (12 months)", x["jockey_win"] >= 15), ("Trainer 15%+ winners (12 months)", x["trainer_win"] >= 15),
         ("Trainer-jockey combo 20%+", x["tj_win"] >= 20),
         ("Barrier 1-3", x["barrier_frac"] * x["field_size"] <= 3), ("Barrier 10+", x["barrier_frac"] * x["field_size"] >= 10)]
    rows = []
    out.append("")
    out.append("== What each signal is worth (all {:,} races; A/E vs the Betfair SP chance, 1.00 = fully priced in) ==".format(x["race_id"].nunique()))
    for name, mask in F:
        g = x[mask.fillna(False)]
        if len(g) < 40:
            continue
        ae = g["win"].sum() / g["pm"].sum()
        se = math.sqrt((g["pm"] * (1 - g["pm"])).sum()) / g["pm"].sum()
        ge = g[g["price_early"] > 1]
        r = {"signal": name, "n": int(len(g)), "strike": round(float(g["win"].mean()) * 100, 1), "ae": round(float(ae), 3),
             "ae_lo": round(float(ae - 1.96 * se), 3), "ae_hi": round(float(ae + 1.96 * se), 3),
             "roi_bsp": round(_roi(g["win"].values, g["bsp"].values) * 100, 1),
             "roi_early": round(_roi(ge["win"].values, ge["price_early"].values) * 100, 1) if len(ge) >= 40 else None}
        rows.append(r)
        out.append("  {:<38} n={:<6} strike {:>5.1f}%  A/E {:.3f} [{:.3f}, {:.3f}]  ROI at BSP {:+.1f}%  at early price {}".format(
            name, r["n"], r["strike"], r["ae"], r["ae_lo"], r["ae_hi"], r["roi_bsp"],
            "{:+.1f}%".format(r["roi_early"]) if r["roi_early"] is not None else "n/a"))
    return rows


def price_paths(d, out):
    """How the prices relate: early bookmaker average, final bookmaker average, SP, Betfair SP."""
    x = d[(d["bsp"] > 1)]
    out.append("")
    out.append("== Prices (median ratio to Betfair SP; below 1 = shorter than BSP) ==")
    for lab, col in (("Early bookmaker price", "p_early_raw"), ("Final bookmaker average", "p_final_raw"), ("Starting price (SP)", "sp"), ("Best bookmaker price at the jump", "best_now")):
        if col not in x or x[col].notna().sum() < 100:
            continue
        g = x[x[col] > 1]
        parts = []
        for lo, hi in ((1, 4), (4, 10), (10, 25)):
            gg = g[(g["bsp"] >= lo) & (g["bsp"] < hi)]
            if len(gg) >= 50:
                parts.append("BSP ${}-${}: x{:.2f}".format(lo, hi, (gg[col] / gg["bsp"]).median()))
        out.append("  {:<34} {}".format(lab, " | ".join(parts)))
    out.append("  Backing every runner $2-$15 at: " + " | ".join(
        "{} {:+.1%}".format(lab, _roi(g["win"].values, g[col].values, com))
        for lab, col, com, g in [(l, c, cm, x[(x[c] >= 2) & (x[c] <= 15)]) for l, c, cm in
                                 (("early price", "p_early_raw", 0), ("SP", "sp", 0), ("best at jump", "best_now", 0), ("BSP gross", "bsp", 0), ("BSP after 8%", "bsp", BETFAIR_COMMISSION))
                                 if c in x and x[c].notna().sum() >= 100]))


# ------------------------------------------------------------------ fit + save
def fit(db, log=print):
    d = build_dataset(db, log)
    out = ["Model v3 on {:,} runners in {:,} complete Victorian races ({} to {})".format(
        len(d), d["race_id"].nunique(), d["race_date"].min().date(), d["race_date"].max().date())]
    price_paths(d, out)
    res = {}
    for col, label in (("p_early_raw", "EARLY bookmaker price"), ("p_final_raw", "FINAL bookmaker price"), ("bsp", "BETFAIR SP")):
        res[col] = evaluate(d, col, label, out)
    factors = factor_table(d, out)

    early = res.get("p_early_raw")
    primary = (early or {}).get("bets", {}).get(str(EV_PRIMARY)) if early else None
    overlays_proven = bool(primary and primary["n"] >= 150 and primary["roi_lo"] > 0)
    form_adds = bool(early and early["gain_lo"] > 0)
    fades_proven = bool(early and early.get("fade") and early["fade"]["n"] >= 200 and early["fade"]["ae"] <= 0.85)

    # Final fit on everything, early-price market, for live use.
    x = _with_market(d, "p_early_raw")
    params = {"name": "v3", "fitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "n_races": int(d["race_id"].nunique()), "n_runners": int(len(d)),
              "from": str(d["race_date"].min().date()), "to": str(d["race_date"].max().date()),
              "overlays_proven": overlays_proven, "form_adds": form_adds, "fades_proven": fades_proven,
              "use_for_pricing": False, "ev_threshold": EV_PRIMARY, "band": list(BAND), "play_min_p": PLAY_MIN_P,
              "factors": factors, "results": {k: ({kk: vv for kk, vv in v.items() if kk != "test"} if v else None) for k, v in res.items()}}
    if x["race_id"].nunique() >= 300:
        m = fit_one(x, FEATS)
        params.update(market_coef=float(m["w"][0]), market_only_coef=m["w0"],
                      coefs={f: float(m["w"][i + 1] / m["sd"][f]) for i, f in enumerate(FEATS)},
                      means={f: float(m["mu"][f]) for f in FEATS},
                      importance={f: round(float(m["w"][i + 1]), 3) for i, f in enumerate(FEATS)},
                      use_for_pricing=True)
        out.append("")
        out.append("Live model (early price, all data): market weight {:.2f}; strongest signals per 1 SD:".format(m["w"][0]))
        for f, v in sorted(params["importance"].items(), key=lambda kv: -abs(kv[1]))[:14]:
            out.append("  {:<16} {:+.3f}   {}".format(f, v, DESC.get(f, "")))
    out.append("")
    out.append("VERDICT: form adds to the early market: {} | 10%+ overlays profitable at the early price (CI above zero, 150+ bets): {} | fades proven: {}".format(
        form_adds, overlays_proven, fades_proven))
    params["report"] = "\n".join(out)
    return _clean(params)


def _clean(o):
    """JSON-safe: NaN/inf -> None, numpy numbers -> Python."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if (math.isnan(o) or math.isinf(o)) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def static_score(params, f):
    """Runner's form part of the score (the site adds market weight x log(1/price))."""
    return sum(params["coefs"][k] * (f.get(k) or 0.0) for k in params["coefs"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args(argv)
    from history_db import HistoryDB
    db = HistoryDB()
    if a.fit:
        p = fit(db, lambda *x: print(*x, file=sys.stderr))
        print(p["report"])
        if not a.no_save:
            model_v2.save(db, p, name="v3")
            print("Saved to model_params (name v3).")
    else:
        p = model_v2.load(db, name="v3")
        print(p["report"] if p else "No v3 model saved yet.")
    db.close()


if __name__ == "__main__":
    main()
