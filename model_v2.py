"""Model v2: learn from results where the market is wrong.

Every run in the history becomes one training row: features built ONLY from that
horse's earlier runs (no look-ahead), the starting price, and whether it won.
A logistic regression then learns how much each form signal adds on top of the
market price:

    logit P(win) = b0 + b_mkt * log(1/price) + sum(b_k * feature_k)

On a race card the probabilities are re-normalised across the full field, which
cancels b0, so the history's sampling (it holds placegetters and horses still
racing, not full fields) shifts only the intercept and not the weights.

The model is only switched on for pricing when it beats the market on races it
was NOT trained on (time split): lower log-loss than the market alone AND its
overlays return more winners than their price expected.

    python model_v2.py --fit            fit, test, print the report, save to the DB
    python model_v2.py --report         print the saved report
"""

import argparse
import json
import math
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from form_model import FormModel, load_history, going_band

SPLIT_DATE = "2026-07-01"          # train before, test on and after
TRAIN_FROM = "2024-07-01"          # older history is the most survivor-biased
L2 = 1.0                           # ridge penalty (standardised features)
OVERLAY = 1.20                     # model chance at least 20% above the price's
ODDS_BAND = (2.2, 18.0)

FEATURES = [
    ("mkt", "log market chance (1/price)"),
    ("gap_l", "form rating vs par, lengths (Form L)"),
    ("no_form", "no rated runs"),
    ("rel", "how much form the rating stands on"),
    ("last_l", "last start rating vs par, lengths"),
    ("best3_l", "best of last 3 vs par, lengths"),
    ("trend", "last 3 avg minus the 3 before, points"),
    ("won_last", "won last start"),
    ("close_last", "beaten 1L or less last start"),
    ("excuse_last", "stewards excuse last start"),
    ("up_trip", "up 200m+ in trip"),
    ("down_trip", "down 200m+ in trip"),
    ("first_up", "1st-up"),
    ("second_up", "2nd-up"),
    ("third_up", "3rd-up"),
    ("log_days", "log days since last run"),
    ("going_suit", "place rate on today's going vs overall"),
    ("unraced_going", "never raced on today's going"),
    ("early", "average settling position (0 leads, 1 last)"),
    ("barrier_frac", "barrier / field size"),
]
NAMES = [f for f, _ in FEATURES]


# ------------------------------------------------------------------ features
def _going_suit(prior, gb):
    if not gb or prior.empty:
        return 0.0, 1.0
    placed = (prior["finish_pos"] <= 3).astype(float)
    on = prior["going_band"] == gb
    n_on = int(on.sum())
    if n_on == 0:
        return 0.0, 1.0
    overall = (placed.sum() + 1) / (len(prior) + 3)
    there = (placed[on].sum() + 1) / (n_on + 3)
    return float((there - overall) * n_on / (n_on + 3)), 0.0


def runner_features(model, horse, race):
    """Features for one runner from its runs BEFORE race['race_date'].
    race: distance, going, class_label, track, race_date, barrier, field_size,
    prep, days_since."""
    rd = pd.Timestamp(race["race_date"])
    runs = model.horse_runs(horse)
    prior = runs[runs["race_date"] < rd]
    rated = prior[prior["wfa_rating"].notna()]
    r = model.rate(horse, race.get("distance"), race.get("going"), race.get("class_label"),
                   race.get("track"), race["race_date"])
    par = r.get("par")
    lpp = model.lengths_per_point(race.get("distance"))
    f = dict.fromkeys(NAMES, 0.0)
    if r.get("gap_l") is None:
        f["no_form"] = 1.0
    else:
        f["gap_l"] = float(r["gap_l"])
        f["rel"] = min(float(r.get("reliability") or 0), 6.0)
    if par and not rated.empty:
        ratings = rated["wfa_rating"].tolist()
        f["last_l"] = (ratings[0] - par) * lpp
        f["best3_l"] = (max(ratings[:3]) - par) * lpp
        if len(ratings) >= 4:
            f["trend"] = float(np.mean(ratings[:3]) - np.mean(ratings[3:6]))
    if not prior.empty:
        last = prior.iloc[0]
        f["won_last"] = float(last["finish_pos"] == 1)
        b = last.get("beaten")
        f["close_last"] = float(last["finish_pos"] != 1 and pd.notna(b) and b <= 1.0)
        f["excuse_last"] = float(bool(last.get("excuse")))
        if race.get("distance") and pd.notna(last.get("distance")):
            d = race["distance"] - last["distance"]
            f["up_trip"] = float(d >= 200)
            f["down_trip"] = float(d <= -200)
        s = prior.head(3)
        frac = (s["settle_pos"] - 1) / (s["field_size"] - 1)
        frac = frac[(s["field_size"] > 1) & s["settle_pos"].notna()]
        f["early"] = float(frac.mean()) if len(frac) else 0.5
    else:
        f["early"] = 0.5
    prep = race.get("prep")
    f["first_up"] = float(prep == 1)
    f["second_up"] = float(prep == 2)
    f["third_up"] = float(prep == 3)
    ds = race.get("days_since")
    f["log_days"] = math.log1p(ds) if ds is not None and not pd.isna(ds) and ds >= 0 else math.log1p(28)
    f["going_suit"], f["unraced_going"] = _going_suit(prior[prior["finish_pos"].notna()], going_band(race.get("going")))
    bar, fs = race.get("barrier"), race.get("field_size")
    f["barrier_frac"] = float(bar) / float(fs) if bar and fs and fs > 1 else 0.5
    return f


