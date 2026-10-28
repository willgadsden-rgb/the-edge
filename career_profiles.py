"""Synthetic career profiles for The Edge runner drawer (Phase 4).

Generates deterministic, mock career data per horse (pedigree, connections,
career record, and condition / distance / preparation splits) so the Tab 1
"DETAILS" drawer can read like a professional mobile form guide. Everything is
seeded from the horse name so it is stable across reruns. Mock data only
(see CLAUDE.md) - no outbound lookups.
"""

import hashlib
import random

from prep_engine import profile_runner, STAGE_LABELS
import silks_engine

SIRES = ["Snitzel", "Written Tycoon", "I Am Invincible", "Zoustar", "Fastnet Rock",
         "Exceed And Excel", "Not A Single Doubt", "Deep Field", "Capitalist", "Pierro"]
DAMS = ["Lady Lustre", "Velvet Dawn", "Starlet Reign", "Coral Bay", "Miss Promise",
        "Silken Sky", "Royal Cadence", "Winter Rose", "Golden Veil", "Harbour Mist"]
JOCKEYS = ["J. McDonald", "C. Williams", "D. Lane", "M. Zahra", "B. Melham",
           "J. Bowman", "W. Egan", "C. Newitt", "T. Nugent", "E. Brown"]
TRAINERS = ["C. Waller", "C. Maher", "J. Cummings", "A. Freedman", "P. Moody",
            "G. Waterhouse", "M. Price", "D. O'Brien", "T. Busuttin", "M. Ellerton"]
SEXES = [("Gelding", "G"), ("Mare", "M"), ("Colt", "C"), ("Filly", "F"), ("Entire", "H")]
CONDITIONS = ["Good", "Soft", "Heavy", "Synthetic"]


def _rng(horse_name):
    seed = int(hashlib.md5(("career:" + horse_name).encode("utf-8")).hexdigest(), 16) % (2 ** 32)
    return random.Random(seed)


def _split_counts(total, weights, rng):
    """Distribute `total` starts across buckets by weight (integers summing to total)."""
    counts = []
    acc = 0
    for i, w in enumerate(weights):
        if i == len(weights) - 1:
            counts.append(max(0, total - acc))
        else:
            c = int(round(total * w))
            counts.append(c)
            acc += c
    return counts


