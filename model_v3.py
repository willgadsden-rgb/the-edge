"""Model v3: trained on complete fields from Betfair's free data.

Why: model v2 learned from the Form King history, which holds about 3 of every
10 runners and favours horses that kept racing. Betfair publishes every runner
in every Australian thoroughbred race with its Betfair SP and result
(betfair-datascientists.github.io/data/dataListing), so v3 learns from whole
fields with no survivorship, and is graded against the Betfair SP - the price
a syndicate can actually bet at scale.

    P(win) = softmax over the field of [ b_mkt * log(market chance) + sum(b_k * feature_k) ]

Features come from each horse's earlier runs only: its Betfair history (price,
win/place, spacing, trip changes, prep run) and, where our Form King history has
the horse, the form ratings (Form L and friends from model_v2).

It prices the cards only if it beats the market on races it never saw.

    python model_v3.py --fit       fit, test, print the report, save to the DB
    python model_v3.py --report    print the saved report
"""

import argparse
import io
import json
import math
import re
import sys
import time
import urllib.request
import zipfile
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

BF_BASE = "https://betfair-datascientists.github.io/data/assets/"
FIRST_YEAR = 2021                  # history used for each horse's past runs
TRAIN_FROM = "2022-07-01"          # rows the model learns from (18 months of lookback before it)
SPLIT_DATE = "2026-04-01"          # test on and after
L2 = 2.0
COMMISSION = 0.08
ODDS_BAND = (2.2, 18.0)
FK_FROM = "2024-07-01"

BF_FEATURES = [
    ("first_start", "first starter (no earlier run)"),
    ("log_days", "log days since last run"),
    ("spell", "first-up from a spell (61+ days)"),
    ("backup", "backing up within 10 days"),
    ("prep2", "2nd-up"), ("prep3", "3rd-up"), ("prep4", "4th-up or deeper"),
    ("last_win", "won last start"),
    ("last_place", "placed (not won) last start"),
    ("last_logp", "how fancied last start (log chance)"),
    ("short_beaten", "beaten at $3.50 or shorter last start"),
    ("wins3", "wins in last 3"), ("places3", "placings in last 3"),
    ("career_wr", "career win rate (shrunk)"),
    ("runs_cap", "career runs (capped at 20)"),
    ("light", "lightly raced (1-3 runs)"),
    ("up_trip", "up 200m+ in trip"), ("down_trip", "down 200m+ in trip"),
    ("same_track", "same track as last start"),
    ("travel", "last start in another state"),
    ("mdn_grad", "maiden last start, out of maidens today"),
]
FK_FEATURES = [
    ("has_fk", "in our Form King history (data flag)"),
    ("gap_l", "Form L: rating vs par, lengths"),
    ("no_form", "no rated runs"),
    ("rel", "depth of rated form"),
    ("last_l", "last start rating vs par, lengths"),
    ("best3_l", "best of last 3 vs par, lengths"),
    ("trend", "ratings trend"),
    ("close_last", "beaten 1L or less last start"),
    ("excuse_last", "stewards excuse last start"),
    ("going_suit", "suited by today's going"),
    ("early", "settles back (vs leads)"),
    ("barrier_frac", "wide barrier"),
]
BF_NAMES = [f for f, _ in BF_FEATURES]
FK_NAMES = [f for f, _ in FK_FEATURES]
NAMES = BF_NAMES + FK_NAMES
DESC = dict(BF_FEATURES + FK_FEATURES)

hkey = lambda s: re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*?\)", "", str(s).lower()))


# ------------------------------------------------------------------ Betfair data
KEEP = {"LOCAL_MEETING_DATE": "date", "SCHEDULED_RACE_TIME": "time", "TRACK": "track", "STATE_CODE": "state",
        "RACE_NO": "race_no", "WIN_MARKET_ID": "market_id", "DISTANCE": "distance", "RACE_TYPE": "rtype",
        "TAB_NUMBER": "tab", "SELECTION_NAME": "horse", "WIN_RESULT": "win", "WIN_BSP": "bsp",
        "PLACE_RESULT": "placed", "WIN_PREPLAY_MAX_PRICE_TAKEN": "pp_max",
        "WIN_PREPLAY_MIN_PRICE_TAKEN": "pp_min", "WIN_PREPLAY_WEIGHTED_AVERAGE_PRICE_TAKEN": "pp_wap",
        "WIN_PREPLAY_VOLUME": "pp_vol"}


