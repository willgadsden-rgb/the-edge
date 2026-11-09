"""Runner career profile for the DETAILS drawer (v2: real data only).

Every value comes from the Form King card (`fk_json`: connections, breeding,
career/track/distance/prep records, jockey and trainer 12-month form) or from
the runner's real past runs (`runs_json`, up to 12). Anything Form King does
not supply is shown as "-" - nothing is generated from the horse's name.

The returned dict keeps the shape the drawer in app.py renders.
"""

from prep_engine import profile_runner, STAGE_LABELS

SEX_NAMES = {"G": "Gelding", "M": "Mare", "C": "Colt", "F": "Filly", "H": "Horse", "R": "Rig"}
DASH = "-"


def _rec(form_string):
    """Form King record '8:0-1-1' -> display '8: 0-1-1' (missing -> '0: 0-0-0')."""
    if not form_string or ":" not in str(form_string):
        return "0: 0-0-0"
    starts, rest = str(form_string).split(":", 1)
    return "{}: {}".format(starts.strip(), rest.strip())


def _parse(form_string):
    """'8:0-1-1' -> (starts, wins, seconds, thirds); missing -> zeros."""
    try:
        starts, rest = str(form_string).split(":", 1)
        w, s, t = (int(x) for x in rest.split("-"))
        return int(starts), w, s, t
    except Exception:
        return 0, 0, 0, 0


def _pct(v):
    return "{:.0f}%".format(v) if isinstance(v, (int, float)) else DASH


def _going_band(going):
    """Going band of a past run from its going text ('Soft 6', 'Heavy 8', 'Synthetic')."""
    parts = (going or "").split()
    if not parts:
        return None
    word = parts[0].lower()
    if word.startswith("synth") or word == "aw":
        return "Synthetic"
    num = None
    if len(parts) > 1:
        try:
            num = int(parts[1])
        except ValueError:
            pass
    if num is not None:
        return "Good" if num <= 4 else ("Soft" if num <= 7 else "Heavy")
    return {"firm": "Good", "fast": "Good", "good": "Good", "dead": "Good",
            "soft": "Soft", "slow": "Soft", "heavy": "Heavy"}.get(word)


def _avg(vals):
    vals = [float(v) for v in vals if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals), 1) if vals else None


def generate_profile(horse_name, today_distance, prep_run_num, base_score, fk=None, runs=None):
    """Career profile from real Form King data.

    fk   - the runner's real profile dict (formking_client._profile), or None
    runs - the runner's real past runs, newest first (up to 12), or None
    """
    fk = fk or {}
    runs = runs or []
    form = fk.get("form") or {}

    age, sex = fk.get("age"), fk.get("sex")
    bio = {
        "sire": fk.get("sire") or DASH,
        "dam": fk.get("dam") or DASH,
        "dam_sire": fk.get("dam_sire") or DASH,
        "age_sex": "{}yo {}".format(age, SEX_NAMES.get(sex, sex or "")).strip() if age else DASH,
        "code": "{}{}".format(age or "", sex or "") or DASH,
        "jockey": fk.get("jockey") or DASH,
        "trainer": fk.get("trainer") or DASH,
        "prizemoney": fk.get("prizemoney") or 0.0,
        # Form King gives 12-month strike rates; it has no ROI for connections.
        "jockey_l50": _pct(fk.get("jockey_12m_win_pct")),
        "trainer_l50": _pct(fk.get("trainer_12m_win_pct")),
        "jt_combo": _pct(fk.get("trainer_jockey_win_pct")),
        "jockey_roi": DASH, "trainer_roi": DASH, "jt_roi": DASH,
        "jockey_12m": fk.get("jockey_12m") or DASH,
        "trainer_12m": fk.get("trainer_12m") or DASH,
    }

    c_starts, c_wins, c_2, c_3 = _parse(form.get("career"))
    career = {
        "starts": c_starts, "wins": c_wins, "places": c_2 + c_3,
        "win_pct": round(c_wins / c_starts * 100, 1) if c_starts else 0.0,
        "place_pct": round((c_wins + c_2 + c_3) / c_starts * 100, 1) if c_starts else 0.0,
        "avg_score": _avg(r.get("rating") for r in runs),
    }

    # Going splits from the real runs on file (Form King's own going buckets use a
    # different naming scheme, so the bands are rebuilt from each run's going).
    condition = {}
    for band in ("Good", "Soft", "Heavy", "Synthetic"):
        rs = [r for r in runs if _going_band(r.get("going")) == band]
        w = sum(1 for r in rs if r.get("pos") == 1)
        s2 = sum(1 for r in rs if r.get("pos") == 2)
        s3 = sum(1 for r in rs if r.get("pos") == 3)
        condition[band] = {"starts": len(rs), "wins": w,
                           "avg_score": _avg(r.get("rating") for r in rs),
                           "rec": "{}: {}-{}-{}".format(len(rs), w, s2, s3)}

    d_starts, d_wins, d_2, d_3 = _parse(form.get("distance"))
    distance = {
        "distance": today_distance, "starts": d_starts, "wins": d_wins, "places": d_2 + d_3,
        "avg_score": _avg(r.get("rating") for r in runs
                          if r.get("dist") and abs(r["dist"] - today_distance) <= 100),
    }

    prof = profile_runner(horse_name, prep_run_num, base_score, runs)
    prep = {}
    for stage in range(1, 6):
        row = prof["stages"][stage]
        prep[STAGE_LABELS[stage]] = {"starts": row["starts"], "wins": row["wins"],
                                     "avg_score": row["avg_rating"]}

    # Key-race signal: winners produced since by the horse's last race (Form King
    # subsequentForm on that past run).
    hot_form_winners = (runs[0].get("next_wins") or 0) if runs else 0

    records = {
        "Car": _rec(form.get("career")),
        "Crs": _rec(form.get("track")),
        "Dist": _rec(form.get("distance")),
        "Crs&Dist": _rec(form.get("track_dist")),
        "FU": _rec(form.get("first_up")),
        "2U": _rec(form.get("second_up")),
        "3U": _rec(form.get("third_up")),
    }
    dlw = fk.get("days_since_win")
    facts = {
        "DLW": "{}d".format(dlw) if dlw else DASH,
        "DOD": DASH,
        "ROI %": DASH,
    }
    rec_avg = {"Car": career["avg_score"], "Dist": distance["avg_score"]}

    return {"bio": bio, "career": career, "condition": condition,
            "distance": distance, "prep": prep, "today_stage": prof["prep_stage"],
            "hot_form_winners": hot_form_winners, "records": records, "facts": facts,
            "rec_avg": rec_avg}


if __name__ == "__main__":
    p = generate_profile("Demo", 1200, 3, 60.0,
                         fk={"age": 4, "sex": "G", "form": {"career": "8:0-1-1"}},
                         runs=[{"going": "Soft 6", "pos": 2, "rating": 61.0, "dist": 1200, "prep": 2}])
    print(p["bio"]["age_sex"], p["records"]["Car"], p["condition"]["Soft"])