def generate_profile(horse_name, today_distance, prep_run_num, base_score):
    """Return a full synthetic career profile dict for one runner."""
    r = _rng(horse_name)

    age = r.randint(3, 8)
    sex_name, sex_code = r.choice(SEXES)
    win_rate = max(0.05, min(0.42, r.gauss(0.17, 0.06)))

    starts = r.randint(6, 42)
    wins = min(starts, int(round(starts * win_rate)))
    places = min(starts - wins, int(round(starts * r.uniform(0.18, 0.34))))

    bio = {
        "sire": r.choice(SIRES),
        "dam": r.choice(DAMS),
        "age_sex": "{}yo {}".format(age, sex_name),
        "code": "{}{}".format(age, sex_code),
        "jockey": silks_engine.jockey_for(horse_name),
        "trainer": r.choice(TRAINERS),
        "prizemoney": r.randint(18, 920) * 1000,
    }

    career = {
        "starts": starts, "wins": wins, "places": places,
        "win_pct": round(wins / starts * 100, 1) if starts else 0.0,
        "place_pct": round((wins + places) / starts * 100, 1) if starts else 0.0,
    }

    # Condition splits (Good most common -> Synthetic rare).
    cond_counts = _split_counts(starts, [0.5, 0.3, 0.14, 0.06], r)
    condition = {}
    for cond, cs in zip(CONDITIONS, cond_counts):
        cw = min(cs, int(round(cs * win_rate * r.uniform(0.5, 1.5))))
        avg = round(max(0.0, base_score + r.uniform(-6, 6)), 1) if cs else None
        condition[cond] = {"starts": cs, "wins": cw, "avg_score": avg}

    # Distance split at today's trip.
    d_starts = r.randint(0, min(starts, 9))
    d_wins = min(d_starts, int(round(d_starts * win_rate * r.uniform(0.5, 1.6))))
    d_places = min(max(0, d_starts - d_wins), int(round(d_starts * r.uniform(0.1, 0.4))))
    distance = {
        "distance": today_distance, "starts": d_starts, "wins": d_wins, "places": d_places,
        "avg_score": round(max(0.0, base_score + r.uniform(-5, 5)), 1) if d_starts else None,
    }

    # Preparation splits - reuse the prep engine's stage curve so the drawer's
    # per-stage average scores match the model's prep adjustments.
    prof = profile_runner(horse_name, prep_run_num, base_score)
    stage_scores = prof["stage_scores"]
    prep = {}
    for stage in range(1, 6):
        ps = r.randint(0, 6)
        pw = min(ps, int(round(ps * win_rate * r.uniform(0.4, 1.7))))
        prep[STAGE_LABELS[stage]] = {"starts": ps, "wins": pw, "avg_score": stage_scores[stage]}

    # "Hot form race": how many subsequent winners the horse's last race produced
    # (a strong-form-race signal). Mostly 0-2, occasionally more.
    hot_form_winners = r.choices([0, 1, 2, 3, 4], weights=[45, 25, 18, 8, 4])[0]

    # --- structured stat chips (classic AU form-guide grid) -----------------
    bio["dam_sire"] = r.choice([s for s in SIRES if s != bio["sire"]])
    bio["jockey_l50"] = "{}%".format(r.randint(9, 26))
    bio["jockey_l350"] = "{}%".format(r.randint(10, 22))
    bio["jt_combo"] = "{}%".format(r.randint(6, 24))
    # Strike rate + ROI per connection (mock, deterministic) for the DETAILS drawer.
    bio["trainer_l50"] = "{}%".format(r.randint(8, 24))
    bio["jockey_roi"] = "{:+.0f}%".format(r.uniform(-25, 42))
    bio["trainer_roi"] = "{:+.0f}%".format(r.uniform(-22, 40))
    bio["jt_roi"] = "{:+.0f}%".format(r.uniform(-30, 55))

    def rec(strike, max_starts=starts):
        s = r.randint(0, max(0, max_starts))
        w = min(s, int(round(s * max(0.0, strike))))
        p2 = min(s - w, int(round(s * r.uniform(0.08, 0.18))))
        p3 = min(s - w - p2, int(round(s * r.uniform(0.07, 0.15))))
        return "{}: {}-{}-{}".format(s, w, p2, p3)

    records = {
        "Car": "{}: {}-{}-{}".format(starts, wins, places, max(0, int(round(starts * 0.12)))),
        "12m": rec(win_rate, min(starts, 14)),
        "Crs": rec(win_rate * r.uniform(0.6, 1.3), min(starts, 9)),
        "Dist": "{}: {}-{}-{}".format(distance["starts"], distance["wins"], distance["places"],
                                      max(0, distance["starts"] - distance["wins"] - distance["places"])),
        "Crs&Dist": rec(win_rate * r.uniform(0.5, 1.2), min(starts, 5)),
        "Good": "{}: {}-{}-{}".format(condition["Good"]["starts"], condition["Good"]["wins"],
                                      max(0, int(condition["Good"]["starts"] * 0.12)),
                                      max(0, int(condition["Good"]["starts"] * 0.1))),
        "Soft": "{}: {}-{}-{}".format(condition["Soft"]["starts"], condition["Soft"]["wins"], 0, 0),
        "Heavy": "{}: {}-{}-{}".format(condition["Heavy"]["starts"], condition["Heavy"]["wins"], 0, 0),
        "AW": rec(win_rate * 0.6, min(starts, 4)),
        "Turf": rec(win_rate, starts),
        "G1": rec(0.03, min(starts, 4)), "G2": rec(0.05, min(starts, 5)),
        "G3": rec(0.08, min(starts, 6)), "LR": rec(0.1, min(starts, 7)),
        "FU": "{}: {}-{}-{}".format(prep["1st-up"]["starts"], prep["1st-up"]["wins"], 0, 0),
        "2U": "{}: {}-{}-{}".format(prep["2nd-up"]["starts"], prep["2nd-up"]["wins"], 0, 0),
        "3U": "{}: {}-{}-{}".format(prep["3rd-up"]["starts"], prep["3rd-up"]["wins"], 0, 0),
    }
    facts = {
        "DLW": "{}d".format(r.randint(14, 520)),
        "DOD": r.choice(["Metro", "Provincial", "Country", "Metro"]),
        "ROI %": "{:+.0f}%".format(r.uniform(-28, 42)),
    }

    # Average rating the horse earns per record bucket, and full W-2-3 surface records.
    career["avg_score"] = round(max(0.0, base_score + r.uniform(-4, 4)), 1)
    for cond, cd in condition.items():
        s, w = cd["starts"], cd["wins"]
        p2 = min(max(0, s - w), int(round(s * 0.14)))
        p3 = min(max(0, s - w - p2), int(round(s * 0.11)))
        cd["rec"] = "{}: {}-{}-{}".format(s, w, p2, p3)
    rec_avg = {
        "Car": career["avg_score"],
        "Crs": round(max(0.0, base_score + r.uniform(-5, 5)), 1),
        "Crs&Dist": round(max(0.0, base_score + r.uniform(-6, 6)), 1),
        "Dist": distance["avg_score"],
    }

    return {"bio": bio, "career": career, "condition": condition,
            "distance": distance, "prep": prep, "today_stage": prof["prep_stage"],
            "hot_form_winners": hot_form_winners, "records": records, "facts": facts,
            "rec_avg": rec_avg}


if __name__ == "__main__":
    p = generate_profile("Desert Mirage", 1200, 3, 42.0)
    print(p["bio"])
    print(p["career"])
    print(p["condition"]["Good"], p["distance"], p["prep"]["3rd-up"])