def _get(url, tries=3):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "the-edge"}), timeout=180).read()
        except Exception as exc:
            if i == tries - 1:
                print("  could not fetch {}: {}".format(url, exc), file=sys.stderr)
                return None
            time.sleep(3)


def _read(raw):
    df = pd.read_csv(io.BytesIO(raw), usecols=lambda c: c in KEEP, low_memory=False).rename(columns=KEEP)
    for c in KEEP.values():                       # older files may lack a column
        if c not in df:
            df[c] = np.nan
    return df


def load_betfair(first_year=FIRST_YEAR, today=None):
    """Every ANZ thoroughbred runner since first_year (yearly zips, then this year's months)."""
    today = today or date.today()
    frames = []
    for y in range(first_year, today.year):
        raw = _get("{}ANZ_Thoroughbreds_{}.zip".format(BF_BASE, y))
        if raw is None:
            continue
        z = zipfile.ZipFile(io.BytesIO(raw))
        for m in z.infolist():
            if m.filename.lower().endswith(".csv"):
                frames.append(_read(z.read(m.filename)))
        print("  {}: {:,} rows so far".format(y, sum(len(f) for f in frames)), file=sys.stderr)
    for mth in range(1, 13):
        if date(today.year, mth, 1) > today:
            break
        raw = _get("{}ANZ_Thoroughbreds_{}_{:02d}.csv".format(BF_BASE, today.year, mth), tries=1)
        if raw is not None:
            frames.append(_read(raw))
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["win"] = (df["win"].astype(str).str.upper() == "WINNER").astype(float)
    df["placed"] = (df["placed"].astype(str).str.upper() == "WINNER").astype(float)
    for c in ("bsp", "pp_max", "pp_min", "pp_wap", "pp_vol", "distance"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["date"].notna() & (df["bsp"] > 1.0) & (df["bsp"] <= 1000.0) & np.isfinite(df["bsp"])].copy()
    df["hkey"] = df["horse"].map(hkey)
    df = df.drop_duplicates(["market_id", "hkey"])
    g = df.groupby("market_id")
    df["n"] = g["hkey"].transform("size")
    df["winners"] = g["win"].transform("sum")
    df = df[(df["n"] >= 4) & (df["winners"] == 1)].copy()          # complete, single-winner races
    df["p_mkt"] = (1 / df["bsp"]) / df.groupby("market_id")["bsp"].transform(lambda s: (1 / s).sum())
    bad = df.groupby("market_id")["p_mkt"].transform(lambda s: (~np.isfinite(s)) .any() or (s <= 0).any())
    if bad.any():
        print("  dropped {:,} runners in {:,} races with an unusable BSP".format(
            int(bad.sum()), int(df.loc[bad, "market_id"].nunique())), file=sys.stderr)
        df = df[~bad].copy()
    return df.sort_values(["date", "time", "market_id"]).reset_index(drop=True)


