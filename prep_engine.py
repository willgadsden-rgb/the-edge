"""Campaign / preparation profiler (v2: real data only).

Builds a runner's record at each stage of a preparation (1st-up, 2nd-up, ...)
from its ACTUAL past runs. Form King supplies `raceInPrep` on every past run,
so each run is placed in its stage directly - no spell guessing and nothing
seeded from the horse's name.

The prep adjustment to today's rating is 0.0 until it is fitted against
results (see the v2 blueprint): the profile is shown to the analyst as
evidence, not silently added to the score.

Stages map from prep run number:
    1 -> 1st-up, 2 -> 2nd-up, 3 -> 3rd-up, 4 -> 4th-up, 5+ -> 5th+ up
"""

STAGE_LABELS = {1: "1st-up", 2: "2nd-up", 3: "3rd-up", 4: "4th-up", 5: "5th+ up"}

# A stage is the horse's "best stage" only with at least this many runs there
# and an average rating at least this far above the horse's overall average.
MIN_STAGE_RUNS = 2
BEST_STAGE_MARGIN = 1.0


def _stage(prep_run_num):
    """Collapse a prep run number into a 1-5 stage key (5 = 5th-up or later)."""
    try:
        return min(max(int(prep_run_num), 1), 5)
    except (TypeError, ValueError):
        return 1


def stage_table(runs):
    """Per-stage record from real runs: {stage: {starts, wins, places, avg_rating}}.

    `runs` are dicts with "prep", "pos" and "rating" (Form King's per-run WFA
    rating). Runs without a prep number are skipped.
    """
    table = {s: {"starts": 0, "wins": 0, "places": 0, "ratings": []} for s in range(1, 6)}
    for r in runs or []:
        if not r.get("prep"):
            continue
        row = table[_stage(r["prep"])]
        row["starts"] += 1
        pos = r.get("pos")
        if pos == 1:
            row["wins"] += 1
        if isinstance(pos, int) and pos <= 3:
            row["places"] += 1
        if isinstance(r.get("rating"), (int, float)):
            row["ratings"].append(float(r["rating"]))
    for row in table.values():
        rs = row.pop("ratings")
        row["avg_rating"] = round(sum(rs) / len(rs), 1) if rs else None
    return table


def profile_runner(horse_name, prep_run_num, base_score, runs=None):
    """Profile one runner's campaign from its real runs.

    Returns:
        prep_stage      - today's stage label, e.g. "3rd-up"
        is_peak_target  - True when today's stage is the horse's proven best stage
        prep_adjustment - 0.0 (shown as evidence; not added until fitted)
        tag             - display tag, e.g. "[BEST STAGE 3RD-UP]" or ""
        profile         - row for horse_prep_profiles (today's stage, real counts)
        stage_scores    - {stage: average real rating or None}
        stages          - full per-stage table (starts, wins, places, avg_rating)
    """
    today = _stage(prep_run_num)
    table = stage_table(runs)

    rated = [float(r["rating"]) for r in (runs or []) if isinstance(r.get("rating"), (int, float))]
    overall = sum(rated) / len(rated) if rated else None

    best_stage = None
    if overall is not None:
        candidates = [(s, row["avg_rating"]) for s, row in table.items()
                      if row["starts"] >= MIN_STAGE_RUNS and row["avg_rating"] is not None]
        if candidates:
            s, avg = max(candidates, key=lambda c: c[1])
            if avg - overall >= BEST_STAGE_MARGIN:
                best_stage = s

    is_peak_target = best_stage is not None and best_stage == today
    tag = "[BEST STAGE {}]".format(STAGE_LABELS[today].upper()) if is_peak_target else ""

    row = table[today]
    return {
        "prep_stage": STAGE_LABELS[today],
        "is_peak_target": is_peak_target,
        "prep_adjustment": 0.0,
        "tag": tag,
        "profile": {
            "horse_name": horse_name,
            "prep_stage": STAGE_LABELS[today],
            "starts": row["starts"],
            "wins": row["wins"],
            "avg_score": row["avg_rating"],
        },
        "stage_scores": {s: r["avg_rating"] for s, r in table.items()},
        "stages": table,
    }


if __name__ == "__main__":
    demo = [{"prep": 1, "pos": 5, "rating": 60.0}, {"prep": 2, "pos": 2, "rating": 64.0},
            {"prep": 3, "pos": 1, "rating": 68.0}, {"prep": 1, "pos": 4, "rating": 61.0},
            {"prep": 2, "pos": 3, "rating": 63.0}, {"prep": 3, "pos": 1, "rating": 69.0}]
    print(profile_runner("Demo Horse", 3, 65.0, demo))
