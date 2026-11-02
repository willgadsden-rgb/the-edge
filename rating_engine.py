"""Rating engine for the Punting Intelligence Engine (PIE) - Phase 2.

Turns a runner's raw inputs into an absolute 0-100 ability score and a
synthetic recent-form trajectory. Mock data only (see CLAUDE.md).

Calibration anchors (CLAUDE.md "Math & Pricing Rules"):
    Provincial Benchmark 64        -> ~50.0
    Metro Saturday BM78 / Open     -> ~70.0
    Stakes / Group company         -> 85.0 - 100.0
"""

import hashlib
import random

# Standard class weight used as the zero point for the weight penalty/bonus.
CLASS_STANDARD_WEIGHT = 57.0

# Sensitivities (points of 0-100 score per unit of input).
WFA_SENSITIVITY = 0.6       # per rating point above/below the class par
WEIGHT_SENSITIVITY = 1.5    # per kg carried below the 57.0kg standard

# Per-class calibration: (center score, par wfa_rating for that class).
# The center fixes where a "par" horse in the class sits on the 0-100 scale;
# par_wfa is the wfa_rating such a par horse is expected to carry, so a runner
# rated above/below par is nudged up/down from the center.
CLASS_PROFILES = [
    # (keyword matched in class_name.lower(), center, par_wfa)
    ("group 1", 95.0, 92.0),
    ("group 2", 90.0, 88.0),
    ("group 3", 85.0, 85.0),
    ("listed", 80.0, 80.0),
    ("stakes", 82.0, 82.0),
    ("open", 70.0, 72.0),
    ("benchmark 84", 72.0, 74.0),
    ("benchmark 78", 70.0, 72.0),
    ("saturday", 70.0, 72.0),
    ("benchmark 64", 50.0, 55.0),
    ("benchmark", 52.0, 56.0),   # generic/other benchmarks
    ("maiden", 42.0, 42.0),
]
DEFAULT_PROFILE = (50.0, 55.0)


def _class_profile(class_name):
    """Return (center, par_wfa) for the first keyword that matches class_name."""
    name = (class_name or "").lower()
    for keyword, center, par_wfa in CLASS_PROFILES:
        if keyword in name:
            return center, par_wfa
    return DEFAULT_PROFILE


def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def calculate_0_to_100_score(wfa_rating, weight, distance, class_name):
    """Normalise a runner's inputs to an absolute 0-100 ability score.

    distance is accepted for suitability modelling; in Phase 2 it is neutral
    (no synthetic distance form exists yet) and documented as a reserved input.
    """
    center, par_wfa = _class_profile(class_name)

    # How much better/worse than a par horse of this class, by raw rating.
    # An unrated runner (e.g. a live first-starter with no benchmark) is scored
    # at class par rather than crashing on float(None).
    wr = float(wfa_rating) if wfa_rating is not None else par_wfa
    wfa_component = (wr - par_wfa) * WFA_SENSITIVITY

    # Carrying less than the 57.0kg class standard is a bonus; more is a penalty.
    weight_component = (CLASS_STANDARD_WEIGHT - float(weight)) * WEIGHT_SENSITIVITY

    # Reserved for future distance-suitability form; neutral in Phase 2.
    distance_component = 0.0

    score = center + wfa_component + weight_component + distance_component
    return round(_clamp(score), 1)


def _seed_from_name(horse_name):
    """Stable per-horse seed so trajectories are reproducible across runs."""
    digest = hashlib.md5(horse_name.encode("utf-8")).hexdigest()
    return int(digest, 16) % (2 ** 32)


def generate_trajectory(horse_name, current_score, n=None):
    """Return a synthetic list of the horse's last 3-5 scores (oldest -> newest).

    The newest value sits near current_score and the series carries a mild,
    horse-specific trend plus run-to-run noise, all clamped to 0-100. Pass n to
    force an exact number of past runs (e.g. n=5 for the form-guide cards);
    leaving it None keeps the original random 3-5 behaviour.
    """
    rng = random.Random(_seed_from_name(horse_name))
    n_runs = n if n is not None else rng.randint(3, 5)
    trend_per_run = rng.uniform(-3.0, 3.0)

    trajectory = []
    for i in range(n_runs):
        # i counts from oldest (0) to newest (n_runs-1); newest ~ current_score.
        steps_back = (n_runs - 1) - i
        noise = rng.uniform(-2.0, 2.0)
        value = current_score - trend_per_run * steps_back + noise
        trajectory.append(round(_clamp(value), 1))
    return trajectory