def add_history_features(df):
    """Per-runner features from the horse's earlier Betfair runs (no look-ahead)."""
    df = df.sort_values(["hkey", "date", "time"]).reset_index(drop=True)
    g = df.groupby("hkey", sort=False)
    prev = lambda c, k=1: g[c].shift(k)
    days = (df["date"] - prev("date")).dt.days
    first = days.isna()
    df["first_start"] = first.astype(float)
    df["log_days"] = np.log1p(days.clip(lower=0)).fillna(math.log1p(28))
    df["spell"] = ((days > 60) & ~first).astype(float)
    df["backup"] = (days <= 10).astype(float)
    new_prep = (first | (days > 60)).astype(int)
    prep_id = new_prep.groupby(df["hkey"], sort=False).cumsum()
    prep_run = df.groupby(["hkey", prep_id], sort=False).cumcount() + 1
    df["prep_run"] = prep_run
    df["prep2"], df["prep3"], df["prep4"] = (prep_run == 2).astype(float), (prep_run == 3).astype(float), (prep_run >= 4).astype(float)
    lw, lp, lb = prev("win"), prev("placed"), prev("bsp")
    df["last_win"] = lw.fillna(0)
    df["last_place"] = ((lp == 1) & (lw != 1)).astype(float)
    df["last_logp"] = np.log(1 / lb).fillna(math.log(1 / 10.0))
    df["short_beaten"] = ((lb <= 3.5) & (lw == 0)).astype(float)
    df["wins3"] = lw.fillna(0) + prev("win", 2).fillna(0) + prev("win", 3).fillna(0)
    df["places3"] = lp.fillna(0) + prev("placed", 2).fillna(0) + prev("placed", 3).fillna(0)
    runs = g.cumcount()
    wins = g["win"].cumsum() - df["win"]
    df["career_runs"] = runs
    df["career_wr"] = (wins + 1) / (runs + 8) - 0.125
    df["runs_cap"] = runs.clip(upper=20) / 20.0
    df["light"] = ((runs >= 1) & (runs <= 3)).astype(float)
    dd = df["distance"] - prev("distance")
    df["up_trip"], df["down_trip"] = (dd >= 200).astype(float), (dd <= -200).astype(float)
    df["same_track"] = (prev("track") == df["track"]).astype(float)
    df["travel"] = (prev("state").notna() & (prev("state") != df["state"])).astype(float)
    is_mdn = df["rtype"].astype(str).str.lower().str.startswith("mdn")
    df["mdn_grad"] = ((prev("rtype").astype(str).str.lower().str.startswith("mdn")) & ~is_mdn & ~first).astype(float)
    return df.sort_values(["date", "time", "market_id"]).reset_index(drop=True)


def add_fk_features(df, db):
    """Left-join the Form King form features (model_v2) on horse + date."""
    for n in FK_NAMES:
        df[n] = 0.0
    try:
        import model_v2
        from form_model import FormModel, load_history
        h = load_history(db)
        fk = model_v2.build_dataset(h, FormModel(h), since=FK_FROM)
        fk["hkey"] = fk["horse_name"].map(hkey)
        fk["date"] = pd.to_datetime(fk["race_date"]).dt.normalize()
        fk = fk.drop_duplicates(["hkey", "date"])
        cols = [n for n in FK_NAMES if n != "has_fk"]
        m = df[["hkey", "date"]].merge(fk[["hkey", "date"] + cols], on=["hkey", "date"], how="left")
        hit = m[cols[0]].notna().values
        for c in cols:
            df[c] = m[c].fillna(0.0).values
        df["has_fk"] = hit.astype(float)
        print("  Form King features joined to {:,} of {:,} Betfair rows since {}".format(
            int(hit.sum()), int((df["date"] >= pd.Timestamp(FK_FROM)).sum()), FK_FROM), file=sys.stderr)
    except Exception as exc:
        print("  Form King features skipped: {}".format(exc), file=sys.stderr)
    return df


# ------------------------------------------------------------------ conditional logit
def _race_index(mid):
    """Rows must be grouped by race. Returns (starts, race_of_row)."""
    change = np.r_[True, mid[1:] != mid[:-1]]
    starts = np.flatnonzero(change)
    return starts, np.cumsum(change) - 1


def _softmax(z, starts, race):
    z = z - np.maximum.reduceat(z, starts)[race]
    e = np.exp(z)
    return e / np.add.reduceat(e, starts)[race]


def fit_clogit(X, y, mid, l2=L2, iters=40):
    starts, race = _race_index(mid)
    k = X.shape[1]
    w = np.zeros(k)
    w[0] = 1.0                                           # column 0 is the market term
    pen = np.full(k, l2); pen[0] = 0.0
    for _ in range(iters):
        p = _softmax(X @ w, starts, race)
        grad = X.T @ (p - y) + pen * w
        M = np.add.reduceat(X * p[:, None], starts, axis=0)
        H = (X * p[:, None]).T @ X - M.T @ M + np.diag(pen) + 1e-8 * np.eye(k)
        step = np.linalg.solve(H, grad)
        w -= step
        if np.abs(step).max() < 1e-7:
            break
    return w


