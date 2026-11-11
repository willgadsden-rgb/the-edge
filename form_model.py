"""Form model v2: one rating, in lengths, from the history database.

Everything here is measured from the runs in history_db (no hand-set
weights for ability): Form King's per-run weightForAgeRating is the run
rating, the lengths value of a rating point is fitted from horses that met
in the same race, and race pars are the median winning rating for the class
at that tier of track.

Public pieces
    load_history(db)            -> DataFrame of every run joined to its race
    FormModel(history)          -> calibration (lengths per point, pars)
      .rate(horse, distance, going, class_label, track, race_date)
      .horse_runs(horse)        -> that horse's runs, newest first
      .records(horse)           -> records by prep stage, going, trip, track, spacing
      .prep_population()        -> win % and A/E vs SP by prep stage, all horses
"""

import math
import re
from datetime import date

import pandas as pd

# --- classification helpers ---------------------------------------------------
METRO = ("flemington", "caulfield", "moonee valley", "the valley", "sandown", "randwick",
         "rosehill", "warwick farm", "canterbury", "eagle farm", "doomben", "morphettville",
         "ascot", "belmont")
PROVINCIAL = ("geelong", "ballarat", "bendigo", "mornington", "cranbourne", "pakenham",
              "kilmore", "seymour", "sale", "warrnambool", "newcastle", "kembla grange",
              "hawkesbury", "gosford", "wyong", "gold coast", "sunshine coast", "ipswich",
              "toowoomba", "murray bridge", "gawler", "bunbury", "pinjarra")

EXCUSE_WORDS = ("checked", "held up", "blocked", "crowded", "eased", "laid out", "bumped",
                "steadied", "tightened", "lost ground", "lame", "bled", "slow to begin",
                "slowly away", "began awkwardly", "hampered", "inconvenienced", "awkwardly",
                "shifted", "no clear run", "pulled up", "rider lost", "lost a plate",
                "dislodged", "fractious", "over-raced", "overraced", "hung")

RECENCY_HALF_LIFE_DAYS = 120
PAR_SHRINK_RACES = 30        # races needed before a track-tier par stands on its own
EXCUSE_WEIGHT = 0.5


def class_group(*labels):
    """Class group from a Form King restriction code, race name or class label.

    'MDN.3+..S' / '3yo+ Mdn Plate' / 'Maiden' -> 'Maiden'; '(Bm58)' / 'Benchmark 58'
    / '64+...' -> 'BM58' etc.; 'Hcp (C1)' / 'Class 1' -> 'Class 1'.
    """
    text = " ".join(str(x) for x in labels if x)
    t = text.lower()
    code = (labels[0] or "").split(".")[0].upper() if labels and labels[0] else ""
    if re.search(r"(gr|group)\s*1\b|\bg1\b", t) or code in ("G1", "GRP1"):
        return "Group 1"
    if re.search(r"(gr|group)\s*[23]\b|\bg[23]\b", t) or code in ("G2", "G3", "GRP2", "GRP3"):
        return "Group 2-3"
    if re.search(r"\blisted\b|\blr\b", t) or code in ("LR", "LISTED"):
        return "Listed"
    if re.search(r"mdn|maiden", t) or code.startswith("MDN"):
        return "Maiden"
    m = re.search(r"\b(?:bm|benchmark)\s*(\d{2,3})", t) or re.search(r"(?:hcp|rated)\s*\((\d{2,3})\)", t)
    if m:
        return "BM{}".format(int(m.group(1)))
    m = re.search(r"\((?:c|cl)\s*(\d)\)|\bclass\s*(\d)\b|\bcl(\d)\b", t)
    if m:
        return "Class {}".format(next(g for g in m.groups() if g))
    if re.match(r"^C\d", code):
        return "Class {}".format(code[1])
    m = re.match(r"^(\d{2,3})\+?$", code)
    if m:
        return "BM{}".format(int(m.group(1)))
    if re.search(r"open|quality|stakes|\bsw\b|\bwfa\b|cup", t) or code.startswith("OPEN"):
        return "Open/Stakes"
    return "Other"


