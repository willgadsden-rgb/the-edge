"""Rising Stars: lightly raced horses rating at or near a winning standard and
still improving. Built from the history database with the form model, rebuilt
on every harvest and published to public.edge_stars.

A horse qualifies when (all from real runs, nothing estimated):
  - it has raced in the last 60 days and has 8 or fewer career starts,
  - it has at least 2 rated runs,
  - its latest run was a new peak or its ratings are trending up 2+ points, and
  - that latest run was within 1.5 lengths of the winning par for the class it ran in.
The score then rewards: lengths above par, the size of the new peak, winning,
winners coming out of the race, and being very lightly raced.
"""

from datetime import date, timedelta

import pandas as pd

MAX_STARTS = 8
RECENT_DAYS = 60
TOP_N = 40


def find_stars(model, today=None, horses=None):
    today = pd.Timestamp(today or date.today())
    h = model.h
    recent = h[(h["race_date"] >= today - timedelta(days=RECENT_DAYS)) & (h["race_date"] <= today) & h["finish_pos"].notna()]
    out = []
    for name in recent["horse_name"].unique():
        runs = model.horse_runs(name)
        runs = runs[runs["finish_pos"].notna() & (runs["race_date"] <= today)]
        rated = runs[runs["wfa_rating"].notna()]
        if len(rated) < 2:
            continue
        career = runs["race_in_career"].max() if "race_in_career" in runs and runs["race_in_career"].notna().any() else len(runs)
        if pd.isna(career) or career > MAX_STARTS or len(runs) > MAX_STARTS:
            continue
        last = runs.iloc[0]
        if pd.isna(last["wfa_rating"]):
            continue                                         # latest run not rated yet
        r0 = float(last["wfa_rating"])
        earlier = rated.iloc[1:]["wfa_rating"]
        prev_best = float(earlier.max())
        trend = r0 - float(earlier.head(3).mean())
        _, _, par = model.par(last["restrictions"] or last["race_name"], last["track"])
        if not par:
            continue
        lpp = model.lengths_per_point(last["distance"])
        vs_par = (r0 - par["par"]) * lpp
        new_peak = r0 > prev_best
        if not (new_peak or trend >= 2.0) or vs_par < -1.5:
            continue
        won = last["finish_pos"] == 1
        nw = last.get("next_wins")
        nw = int(nw) if pd.notna(nw) else 0
        score = (min(max(vs_par, 0), 6) * 2 + min(max(r0 - prev_best, 0), 8) * 1.5 + (2 if won else 0)
                 + min(nw, 3) + (1 if career <= 4 else 0) + min(max(trend, 0), 6) * 0.5)
        reasons = []
        if vs_par >= 0:
            reasons.append("ran {:.1f}L above the winning par".format(vs_par))
        else:
            reasons.append("within {:.1f}L of the winning par".format(abs(vs_par)))
        if new_peak:
            reasons.append("new peak, up {:.1f} points".format(r0 - prev_best))
        if trend >= 2:
            reasons.append("ratings up {:.1f} on its earlier runs".format(trend))
        if won:
            m = last.get("margin")
            reasons.append("won" + (" by {:.1f}L".format(abs(m)) if pd.notna(m) and m else ""))
        if nw:
            reasons.append("{} winner{} out of the race since".format(nw, "s" if nw > 1 else ""))
        info = (horses or {}).get(name, {})
        out.append({
            "horse_name": name, "score": round(float(score), 1), "career_starts": int(career),
            "wins": int((runs["finish_pos"] == 1).sum()), "last_date": last["race_date"].date().isoformat(),
            "last_track": last["track"], "last_distance": int(last["distance"]) if pd.notna(last["distance"]) else None,
            "last_class": last["restrictions"] or last["race_name"], "last_pos": int(last["finish_pos"]),
            "last_rating": round(r0, 1), "prev_best": round(prev_best, 1), "vs_par_l": round(float(vs_par), 1),
            "trend": round(float(trend), 1), "next_wins": nw, "reasons": "; ".join(reasons),
            "ratings": ",".join("{:.0f}".format(x) for x in rated["wfa_rating"].head(6).tolist()[::-1]),
            "sire": info.get("sire"), "trainer": info.get("trainer"), "foal_date": info.get("foal_date"),
        })
    out.sort(key=lambda r: -r["score"])
    return out[:TOP_N]