def race_ll(p, y, starts):
    """-log(model chance of the winner), one value per race."""
    return -np.log(np.clip(np.add.reduceat(p * y, starts), 1e-9, 1))


# ------------------------------------------------------------------ evaluation
def _perf(d, pcol=None):
    if not len(d):
        return {"n": 0}
    pnl = np.where(d["win"] == 1, (d["bsp"] - 1) * (1 - COMMISSION), -1.0)
    out = {"n": int(len(d)), "wins": int(d["win"].sum()), "strike": round(float(d["win"].mean()) * 100, 1),
           "avg_bsp": round(float(d["bsp"].mean()), 2), "ae_vs_bsp": round(float(d["win"].sum() / d["p_mkt"].sum()), 3),
           "roi_bsp_net": round(float(pnl.mean()) * 100, 1)}
    if pcol:
        out["ae_vs_model"] = round(float(d["win"].sum() / d[pcol].sum()), 3)
    return out


def _boot(test, stat, n_boot=300, seed=11):
    rng = np.random.default_rng(seed)
    groups = [g for _, g in test.groupby(test["date"])]
    vals = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(groups), len(groups))
        v = stat(pd.concat([groups[i] for i in pick]))
        if v is not None and not np.isnan(v):
            vals.append(v)
    v = np.array(vals)
    return [round(float(np.percentile(v, 2.5)), 5), round(float(np.percentile(v, 97.5)), 5)] if len(v) else [None, None]