def track_tier(track):
    t = (track or "").lower()
    if any(t.startswith(x) for x in METRO):
        return "Metro"
    if any(t.startswith(x) for x in PROVINCIAL):
        return "Provincial"
    return "Country"


def going_band(going):
    parts = (going or "").split()
    if not parts:
        return None
    word = parts[0].lower()
    if word.startswith("synth") or word in ("aw", "all"):
        return "Synthetic"
    num = None
    if len(parts) > 1:
        try:
            num = int(parts[1])
        except ValueError:
            num = None
    if num is not None:
        return "Good" if num <= 4 else ("Soft" if num <= 7 else "Heavy")
    return {"firm": "Good", "fast": "Good", "good": "Good", "dead": "Good",
            "soft": "Soft", "slow": "Soft", "heavy": "Heavy"}.get(word)


def distance_band(d):
    if not d or (isinstance(d, float) and math.isnan(d)):
        return None
    d = int(d)
    if d < 1100:
        return "Up to 1099m"
    if d < 1400:
        return "1100-1399m"
    if d < 1700:
        return "1400-1699m"
    if d < 2100:
        return "1700-2099m"
    return "2100m+"


def spacing_band(days):
    if days is None or (isinstance(days, float) and math.isnan(days)):
        return None
    days = int(days)
    if days <= 14:
        return "Up to 14 days"
    if days <= 28:
        return "15-28 days"
    if days <= 60:
        return "29-60 days"
    if days <= 120:
        return "61-120 days"
    return "Spell (121+ days)"


def stage_label(prep):
    if prep is None or (isinstance(prep, float) and math.isnan(prep)):
        return None
    p = int(prep)
    return {1: "1st-up", 2: "2nd-up", 3: "3rd-up", 4: "4th-up"}.get(p, "5th-up+")


def is_excuse(comment):
    c = (comment or "").lower()
    return any(w in c for w in EXCUSE_WORDS)


# --- loading -------------------------------------------------------------------
HISTORY_SQL = """
SELECT x.race_id, x.horse_name, x.finish_pos, x.margin, x.field_size, x.barrier, x.weight,
       x.jockey, x.settle_pos, x.sp, x.bsp, x.wfa_rating, x.race_in_prep, x.days_since_prev,
       x.stewards_comment, x.next_runs, x.next_wins, x.source, x.race_in_career,
       x.open_fluc, x.top_fluc, x.pos_800, x.pos_400, x.track_speed,
       r.race_date, r.track, r.state, r.distance, r.going, r.restrictions, r.race_name,
       r.field_size AS race_field_size
FROM runs x JOIN races r ON r.race_id = x.race_id
"""


def load_history(db):
    """Every run joined to its race, with derived columns, as a DataFrame."""
    rows = db.query(HISTORY_SQL)
    cols = ["race_id", "horse_name", "finish_pos", "margin", "field_size", "barrier", "weight",
            "jockey", "settle_pos", "sp", "bsp", "wfa_rating", "race_in_prep", "days_since_prev",
            "stewards_comment", "next_runs", "next_wins", "source", "race_in_career",
            "open_fluc", "top_fluc", "pos_800", "pos_400", "track_speed", "race_date", "track", "state",
            "distance", "going", "restrictions", "race_name", "race_field_size"]
    df = pd.DataFrame([tuple(r) for r in rows], columns=cols)
    return prepare(df)


