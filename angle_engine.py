"""Situational Angle Engine for The Edge (Phase 5).

Scans runner history and current race conditions to produce dynamic +/- point
modifiers ("angles") that feed the projected score. Runner history is synthesised
deterministically per horse (mock data only, see CLAUDE.md). Each public check is
a pure predicate so the angles can be unit-tested with explicit inputs; the
`calculate_angles` entry point assembles them from a seeded synthetic history.

Each active angle is returned as:  {"name": str, "points": float, "type": "bonus"|"penalty"}
"""

import hashlib
import random

# Point values per angle.
PTS_DISTANCE_CONDITIONER = 2.0
PTS_HEAVY_HANGOVER = -1.5
PTS_LIGHTWEIGHT_MUDLARK = 2.0
PTS_FEATHERWEIGHT = 1.5
PTS_WEIGHT_STOPPER = -1.5
PTS_SPEED_MAP_BIAS = 1.5

TRACK_BIAS_FAIR = "Fair"
TRACK_BIAS_LEADER = "Leader Bias"
TRACK_BIAS_SWOOPER = "Swooper Bias"


def _seed(horse_name):
    return int(hashlib.md5(("angle:" + horse_name).encode("utf-8")).hexdigest(), 16) % (2 ** 32)


def _early_speed(name):
    h = int(hashlib.md5(("es:" + name).encode("utf-8")).hexdigest(), 16)
    return 30.0 + (h % 651) / 10.0


def settling_positions(entries):
    """Map horse_name -> early settling position (1 = fastest/leader)."""
    order = sorted((e for e in entries if not e.get("scratched")),
                   key=lambda e: -_early_speed(e["horse_name"]))
    return {e["horse_name"]: i for i, e in enumerate(order, start=1)}


def synth_history(horse_name, today_distance):
    """Deterministic mock recent-history snapshot used by the history-based angles."""
    r = random.Random(_seed(horse_name))
    last_distance = max(800, today_distance + r.choice([-400, -200, -100, 0, 100, 200]))
    two_back_distance = max(800, last_distance + r.choice([-400, -200, 0, 200]))
    last_condition = r.choice(["Good", "Good", "Soft", "Heavy", "Good"])
    return {
        "last_distance": last_distance,
        "two_back_distance": two_back_distance,
        "rose_two_back_m": last_distance - two_back_distance,
        "days_since": r.choice([6, 8, 10, 13, 16, 20, 28, 35, 45]),
        "last_condition": last_condition,
        "last_severity": r.choice([8, 9, 10]) if last_condition == "Heavy" else 0,
        "runs_since_heavy": 0 if r.random() < 0.6 else 1,   # 0 = this is the first run back
        "is_second_at_trip": r.random() < 0.45,
        "late_sectional_above_avg": r.random() < 0.5,
        "elite_late_sectional": r.random() < 0.35,
        "weight_drop": round(r.choice([0, 0, 0.5, 1.0, 2.0, 3.0, 4.0]), 1),
    }


# -- pure angle predicates ----------------------------------------------------
def check_distance_conditioner(today_distance, is_second_at_trip, rose_two_back_m):
    """2nd start at 2000m+ after a >=400m rise two starts back -> +2.0 (peak trip fitness)."""
    if today_distance >= 2000 and is_second_at_trip and rose_two_back_m >= 400:
        return {"name": "Distance Conditioner", "points": PTS_DISTANCE_CONDITIONER, "type": "bonus"}
    return None


def check_heavy_hangover(today_condition, last_condition, days_since,
                         last_severity=10, runs_since_heavy=0):
    """Heavy-track hangover with a strict 1-run lifecycle.

    Fires only on the immediate first run after a Heavy 8-10 track, within 21 days,
    on a Good track today. Once that run is completed (runs_since_heavy > 0) the
    angle is permanently retired for the campaign and returns None.
    """
    if (today_condition == "Good" and last_condition == "Heavy"
            and 8 <= last_severity <= 10 and days_since < 21 and runs_since_heavy == 0):
        return {"name": "Heavy Hangover", "points": PTS_HEAVY_HANGOVER, "type": "penalty"}
    return None


def check_lightweight_mudlark(weight, today_condition, late_sectional_above_avg):
    """<=54.5kg on a Soft/Heavy deck with above-average late sectional -> +2.0."""
    if weight <= 54.5 and today_condition in ("Soft", "Heavy") and late_sectional_above_avg:
        return {"name": "Lightweight Mudlark", "points": PTS_LIGHTWEIGHT_MUDLARK, "type": "bonus"}
    return None


def check_featherweight_turn_of_foot(weight, weight_drop, elite_late_sectional):
    """<=54.0kg (or a >=3.0kg weight drop) with an elite late sectional, any surface -> +1.5."""
    if (weight <= 54.0 or weight_drop >= 3.0) and elite_late_sectional:
        return {"name": "Featherweight Turn of Foot", "points": PTS_FEATHERWEIGHT, "type": "bonus"}
    return None


def check_weight_stopper(weight, stepping_up):
    """>=60.0kg while stepping up in class or distance -> -1.5."""
    if weight >= 60.0 and stepping_up:
        return {"name": "Weight Stopper", "points": PTS_WEIGHT_STOPPER, "type": "penalty"}
    return None


def check_speed_map_bias(settling_position, track_bias):
    """Adjust by settling position under the selected track bias."""
    if track_bias == TRACK_BIAS_LEADER:
        if settling_position <= 2:
            return {"name": "Leader-Bias Suited", "points": PTS_SPEED_MAP_BIAS, "type": "bonus"}
        if settling_position >= 6:
            return {"name": "Leader-Bias Against", "points": -PTS_SPEED_MAP_BIAS, "type": "penalty"}
    elif track_bias == TRACK_BIAS_SWOOPER:
        if settling_position <= 2:
            return {"name": "Swooper-Bias Against", "points": -PTS_SPEED_MAP_BIAS, "type": "penalty"}
        if settling_position >= 6:
            return {"name": "Swooper-Bias Suited", "points": PTS_SPEED_MAP_BIAS, "type": "bonus"}
    return None


def calculate_angles(entry, race, meeting, settling_position, track_bias):
    """Assemble all active angles for one runner from its synthetic history."""
    today_distance = race["distance"]
    today_condition = (meeting["condition"] or "Good").split()[0]
    weight = entry["weight"]
    hist = synth_history(entry["horse_name"], today_distance)
    stepping_up = today_distance > hist["last_distance"]

    candidates = [
        check_distance_conditioner(today_distance, hist["is_second_at_trip"], hist["rose_two_back_m"]),
        check_heavy_hangover(today_condition, hist["last_condition"], hist["days_since"],
                             hist["last_severity"], hist["runs_since_heavy"]),
        check_lightweight_mudlark(weight, today_condition, hist["late_sectional_above_avg"]),
        check_featherweight_turn_of_foot(weight, hist["weight_drop"], hist["elite_late_sectional"]),
        check_weight_stopper(weight, stepping_up),
        check_speed_map_bias(settling_position, track_bias),
    ]
    return [a for a in candidates if a]


def angle_points(angles):
    return round(sum(a["points"] for a in angles), 2)


if __name__ == "__main__":
    print(check_weight_stopper(60.5, True))
    print(check_heavy_hangover("Good", "Heavy", 14))
    print(check_speed_map_bias(1, TRACK_BIAS_LEADER))
    print(check_speed_map_bias(7, TRACK_BIAS_SWOOPER))