def evaluate(df, names=NAMES, label="v3"):
    df = df[df["date"] >= pd.Timestamp(TRAIN_FROM)].sort_values(["date", "time", "market_id"]).reset_index(drop=True)
    split = pd.Timestamp(SPLIT_DATE)
    tr, te = df[df["date"] < split], df[df["date"] >= split].copy()
    mu, sd = tr[names].mean(), tr[names].std().replace(0, 1.0)
    D = lambda d, cols: np.column_stack([np.log(d["p_mkt"].values)] + ([((d[cols] - mu[cols]) / sd[cols]).values] if cols else []))
    w_m = fit_clogit(D(tr, []), tr["win"].values, tr["market_id"].values)
    w_f = fit_clogit(D(tr, names), tr["win"].values, tr["market_id"].values)
    starts, race = _race_index(te["market_id"].values)
    te["p_m"] = _softmax(D(te, []) @ w_m, starts, race)
    te["p_f"] = _softmax(D(te, names) @ w_f, starts, race)
    y = te["win"].values
    ll_raw, ll_m, ll_f = race_ll(te["p_mkt"].values, y, starts), race_ll(te["p_m"].values, y, starts), race_ll(te["p_f"].values, y, starts)
    te["race_gain"] = (ll_m - ll_f)[race] / te["n"].values          # spread so day-resampling sums back to per-race
    gain = float(np.nanmean(ll_m - ll_f))
    ci = _boot(te, lambda d: d["race_gain"].sum() / d["market_id"].nunique())
    # Where it actually prices: races we hold Form King form for (our VIC cards).
    gain_fk = gain_fk_ci = None; n_fk_races = 0
    if "has_fk" in te:
        sub = te[te.groupby("market_id")["has_fk"].transform("mean") >= 0.8]
        if len(sub):
            n_fk_races = int(sub["market_id"].nunique())
            gain_fk = round(float(sub["race_gain"].sum() / n_fk_races), 5)
            gain_fk_ci = _boot(sub, lambda d: d["race_gain"].sum() / d["market_id"].nunique())
    vic = te[te["state"] == "VIC"]
    band = te["bsp"].between(*ODDS_BAND)
    sets = {
        "overlays_120": te[band & (te["p_f"] >= 1.2 * te["p_m"])],
        "overlays_110": te[band & (te["p_f"] >= 1.1 * te["p_m"])],
        "fades_120": te[band & (te["p_f"] <= te["p_m"] / 1.2)],
        "all_in_band": te[band],
        "top_pick": te[te["p_f"] == te.groupby("market_id")["p_f"].transform("max")],
        "favourite": te[te["p_m"] == te.groupby("market_id")["p_m"].transform("max")],
        "strong_25": te[(te["p_f"] >= 0.25) & (te["p_f"] >= te["p_m"])],
        "strong_25_vic": vic[(vic["p_f"] >= 0.25) & (vic["p_f"] >= vic["p_m"])],
        "overlays_120_vic": vic[vic["bsp"].between(*ODDS_BAND) & (vic["p_f"] >= 1.2 * vic["p_m"])],
        "fades_120_vic": vic[vic["bsp"].between(*ODDS_BAND) & (vic["p_f"] <= vic["p_m"] / 1.2)],
    }
    perf = {k: _perf(v, "p_f") for k, v in sets.items()}
    ae = lambda mask: (lambda d: d.loc[mask(d), "win"].sum() / d.loc[mask(d), "p_m"].sum() if mask(d).sum() else np.nan)
    perf["overlays_120"]["ae_ci"] = _boot(te, ae(lambda d: d["bsp"].between(*ODDS_BAND) & (d["p_f"] >= 1.2 * d["p_m"])))
    perf["fades_120"]["ae_ci"] = _boot(te, ae(lambda d: d["bsp"].between(*ODDS_BAND) & (d["p_f"] <= d["p_m"] / 1.2)))
    roi = lambda mask: (lambda d: np.where(d.loc[mask(d), "win"] == 1, (d.loc[mask(d), "bsp"] - 1) * (1 - COMMISSION), -1.0).mean() * 100 if mask(d).sum() else np.nan)
    perf["overlays_120"]["roi_ci"] = _boot(te, roi(lambda d: d["bsp"].between(*ODDS_BAND) & (d["p_f"] >= 1.2 * d["p_m"])))
    perf["strong_25"]["roi_ci"] = _boot(te, roi(lambda d: (d["p_f"] >= 0.25) & (d["p_f"] >= d["p_m"])))

    bands = []
    for lo, hi in ((1, 2.2), (2.2, 4), (4, 7), (7, 12), (12, 18), (18, 40), (40, 1001)):
        g = te[(te["bsp"] >= lo) & (te["bsp"] < hi)]
        if len(g):
            bands.append({"lo": lo, "hi": hi, "n": int(len(g)), "strike": round(float(g["win"].mean()) * 100, 1),
                          "ae_raw": round(float(g["win"].sum() / (1 / g["bsp"]).sum()), 3),
                          "roi_bsp_net": round(float(np.where(g["win"] == 1, (g["bsp"] - 1) * (1 - COMMISSION), -1).mean()) * 100, 1)})

    # refit on everything for live use; coefficients per raw unit
    amu, asd = df[names].mean(), df[names].std().replace(0, 1.0)
    Xa = np.column_stack([np.log(df["p_mkt"].values), ((df[names] - amu) / asd).values])
    w = fit_clogit(Xa, df["win"].values, df["market_id"].values)
    coefs = {n: float(w[i + 1] / asd[n]) for i, n in enumerate(names)}
    o, f = perf["overlays_120"], perf["fades_120"]
    return {
        "label": label, "fitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "train_from": TRAIN_FROM, "split": SPLIT_DATE, "names": list(names),
        "n_train_races": int(tr["market_id"].nunique()), "n_test_races": int(te["market_id"].nunique()),
        "n_test_runs": int(len(te)), "n_all_runs": int(len(df)),
        "ll_market_raw": round(float(np.nanmean(ll_raw)), 5), "ll_market": round(float(np.nanmean(ll_m)), 5),
        "ll_model": round(float(np.nanmean(ll_f)), 5), "gain_per_race": round(gain, 5), "gain_ci": ci,
        "gain_pct": round(gain / float(np.nanmean(ll_m)) * 100, 3),
        "gain_vic": round(float(np.nanmean((ll_m - ll_f)[np.unique(race[(te["state"] == "VIC").values])])), 5) if len(vic) else None,
        "perf": perf, "bands": bands,
        "gain_fk": gain_fk, "gain_fk_ci": gain_fk_ci, "n_test_races_fk": n_fk_races,
        "prices_fk_cards": bool(gain_fk_ci and gain_fk_ci[0] is not None and gain_fk_ci[0] > 0),
        "market_coef": float(w[0]), "market_only_coef": float(w_m[0]),
        "coefs": coefs, "means": {n: float(amu[n]) for n in names},
        "importance_per_sd": {n: round(float(w[i + 1]), 4) for i, n in enumerate(names)},
        "use_for_pricing": bool(ci[0] is not None and ci[0] > 0),
        "overlays_proven": bool(o.get("n", 0) >= 300 and (o.get("roi_ci") or [None])[0] is not None and o["roi_ci"][0] > 0),
        "fades_proven": bool(f.get("n", 0) >= 300 and (f.get("ae_ci") or [None, None])[1] is not None and f["ae_ci"][1] < 1.0),
        "has_fk_share_test": round(float(te["has_fk"].mean()), 3) if "has_fk" in te else 0.0,
    }


