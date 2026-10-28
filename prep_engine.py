"""Campaign / preparation profiler for PIE - Phase 2.

Evaluates where a runner is in its campaign (prep_run_num), builds a synthetic
per-stage form curve, detects "target peak" runs, and returns a prep adjustment
factor to apply to today's rating. Mock data only (see CLAUDE.md).

Stages map from prep_run_num:
    1 -> 1st-up, 2 -> 2nd-up, 3 -> 3rd-up, 4 -> 4th-up, 5+ -> 5th+ up
"""

import hashlib
import random

STAGE_LABELS = {1: "1st-up", 2: "2nd-up", 3: "3rd-up", 4: "4th-up", 5: "5th+ up"}

# A run is a "target peak" only if it is the horse's best stage AND that stage
# sits at least this many points above the horse's early-prep (1st/2nd-up) form.
PEAK_THRESHOLD = 2.5

# Clamp on how much the prep adjustment can swing today's rating, in points.
PREP_ADJ_LIMIT = 6.0


def _stage(prep_run_num):
    """Collapse prep_run_num into a 1-5 stage key (5 means 5th-up or later)."""
    return min(max(int(prep_run_num), 1), 5)


def _seed_from_name(horse_name):
    """Stable per-horse seed so prep curves are reproducible across runs."""
    digest = hashlib.md5(("prep:" + horse_name).encode("utf-8")).hexdigest()
    return int(digest, 16) % (2 ** 32)


def _build_curve(horse_name):
    """Return per-stage point offsets (relative to the horse's par) for 1..5.

    The curve peaks at a horse-specific stage and decays on either side, which
    mimics a horse that needs a run or two to hit its best then tapers.
    """
    rng = random.Random(_seed_from_name(horse_name))
    peak_stage = rng.choices([1, 2, 3, 4, 5], weights=[1, 3, 4, 3, 2])[0]
    peak_value = rng.uniform(3.0, 6.0)
    decay = rng.uniform(1.5, 3.0)

    offsets = {}
    for stage in range(1, 6):
        offsets[stage] = round(peak_value - decay * abs(stage - peak_stage), 2)
    return peak_stage, offsets


def _stage_history(rng, stage, peak_stage):
    """Synthesise realistic (starts, wins) for a horse at a given stage.

    Strike rate is higher at/near the peak stage than in early conditioning runs.
    """
    starts = rng.randint(1, 6)
    distance_from_peak = abs(stage - peak_stage)
    base_strike = max(0.05, 0.32 - 0.07 * distance_from_peak)
    wins = sum(1 for _ in range(starts) if rng.random() < base_strike)
    return starts, wins


def profile_runner(horse_name, prep_run_num, base_score):
    """Profile one runner's campaign and return its prep assessment.

    Returns a dict:
        prep_stage      - label, e.g. "3rd-up"
        is_peak_target  - True if today is a significant target-peak run
        prep_adjustment - points to add to today's rating (clamped)
        tag             - display tag: PEAK TARGET / CONDITIONING / TAPERING
        profile         - row for horse_prep_profiles (today's stage)
        stage_scores    - synthetic avg_score at each stage (for inspection)
    """
    today = _stage(prep_run_num)
    peak_stage, offsets = _build_curve(horse_name)
    rng = random.Random(_seed_from_name(horse_name) + 7)

    # Historical average score at each stage = par (base_score) + that offset.
    stage_scores = {s: round(max(0.0, base_score + offsets[s]), 1) for s in range(1, 6)}

    # Is today a genuine target peak? Best stage, meaningfully above early prep.
    early_avg = (offsets[1] + offsets[2]) / 2.0
    is_peak_target = (
        today == peak_stage
        and today >= 3
        and (offsets[today] - early_avg) >= PEAK_THRESHOLD
    )

    prep_adjustment = max(-PREP_ADJ_LIMIT, min(PREP_ADJ_LIMIT, offsets[today]))

    if is_peak_target:
        tag = "[PEAK TARGET {}]".format(STAGE_LABELS[today].upper())
    elif today < peak_stage:
        tag = "[CONDITIONING]"
    else:  # today > peak_stage (or an unremarkable peak)
        tag = "[TAPERING]" if today > peak_stage else "[CONDITIONING]"

    starts, wins = _stage_history(rng, today, peak_stage)
    profile = {
        "horse_name": horse_name,
        "prep_stage": STAGE_LABELS[today],
        "starts": starts,
        "wins": wins,
        "avg_score": stage_scores[today],
    }

    return {
        "prep_stage": STAGE_LABELS[today],
        "is_peak_target": is_peak_target,
        "prep_adjustment": round(prep_adjustment, 2),
        "tag": tag,
        "profile": profile,
        "stage_scores": stage_scores,
    }


if __name__ == "__main__":
    result = profile_runner("Demo Horse", prep_run_num=3, base_score=70.0)
    print(result["tag"], "adj", result["prep_adjustment"],
          "stages", result["stage_scores"])