def trajectory_trend(trajectory):
    """Least-squares slope of a trajectory, in points per run (rounded 1 dp)."""
    n = len(trajectory)
    if n < 2:
        return 0.0

    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(trajectory) / n
    numerator = sum((xs[i] - mean_x) * (trajectory[i] - mean_y) for i in range(n))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 1)


def classify_trajectory(form_newest_first):
    """Noise-banded form-trajectory classification.

    Input is the form array in display order L1..L5 (newest -> oldest). Returns
    {label, per_run, cls} where label is RISING / EASING / STABLE. Chronological
    progression is measured oldest->newest (x = -4..0, newest = 0). Only a genuine
    breakout (> +2.0 above the median baseline) reads RISING, and only a genuine
    collapse (> -2.0 below baseline) reads EASING; otherwise it is STABLE. A metro-
    class horse (all runs > 70) is never flagged EASING unless its last run plummeted.
    """
    import statistics
    form = list(form_newest_first)
    if len(form) < 2:
        return {"label": "STABLE", "per_run": 0.0, "cls": "flat"}

    recent = form[0]
    chrono = list(reversed(form))                 # oldest -> newest
    trend = trajectory_trend(chrono)              # +ve = improving per run
    median = statistics.median(form)
    dev = recent - median
    all_metro = all(v > 70 for v in form)
    plummeted = recent < median - 3.0

    if dev > 2.0 and trend > 0:
        return {"label": "RISING", "per_run": abs(trend), "cls": "up"}
    if dev < -2.0 and trend < 0:
        if all_metro and not plummeted:
            return {"label": "STABLE", "per_run": 0.0, "cls": "flat"}
        return {"label": "EASING", "per_run": abs(trend), "cls": "dn"}
    return {"label": "STABLE", "per_run": 0.0, "cls": "flat"}


def condition_affinity(horse_name, condition):
    """Deterministic per-horse affinity for a track condition, in [-4.0, +4.0]."""
    digest = hashlib.md5("{}:{}".format(horse_name, condition).encode("utf-8")).hexdigest()
    return round((int(digest, 16) % 81) / 10.0 - 4.0, 1)


def distance_affinity(horse_name, distance):
    """Deterministic per-horse affinity for today's distance, in [-3.0, +3.0]."""
    if not distance:
        return 0.0
    digest = hashlib.md5("{}:{}".format(horse_name, distance).encode("utf-8")).hexdigest()
    return round((int(digest, 16) % 61) / 10.0 - 3.0, 1)


# Syndicate guardrail: no combination of situational modifiers may move a horse by
# more than +/- 2.5 rating points (~1.7 lengths) from its established ability.
MODIFIER_CAP = 2.5


def clamp_modifier(points):
    """Hard-clamp the consolidated situational modifier to [-2.5, +2.5]."""
    return max(-MODIFIER_CAP, min(MODIFIER_CAP, float(points)))


def calculate_projected_score(horse_name, base_score, prep_run_num, condition,
                              distance=None, situational_points=0.0,
                              manual_override_points=0.0, unclamped_points=0.0):
    """Project today's 0-100 score with a hard cap on situational modifiers:

        Projected = Base Rating + clamped_modifier + user_points + manual_override

    - Base Rating: established ability = recent-form-adjusted class rating + prep,
      condition and distance suitability (intrinsic, never clamped);
    - clamped_modifier: the consolidated situational points (angles, pace tempo,
      wind vectors, track bias, intraday TSV drift) clamped to [-2.5, +2.5];
    - user_points: deliberate custom-rule biases (user intent, not clamped);
    - manual_override: analyst / AI co-pilot manual adjustment.
    """
    from prep_engine import profile_runner  # local import avoids an import cycle

    traj = generate_trajectory(horse_name, base_score, n=5)
    trend = trajectory_trend(traj)
    next_form = _clamp(traj[-1] + trend)
    recent = sum(traj[-3:]) / len(traj[-3:])
    form_blend = 0.5 * next_form + 0.5 * recent

    base_rating = (0.7 * form_blend + 0.3 * base_score
                   + profile_runner(horse_name, prep_run_num, base_score)["prep_adjustment"]
                   + condition_affinity(horse_name, condition)
                   + distance_affinity(horse_name, distance))

    clamped = clamp_modifier(situational_points)
    projected = (base_rating + clamped + float(unclamped_points)
                 + float(manual_override_points))
    return round(_clamp(projected), 1)


if __name__ == "__main__":
    demo = calculate_0_to_100_score(wfa_rating=74.0, weight=56.0,
                                    distance=1600, class_name="Open Benchmark 84")
    traj = generate_trajectory("Demo Horse", demo)
    print(f"score={demo}  trajectory={traj}  trend={trajectory_trend(traj)}/run")