# ------------------------------------------------------------------ unbiased Pattern Lab
ANGLES = [
    ("Won last start", "last_win", lambda d: d["last_win"] == 1),
    ("Beaten at $3.50 or shorter last start", "short_beaten", lambda d: d["short_beaten"] == 1),
    ("2+ wins in last 3", "wins3", lambda d: d["wins3"] >= 2),
    ("First starter", "first_start", lambda d: d["first_start"] == 1),
    ("First-up from a spell", "spell", lambda d: d["spell"] == 1),
    ("2nd-up", "prep2", lambda d: d["prep2"] == 1),
    ("3rd-up", "prep3", lambda d: d["prep3"] == 1),
    ("4th-up or deeper", "prep4", lambda d: d["prep4"] == 1),
    ("Backing up within 10 days", "backup", lambda d: d["backup"] == 1),
    ("Up 200m+ in trip", "up_trip", lambda d: d["up_trip"] == 1),
    ("Down 200m+ in trip", "down_trip", lambda d: d["down_trip"] == 1),
    ("Maiden winner stepping out of maidens", "mdn_grad", lambda d: (d["mdn_grad"] == 1) & (d["last_win"] == 1)),
    ("Last start interstate", "travel", lambda d: d["travel"] == 1),
    ("Lightly raced (1-3 runs)", "light", lambda d: d["light"] == 1),
    ("Priced under $2.20", None, lambda d: d["bsp"] < 2.2),
    ("Priced $2.20 to $4", None, lambda d: d["bsp"].between(2.2, 4, inclusive="left")),
    ("Priced $4 to $7", None, lambda d: d["bsp"].between(4, 7, inclusive="left")),
    ("Priced $7 to $12", None, lambda d: d["bsp"].between(7, 12, inclusive="left")),
    ("Priced $12 to $18", None, lambda d: d["bsp"].between(12, 18, inclusive="left")),
    ("Priced $18+", None, lambda d: d["bsp"] >= 18),
]


def angle_table(df, state="VIC", since="2023-01-01", split="2025-01-01"):
    d = df[(df["state"] == state) & (df["date"] >= pd.Timestamp(since))]
    out = []
    for name, _, mask in ANGLES:
        row = {"angle": name}
        for tag, part in (("old", d[d["date"] < pd.Timestamp(split)]), ("recent", d[d["date"] >= pd.Timestamp(split)])):
            g = part[mask(part)]
            row["n_" + tag] = int(len(g))
            row["ae_" + tag] = round(float(g["win"].sum() / g["p_mkt"].sum()), 3) if len(g) and g["p_mkt"].sum() > 0 else None
            row["roi_" + tag] = round(float(np.where(g["win"] == 1, (g["bsp"] - 1) * (1 - COMMISSION), -1).mean()) * 100, 1) if len(g) else None
        g = d[mask(d)]
        row["strike"] = round(float(g["win"].mean()) * 100, 1) if len(g) else None
        out.append(row)
    return {"state": state, "since": since, "split": split, "rows": out, "runs": int(len(d)), "races": int(d["market_id"].nunique())}