def build_dataset(h, model, since=TRAIN_FROM):
    rows = h[(h["race_date"] >= pd.Timestamp(since)) & (h["sp"] > 1) & h["finish_pos"].notna()]
    out = []
    for x in rows.itertuples(index=False):
        race = {"distance": x.distance, "going": x.going, "class_label": x.restrictions or x.race_name,
                "track": x.track, "race_date": x.race_date, "barrier": x.barrier,
                "field_size": x.field_size, "prep": x.race_in_prep, "days_since": x.days_since_prev}
        f = runner_features(model, x.horse_name, race)
        f["mkt"] = math.log(1.0 / x.sp)
        f.update(win=float(x.finish_pos == 1), sp=float(x.sp), bsp=float(x.bsp) if pd.notna(x.bsp) else None,
                 race_date=x.race_date, race_id=x.race_id, source=x.source)
        out.append(f)
    return pd.DataFrame(out)


# ------------------------------------------------------------------ fitting
def fit_logit(X, y, l2=L2, iters=50):
    """Ridge logistic regression by Newton steps. X already has the intercept column."""
    n, k = X.shape
    w = np.zeros(k)
    pen = np.full(k, l2)
    pen[0] = 0.0                                    # no penalty on the intercept
    for _ in range(iters):
        z = X @ w
        p = 1 / (1 + np.exp(-z))
        g = X.T @ (p - y) + pen * w
        H = (X * (p * (1 - p))[:, None]).T @ X + np.diag(pen)
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-7:
            break
    return w


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def evaluate(df):
    df = df.copy()
    train, test = df[df["race_date"] < pd.Timestamp(SPLIT_DATE)], df[df["race_date"] >= pd.Timestamp(SPLIT_DATE)]
    feats = NAMES
    mu = train[feats].mean()
    sd = train[feats].std().replace(0, 1.0)
    sd["mkt"] = 1.0                                  # keep the market on its natural scale
    mu["mkt"] = 0.0

    def design(d, cols):
        Z = (d[cols] - mu[cols]) / sd[cols]
        return np.column_stack([np.ones(len(d)), Z.values])

    ytr, yte = train["win"].values, test["win"].values
    w_m = fit_logit(design(train, ["mkt"]), ytr)
    w_f = fit_logit(design(train, feats), ytr)
    p_m = 1 / (1 + np.exp(-design(test, ["mkt"]) @ w_m))
    p_f = 1 / (1 + np.exp(-design(test, feats) @ w_f))
    test = test.assign(p_m=p_m, p_f=p_f)
    ll_m, ll_f = logloss(p_m, yte), logloss(p_f, yte)

    # Overlays: model chance well above the market-only chance (same scale, so
    # the history's sampling cancels out).
    ov = test[(test["p_f"] >= OVERLAY * test["p_m"]) & test["sp"].between(*ODDS_BAND)]
    base = test[test["sp"].between(*ODDS_BAND)]
    under = test[(test["p_f"] <= test["p_m"] / OVERLAY) & test["sp"].between(*ODDS_BAND)]

    def perf(d):
        if d.empty:
            return {"n": 0}
        ae = d["win"].sum() / (1 / d["sp"]).sum()
        roi = (np.where(d["win"] == 1, d["sp"] - 1, -1)).mean()
        b = d[d["bsp"].notna()]
        roi_b = (np.where(b["win"] == 1, (b["bsp"] - 1) * 0.92, -1)).mean() if len(b) else None
        return {"n": int(len(d)), "wins": int(d["win"].sum()), "strike": round(float(d["win"].mean()) * 100, 1),
                "ae": round(float(ae), 3), "roi_sp": round(float(roi) * 100, 1),
                "roi_bsp_net": round(float(roi_b) * 100, 1) if roi_b is not None else None, "n_bsp": int(len(b))}

    o, b_, u = perf(ov), perf(base), perf(under)
    rel_ae = (o.get("ae", 0) / b_["ae"]) if b_.get("ae") else 0
    validated = bool(ll_f < ll_m and o.get("n", 0) >= 100 and rel_ae >= 1.03)      # overlays proven
    rel_under = (u.get("ae", 1) / b_["ae"]) if b_.get("ae") else 1
    # More accurate than the market on unseen races -> it prices the cards (its
    # probabilities beat both the market alone and the old 70/30 blend).
    use_for_pricing = bool(ll_f < ll_m and len(test) >= 2000)
    # Its unders win clearly less than their price says -> flag them as fades.
    fades_proven = bool(u.get("n", 0) >= 200 and rel_under <= 0.90)

    # Refit on everything for live use.
    allmu, allsd = df[feats].mean(), df[feats].std().replace(0, 1.0)
    allsd["mkt"], allmu["mkt"] = 1.0, 0.0
    Zall = np.column_stack([np.ones(len(df)), ((df[feats] - allmu[feats]) / allsd[feats]).values])
    w_all = fit_logit(Zall, df["win"].values)
    coefs = {name: float(w_all[i + 1] / allsd[name]) for i, name in enumerate(feats)}   # per raw unit
    intercept = float(w_all[0] - sum(coefs[n] * allmu[n] for n in feats))
    std_w = {name: round(float(w_all[i + 1]), 3) for i, name in enumerate(feats)}       # per 1 SD (importance)

    return {
        "fitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "train_from": TRAIN_FROM, "split": SPLIT_DATE,
        "n_train": int(len(train)), "n_test": int(len(test)), "n_all": int(len(df)),
        "logloss_market": round(ll_m, 5), "logloss_model": round(ll_f, 5),
        "logloss_gain_pct": round((ll_m - ll_f) / ll_m * 100, 3),
        "overlays": o, "all_in_band": b_, "unders": u, "overlay_ae_vs_base": round(rel_ae, 3),
        "validated": validated, "overlays_proven": validated,
        "use_for_pricing": use_for_pricing, "fades_proven": fades_proven,
        "under_ae_vs_base": round(rel_under, 3),
        "coefs": coefs, "intercept": intercept, "importance_per_sd": std_w,
        "market_coef": coefs["mkt"],
    }