def prepare(df):
    df = df.copy()
    for c in ("finish_pos", "margin", "field_size", "barrier", "weight", "settle_pos", "sp", "bsp",
              "wfa_rating", "race_in_prep", "days_since_prev", "next_runs", "next_wins",
              "distance", "race_field_size", "open_fluc", "top_fluc", "pos_800", "pos_400", "track_speed"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df.loc[df["wfa_rating"] <= 0, "wfa_rating"] = float("nan")    # 0 = unrated
    df["field_size"] = df["field_size"].fillna(df["race_field_size"])
    df["race_date"] = pd.to_datetime(df["race_date"], errors="coerce")
    df["class_group"] = [class_group(a, b) for a, b in zip(df["restrictions"], df["race_name"])]
    df["tier"] = df["track"].map(track_tier)
    df["going_band"] = df["going"].map(going_band)
    df["dist_band"] = df["distance"].map(distance_band)
    df["stage"] = df["race_in_prep"].map(stage_label)
    df["spacing"] = df["days_since_prev"].where(df["race_in_prep"] != 1).map(spacing_band)
    df.loc[df["race_in_prep"] == 1, "spacing"] = "Spell (1st-up)"
    # Lengths behind the winner (0 for the winner); margins are stored as
    # +winning margin for the winner and -lengths beaten for the rest.
    df["beaten"] = df["margin"].where(df["finish_pos"] != 1, 0.0).abs()
    df.loc[(df["finish_pos"] != 1) & (df["margin"] > 0), "beaten"] = float("nan")
    df["excuse"] = df["stewards_comment"].map(is_excuse)
    return df


# --- the model -----------------------------------------------------------------
class FormModel:
    def __init__(self, history):
        self.h = history
        self._by_horse = {k: g.sort_values("race_date", ascending=False)
                          for k, g in history.groupby("horse_name")} if len(history) else {}
        self.lpp_table = self._fit_lengths_per_point()
        self.pars, self.class_pars = self._fit_pars()

    # Lengths per rating point, by distance band, from horses that met.
    def _fit_lengths_per_point(self):
        r = self.h.dropna(subset=["wfa_rating", "beaten", "distance"])
        r = r[(r["distance"] >= 800) & (r["distance"] <= 3200)][
            ["race_id", "horse_name", "wfa_rating", "beaten", "distance"]]
        out = {}
        if len(r) < 50:
            return {950: 0.5, 1250: 0.55, 1550: 0.6, 1900: 0.67, 2400: 0.74}
        p = r.merge(r, on="race_id", suffixes=("_a", "_b"))
        p = p[p["horse_name_a"] < p["horse_name_b"]]
        p["dr"] = p["wfa_rating_a"] - p["wfa_rating_b"]
        p["dl"] = p["beaten_b"] - p["beaten_a"]
        p = p[p["dl"].abs() <= 15]
        bands = [(800, 1100, 950), (1100, 1400, 1250), (1400, 1700, 1550), (1700, 2100, 1900),
                 (2100, 3201, 2400)]
        for lo, hi, mid in bands:
            q = p[(p["distance_a"] >= lo) & (p["distance_a"] < hi)]
            denom = (q["dr"] ** 2).sum()
            if len(q) >= 30 and denom > 0:
                out[mid] = float((q["dr"] * q["dl"]).sum() / denom)
        return out or {950: 0.5, 1250: 0.55, 1550: 0.6, 1900: 0.67, 2400: 0.74}

    def lengths_per_point(self, distance):
        pts = sorted(self.lpp_table.items())
        if not distance:
            return pts[len(pts) // 2][1]
        if distance <= pts[0][0]:
            return pts[0][1]
        if distance >= pts[-1][0]:
            return pts[-1][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= distance <= x1:
                return y0 + (y1 - y0) * (distance - x0) / (x1 - x0)
        return pts[-1][1]

    # Median winning rating by class (and by class x track tier, shrunk).
    def _fit_pars(self):
        w = self.h[(self.h["finish_pos"] == 1) & self.h["wfa_rating"].notna()]
        w = w.drop_duplicates("race_id")
        class_pars = w.groupby("class_group")["wfa_rating"].agg(["median", "count"])
        tier = w.groupby(["class_group", "tier"])["wfa_rating"].agg(["median", "count"])
        pars = {}
        for (cg, t), row in tier.iterrows():
            base = class_pars.loc[cg, "median"]
            n = row["count"]
            pars[(cg, t)] = {"par": float((n * row["median"] + PAR_SHRINK_RACES * base) / (n + PAR_SHRINK_RACES)),
                             "races": int(n)}
        cp = {cg: {"par": float(r["median"]), "races": int(r["count"])} for cg, r in class_pars.iterrows()}
        return pars, cp

    def par(self, class_label, track):
        cg = class_group(class_label)
        t = track_tier(track)
        if (cg, t) in self.pars:
            return cg, t, self.pars[(cg, t)]
        if cg in self.class_pars:
            return cg, t, self.class_pars[cg]
        return cg, t, None

    # One horse.
    def horse_runs(self, horse):
        return self._by_horse.get(horse, self.h.iloc[0:0])

    def rate(self, horse, distance=None, going=None, class_label=None, track=None, race_date=None):
        """Today's rating for a horse, in Form King points and in lengths vs par."""
        runs = self.horse_runs(horse)
        runs = runs[runs["wfa_rating"].notna()]
        if race_date is not None:
            runs = runs[runs["race_date"] < pd.Timestamp(race_date)]
        cg, tier, par = self.par(class_label, track)
        out = {"class_group": cg, "tier": tier, "par": par["par"] if par else None,
               "par_races": par["races"] if par else 0, "runs_used": 0}
        if runs.empty:
            out.update(ability=None, ceiling=None, reliability=0.0, gap_l=None,
                       ceiling_gap_l=None, confidence="No form", badge="")
            return out
        today = pd.Timestamp(race_date) if race_date is not None else pd.Timestamp(date.today())
        age_days = (today - runs["race_date"]).dt.days.clip(lower=0).fillna(365)
        w_recency = 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
        gb = going_band(going) if going else None
        w_going = runs["going_band"].map(lambda g: 1.0 if (gb is None or g == gb) else 0.5)
        if distance:
            dd = (runs["distance"] - distance).abs()
            w_dist = dd.map(lambda x: 1.0 if x <= 200 else (0.7 if x <= 400 else 0.4)).fillna(0.4)
        else:
            w_dist = 1.0
        w_exc = runs["excuse"].map(lambda e: EXCUSE_WEIGHT if e else 1.0)
        w = w_recency * w_going * w_dist * w_exc
        ability = float((runs["wfa_rating"] * w).sum() / w.sum())
        reliability = float(w.sum() ** 2 / (w ** 2).sum())        # effective number of runs
        relevant = runs[(w_going == 1.0) & ((w_dist == 1.0) if distance else True)]
        recent = runs.head(6)
        ceiling = float((relevant if len(relevant) else recent)["wfa_rating"].head(6).max())
        lpp = self.lengths_per_point(distance)
        gap = (ability - par["par"]) * lpp if par else None
        cgap = (ceiling - par["par"]) * lpp if par else None
        relevant_n = int(len(relevant))
        conf = "High" if reliability >= 3 and relevant_n >= 2 else ("Medium" if reliability >= 1.5 else "Low")
        badge = ""
        if gap is not None:
            if gap >= 3:
                badge = "Class edge"
            elif abs(gap) <= 1:
                badge = "Right in it"
            elif gap <= -3:
                badge = "Needs to improve"
        out.update(ability=round(ability, 1), ceiling=round(ceiling, 1),
                   reliability=round(reliability, 1), runs_used=int(len(runs)),
                   relevant_runs=relevant_n, lpp=round(lpp, 3),
                   gap_l=round(gap, 1) if gap is not None else None,
                   ceiling_gap_l=round(cgap, 1) if cgap is not None else None,
                   confidence=conf, badge=badge)
        return out

    def records(self, horse):
        """Records for one horse by prep stage, going, trip, track and spacing."""
        runs = self.horse_runs(horse)
        runs = runs[runs["finish_pos"].notna()]
        out = {}
        for key, col, order in (
                ("Prep stage", "stage", ["1st-up", "2nd-up", "3rd-up", "4th-up", "5th-up+"]),
                ("Going", "going_band", ["Good", "Soft", "Heavy", "Synthetic"]),
                ("Distance", "dist_band", ["Up to 1099m", "1100-1399m", "1400-1699m", "1700-2099m", "2100m+"]),
                ("Spacing", "spacing", ["Spell (1st-up)", "Up to 14 days", "15-28 days", "29-60 days", "61-120 days", "Spell (121+ days)"]),
                ("Track", "track", None)):
            rows = []
            groups = runs.groupby(col)
            keys = order if order else sorted(groups.groups, key=lambda k: -len(groups.groups[k]))
            for k in keys:
                if k not in groups.groups:
                    continue
                g = groups.get_group(k)
                rows.append({key: k, "Starts": len(g), "Wins": int((g["finish_pos"] == 1).sum()),
                             "2nds": int((g["finish_pos"] == 2).sum()), "3rds": int((g["finish_pos"] == 3).sum()),
                             "Win %": round(100 * (g["finish_pos"] == 1).mean()),
                             "Avg rating": round(g["wfa_rating"].mean(), 1) if g["wfa_rating"].notna().any() else None})
            out[key] = pd.DataFrame(rows)
        return out

    def best_stage(self, horse, min_runs=2, margin=1.0):
        runs = self.horse_runs(horse).dropna(subset=["wfa_rating", "stage"])
        if len(runs) < 3:
            return None
        overall = runs["wfa_rating"].mean()
        g = runs.groupby("stage")["wfa_rating"].agg(["mean", "count"])
        g = g[g["count"] >= min_runs]
        if g.empty:
            return None
        best = g["mean"].idxmax()
        return best if g.loc[best, "mean"] - overall >= margin else None

    def track_stats(self, track, distance=None):
        """How winners have raced at a track, counted from the winners on file:
        races, % won by the horse that settled first, % won from the inside half
        of the draw, and average winning barrier (with a near-trip split)."""
        if not track:
            return None
        w = self.h[(self.h["finish_pos"] == 1) & (self.h["track"].str.lower() == track.lower())]
        w = w.drop_duplicates("race_id")

        def summary(g):
            if g.empty:
                return None
            settled = g[g["settle_pos"].notna()]
            drawn = g[g["barrier"].notna() & (g["barrier"] > 0)]
            halves = drawn[drawn["field_size"].notna() & (drawn["field_size"] >= 4)]
            return {
                "races": int(len(g)),
                "leader_pct": round(100 * (settled["settle_pos"] == 1).mean()) if len(settled) else None,
                "leader_n": int(len(settled)),
                "inside_pct": round(100 * (halves["barrier"] <= halves["field_size"] / 2).mean()) if len(halves) else None,
                "inside_n": int(len(halves)),
                "avg_barrier": round(float(drawn["barrier"].mean()), 1) if len(drawn) else None,
            }

        out = {"track": track, "all": summary(w)}
        if distance:
            near = w[(w["distance"] - distance).abs() <= 200]
            out["near_trip"] = summary(near)
        return out if out["all"] else None

    def prep_population(self):
        """Win % and A/E against SP by prep stage across every horse on file.

        A/E uses raw SP (bookmaker margin included), so 1.00 is above what an
        average runner achieves; compare stages with each other."""
        r = self.h[self.h["stage"].notna() & self.h["finish_pos"].notna() & (self.h["source"] != "placings")]
        rows = []
        for st_ in ["1st-up", "2nd-up", "3rd-up", "4th-up", "5th-up+"]:
            g = r[r["stage"] == st_]
            if g.empty:
                continue
            sp = g["sp"].where(g["sp"] > 1)
            wins = int((g["finish_pos"] == 1).sum())
            exp = (1 / sp).sum()
            rows.append({"Prep stage": st_, "Runs": len(g), "Wins": wins,
                         "Win %": round(100 * wins / len(g), 1),
                         "A/E vs SP": round(wins / exp, 2) if exp else None})
        return pd.DataFrame(rows)


if __name__ == "__main__":
    from history_db import HistoryDB
    db = HistoryDB()
    m = FormModel(load_history(db))
    print("lengths per point:", {k: round(v, 3) for k, v in m.lpp_table.items()})
    print("class pars:", {k: round(v["par"], 1) for k, v in sorted(m.class_pars.items())})
    print(m.prep_population())