# ------------------------------------------------------------------ live scoring
def live_bf_features(runs, today, distance, track, is_maiden_today, vic_tracks=None, career=None):
    """The same history features for a runner on today's card, from its Form King
    past runs (newest first; each: date ms/ISO, pos, bsp or sp, dist, track, nrun, class)."""
    f = dict.fromkeys(BF_NAMES, 0.0)
    today = pd.Timestamp(today)

    def when(r):
        d = r.get("date")
        return pd.to_datetime(d, unit="ms") if isinstance(d, (int, float)) else pd.to_datetime(d, errors="coerce")

    past = sorted([(when(r), r) for r in (runs or []) if r.get("pos")], key=lambda x: x[0], reverse=True)
    past = [(d.tz_localize(None) if getattr(d, "tzinfo", None) else d, r) for d, r in past if pd.notna(d)]
    past = [(d, r) for d, r in past if d.normalize() < today.normalize()]
    c_runs, c_wins = (career or (len(past), sum(1 for _, r in past if r.get("pos") == 1)))
    if not past:
        f["first_start"] = 1.0 if not c_runs else 0.0
        f["log_days"] = math.log1p(28)
        f["last_logp"] = math.log(1 / 10.0)
        f["career_wr"] = (c_wins + 1) / (c_runs + 8) - 0.125
        f["runs_cap"] = min(c_runs, 20) / 20.0
        return f
    placed = lambda r: 1.0 if r.get("pos") and r["pos"] <= (2 if (r.get("nrun") or 8) < 8 else 3) else 0.0
    price = lambda r: r.get("bsp") or r.get("sp")
    d0, r0 = past[0]
    days = max(0, (today.normalize() - d0.normalize()).days)
    f["log_days"] = math.log1p(days)
    f["spell"] = float(days > 60)
    f["backup"] = float(days <= 10)
    prep = 1
    if days <= 60:
        prep = 2
        for (da, _), (db_, _) in zip(past, past[1:]):
            if (da - db_).days > 60:
                break
            prep += 1
    f["prep2"], f["prep3"], f["prep4"] = float(prep == 2), float(prep == 3), float(prep >= 4)
    f["last_win"] = float(r0.get("pos") == 1)
    f["last_place"] = float(placed(r0) == 1 and r0.get("pos") != 1)
    p0 = price(r0)
    f["last_logp"] = math.log(1 / p0) if p0 and p0 > 1 else math.log(1 / 10.0)
    f["short_beaten"] = float(bool(p0) and p0 <= 3.5 and r0.get("pos") != 1)
    f["wins3"] = float(sum(1 for _, r in past[:3] if r.get("pos") == 1))
    f["places3"] = float(sum(placed(r) for _, r in past[:3]))
    f["career_wr"] = (c_wins + 1) / (c_runs + 8) - 0.125
    f["runs_cap"] = min(c_runs, 20) / 20.0
    f["light"] = float(1 <= c_runs <= 3)
    if distance and r0.get("dist"):
        f["up_trip"], f["down_trip"] = float(distance - r0["dist"] >= 200), float(distance - r0["dist"] <= -200)
    f["same_track"] = float(bool(track) and str(r0.get("track") or "").lower() == str(track).lower())
    if vic_tracks is not None and r0.get("track"):
        f["travel"] = float(str(r0["track"]).lower() not in vic_tracks)
    f["mdn_grad"] = float(str(r0.get("class") or "").upper().startswith("MDN") and not is_maiden_today)
    return f


def static_score(params, feats):
    """Runner's score without the market term (site adds market_coef * log(1/price))."""
    c = params["coefs"]
    return sum(c[n] * feats.get(n, 0.0) for n in params["names"])