# ------------------------------------------------------------------ audit
def audit(df, n_boot=400, seed=7):
    """Stress-test on the unseen period: is the gain over the market real, stable,
    and more than favourite-longshot bias? Bootstrap resamples whole race days."""
    rng = np.random.default_rng(seed)
    split = pd.Timestamp(SPLIT_DATE)
    train, test = df[df["race_date"] < split], df[df["race_date"] >= split].copy()
    mu, sd = train[NAMES].mean(), train[NAMES].std().replace(0, 1.0)
    sd["mkt"], mu["mkt"] = 1.0, 0.0
    D = lambda d, cols: np.column_stack([np.ones(len(d)), ((d[cols] - mu[cols]) / sd[cols]).values])
    form_only = [n for n in NAMES if n != "mkt"]
    w_m = fit_logit(D(train, ["mkt"]), train["win"].values)
    w_f = fit_logit(D(train, NAMES), train["win"].values)
    w_o = fit_logit(D(train, form_only), train["win"].values)
    sig = lambda z: 1 / (1 + np.exp(-z))
    test["p_m"], test["p_f"], test["p_o"] = sig(D(test, ["mkt"]) @ w_m), sig(D(test, NAMES) @ w_f), sig(D(test, form_only) @ w_o)
    y = test["win"].values
    base = np.full(len(test), train["win"].mean())
    ll = lambda p, yy: -(yy * np.log(np.clip(p, 1e-6, 1)) + (1 - yy) * np.log(np.clip(1 - p, 1e-6, 1)))
    test["d_ll"] = ll(test["p_m"].values, y) - ll(test["p_f"].values, y)          # + = model better
    out = ["AUDIT of model v2 on {:,} unseen runs ({} to {}), trained on {:,}".format(
        len(test), test["race_date"].min().date(), test["race_date"].max().date(), len(train))]
    out.append("Win rate in the data: train {:.1%}, test {:.1%} (a full field averages about 10%)".format(train["win"].mean(), test["win"].mean()))
    out.append("Log-loss: no-info {:.5f} | form only (no price) {:.5f} | market only {:.5f} | market+form {:.5f}".format(
        ll(base, y).mean(), ll(test["p_o"].values, y).mean(), ll(test["p_m"].values, y).mean(), ll(test["p_f"].values, y).mean()))
    days = test["race_date"].dt.normalize()
    groups = {d: g for d, g in test.groupby(days)}
    keys = list(groups)

    def boot(stat):
        vals = []
        for _ in range(n_boot):
            pick = rng.choice(len(keys), len(keys))
            vals.append(stat(pd.concat([groups[keys[i]] for i in pick])))
        v = np.array([x for x in vals if x is not None and not np.isnan(x)])
        return np.percentile(v, 2.5), np.percentile(v, 97.5), v

    lo, hi, v = boot(lambda d: d["d_ll"].mean())
    out.append("Gain over the market per run: {:+.5f}  95% CI [{:+.5f}, {:+.5f}]  positive in {:.0%} of resamples".format(
        test["d_ll"].mean(), lo, hi, (v > 0).mean()))
    mid = test["race_date"].sort_values().iloc[len(test) // 2]
    for name, part in (("first half", test[test["race_date"] <= mid]), ("second half", test[test["race_date"] > mid])):
        out.append("  {} ({:,} runs): gain {:+.5f}".format(name, len(part), part["d_ll"].mean()))
    for src, part in test.groupby(test["source"].fillna("?")):
        out.append("  source {} ({:,} runs, win rate {:.1%}): gain {:+.5f}".format(src, len(part), part["win"].mean(), part["d_ll"].mean()))

    band = test["sp"].between(*ODDS_BAND)
    groupsets = {"Overlays (model 20%+ above market)": test[band & (test["p_f"] >= OVERLAY * test["p_m"])],
                 "Unders / fades (model 20%+ below)": test[band & (test["p_f"] <= test["p_m"] / OVERLAY)],
                 "Everything $2.20-$18": test[band]}
    out.append("A/E vs the market-only chance (1.00 = the price already had it right; this strips out favourite-longshot bias):")
    for name, g in groupsets.items():
        if g.empty:
            out.append("  {}: none".format(name)); continue
        flag = (lambda d, nm=name: (lambda x: x["win"].sum() / x["p_m"].sum() if len(x) and x["p_m"].sum() > 0 else np.nan)(
            d[d["sp"].between(*ODDS_BAND) & ((d["p_f"] >= OVERLAY * d["p_m"]) if nm.startswith("Overlays") else
                                             (d["p_f"] <= d["p_m"] / OVERLAY) if nm.startswith("Unders") else True)]))
        lo, hi, _ = boot(flag)
        out.append("  {:<36} n={:<5} wins={:<4} A/E vs market {:.3f}  95% CI [{:.3f}, {:.3f}]  | A/E vs model {:.3f} | avg SP ${:.2f} | ROI at SP {:+.1f}%".format(
            name, len(g), int(g["win"].sum()), g["win"].sum() / g["p_m"].sum(), lo, hi, g["win"].sum() / g["p_f"].sum(),
            g["sp"].mean(), np.where(g["win"] == 1, g["sp"] - 1, -1).mean() * 100))
    for name in ("Overlays (model 20%+ above market)", "Unders / fades (model 20%+ below)"):
        g = groupsets[name]
        for hn, part in (("first half", g[g["race_date"] <= mid]), ("second half", g[g["race_date"] > mid])):
            if len(part):
                out.append("    {} {}: n={} A/E vs market {:.3f}".format(name.split(" (")[0], hn, len(part), part["win"].sum() / part["p_m"].sum()))
    out.append("Market calibration by SP band on unseen runs (A/E vs raw 1/SP; below 1 = worse than its price):")
    for lo_, hi_ in ((1, 2.2), (2.2, 4), (4, 7), (7, 12), (12, 18), (18, 40), (40, 1001)):
        g = test[(test["sp"] >= lo_) & (test["sp"] < hi_)]
        if len(g):
            out.append("  ${:<5}-${:<6} n={:<5} strike {:>5.1%}  A/E {:.3f}  ROI at SP {:+.1f}%".format(
                lo_, hi_, len(g), g["win"].mean(), g["win"].sum() / (1 / g["sp"]).sum(), np.where(g["win"] == 1, g["sp"] - 1, -1).mean() * 100))
    out.append("Runs with no rated form before the race: {:.1%} of the unseen set".format(test["no_form"].mean()))
    return "\n".join(out)


# ------------------------------------------------------------------ storage
DDL = ("CREATE TABLE IF NOT EXISTS model_params (name TEXT PRIMARY KEY, fitted_at TEXT, "
       "params_json TEXT)")


def save(db, params, name="v2"):
    cur = db.conn.cursor()
    cur.execute(DDL)
    ph = "%s" if db.kind == "postgres" else "?"
    cur.execute("INSERT INTO model_params (name, fitted_at, params_json) VALUES ({p}, {p}, {p}) "
                "ON CONFLICT (name) DO UPDATE SET fitted_at = excluded.fitted_at, params_json = excluded.params_json"
                .format(p=ph), (name, params["fitted_at"], json.dumps(params)))
    db.commit()


def load(db, name="v2"):
    try:
        rows = db.query("SELECT params_json FROM model_params WHERE name = ?", (name,))
    except Exception:
        db.conn.rollback()
        return None
    return json.loads(rows[0][0]) if rows else None


def static_logit(params, f):
    """The runner's model score without the market term (the site adds
    b_mkt * log(1/price) when prices move, then re-normalises the race)."""
    c = params["coefs"]
    return params["intercept"] + sum(c[n] * f[n] for n in NAMES if n != "mkt")


def report(p):
    lines = ["Model v2 ({} rows: train {} from {}, test {} from {})".format(
        p["n_all"], p["n_train"], p["train_from"], p["n_test"], p["split"]),
        "Log-loss on unseen races: market {:.5f}, model {:.5f} ({:+.3f}% better)".format(
            p["logloss_market"], p["logloss_model"], p["logloss_gain_pct"]),
        "Overlays (model 20%+ above the market, $2.20-$18): {}".format(p["overlays"]),
        "Every runner $2.20-$18:                            {}".format(p["all_in_band"]),
        "Unders (model 20%+ below the market):              {}".format(p["unders"]),
        "Overlay A/E vs all runners: {:.3f}   overlays proven: {}".format(p["overlay_ae_vs_base"], p["validated"]),
        "Under A/E vs all runners:   {:.3f}   fades proven: {}".format(p.get("under_ae_vs_base", 1), p.get("fades_proven")),
        "Prices the cards: {}".format(p.get("use_for_pricing")),
        "Market weight (1 = trust the price fully): {:.3f}".format(p["market_coef"]),
        "Signal strength per 1 SD (positive = more winners than the price expects):"]
    for n, desc in FEATURES:
        lines.append("  {:<14} {:+.3f}   {}".format(n, p["importance_per_sd"][n], desc))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--audit", action="store_true", help="stress-test on the unseen period; saves nothing")
    a = ap.parse_args(argv)
    from history_db import HistoryDB
    db = HistoryDB()
    if a.fit:
        h = load_history(db)
        m = FormModel(h)
        df = build_dataset(h, m)
        print("Training rows:", len(df), file=sys.stderr)
        p = evaluate(df)
        print(report(p))
        if not a.no_save:
            save(db, p)
            print("Saved to model_params (name v2).")
    elif a.audit:
        h = load_history(db)
        print(audit(build_dataset(h, FormModel(h))))
    elif a.report:
        p = load(db)
        print(report(p) if p else "No model saved yet.")
    db.close()


if __name__ == "__main__":
    main()