# ------------------------------------------------------------------ report / storage
def report(p, angles=None):
    P = p["perf"]
    L = ["Model {} on complete Betfair fields: trained on {:,} races, tested on {:,} unseen races ({:,} runners) from {}".format(
        p["label"], p["n_train_races"], p["n_test_races"], p["n_test_runs"], p["split"]),
        "Log-loss per race: Betfair SP as-is {:.5f} | market (best fit) {:.5f} | model {:.5f}".format(p["ll_market_raw"], p["ll_market"], p["ll_model"]),
        "Gain over the market per race: {:+.5f} ({:+.3f}%)  95% CI {}   VIC only {}".format(p["gain_per_race"], p["gain_pct"], p["gain_ci"], p["gain_vic"]),
        "On races we hold Form King form for: {:,} races, gain {} 95% CI {}  PRICES FK CARDS: {}".format(
            p.get("n_test_races_fk") or 0, p.get("gain_fk"), p.get("gain_fk_ci"), p.get("prices_fk_cards")),
        "PRICES THE CARDS: {}   overlays proven: {}   fades proven: {}   (Form King features on {:.0%} of test rows)".format(
            p["use_for_pricing"], p["overlays_proven"], p["fades_proven"], p.get("has_fk_share_test", 0)),
        "Backing at Betfair SP after {:.0%} commission, unseen races:".format(COMMISSION)]
    for k in ("favourite", "top_pick", "strong_25", "strong_25_vic", "overlays_110", "overlays_120", "overlays_120_vic", "fades_120", "fades_120_vic", "all_in_band"):
        L.append("  {:<17} {}".format(k, P.get(k)))
    L.append("Betfair SP by price band (A/E vs raw 1/BSP):")
    for b in p["bands"]:
        L.append("  ${:<5}-${:<6} n={:<6} strike {:>5.1f}%  A/E {:.3f}  ROI net {:+.1f}%".format(b["lo"], b["hi"], b["n"], b["strike"], b["ae_raw"], b["roi_bsp_net"]))
    L.append("Market weight {:.3f} (market-only fit {:.3f}). Signal strength per 1 SD:".format(p["market_coef"], p["market_only_coef"]))
    for n, v in sorted(p["importance_per_sd"].items(), key=lambda kv: -abs(kv[1])):
        L.append("  {:<13} {:+.4f}   {}".format(n, v, DESC.get(n, "")))
    if angles:
        L.append("Pattern Lab (unbiased): {} since {}, {:,} runs; A/E vs Betfair SP chance, older | recent (split {})".format(
            angles["state"], angles["since"], angles["runs"], angles["split"]))
        for r in angles["rows"]:
            L.append("  {:<40} n {:>6}|{:<6} A/E {}|{}  ROI net {}|{}  strike {}%".format(
                r["angle"], r["n_old"], r["n_recent"], r["ae_old"], r["ae_recent"], r["roi_old"], r["roi_recent"], r["strike"]))
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--no-fk", action="store_true")
    a = ap.parse_args(argv)
    import model_v2
    from history_db import HistoryDB
    db = HistoryDB()
    if a.fit:
        t0 = time.time()
        df = add_history_features(load_betfair())
        print("Betfair rows: {:,} ({:,} races) in {:.0f}s".format(len(df), df["market_id"].nunique(), time.time() - t0), file=sys.stderr)
        if not a.no_fk:
            df = add_fk_features(df, db)
        else:
            for n in FK_NAMES:
                df[n] = 0.0
        base = evaluate(df, BF_NAMES, "v3-market-form")
        full = evaluate(df, NAMES, "v3")
        angles = angle_table(df)
        print("=== Betfair-history features only ===")
        print(report(base))
        print("=== With Form King ratings added ===")
        print(report(full, angles))
        best = full if full["gain_per_race"] >= base["gain_per_race"] else base
        best["compared"] = {"market_form_gain": base["gain_per_race"], "with_ratings_gain": full["gain_per_race"]}
        if not a.no_save:
            model_v2.save(db, best, name="v3")
            model_v2.save(db, dict(angles, fitted_at=best["fitted_at"]), name="angles_bf")
            print("Saved model_params v3 ({}) and angles_bf.".format(best["label"]))
    elif a.report:
        p = model_v2.load(db, "v3")
        print(report(p) if p else "No v3 saved yet.")
    db.close()


if __name__ == "__main__":
    main()
