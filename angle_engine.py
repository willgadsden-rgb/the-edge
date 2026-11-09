"""Situational Angle Engine for The Edge (Phase 5).

Scans runner history and current race conditions to produce dynamic +/- point
modifiers ("angles") that feed the projected score. Runner history comes from the
real Form King runs stored on each entry (runs_json / last5_json / fk_json). Each
public check is a pure predicate so the angles can be unit-tested with explicit
inputs; `calculate_angles` assembles them from the runner's real history.

Each active angle is returned as:  {"name": str, "points": float, "type": "bonus"|"penalty"}
"""

import json

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


def _json_list(raw):
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw or "[]")
    except Exception:
        return []


def _get(entry, key):
    """Read a key from a dict or a sqlite3.Row that may predate a migration."""
    try:
        return entry[key]
    except (KeyError, IndexError, TypeError):
        return None


def _runs_of(entry):
    """All real past runs on file for an entry (newest first)."""
    runs = _json_list(_get(entry, "runs_json"))
    return runs or _json_list(_get(entry, "last5_json"))


def early_speed_of(entry):
    """Real early-speed figure (0-10) from in-run settling positions, or None."""
    from speedmap_engine import early_speed_from_runs  # local: avoids an import cycle
    return early_speed_from_runs(_json_list(_get(entry, "last5_json")) or _runs_of(entry))


def settling_positions(entries):
    """Map horse_name -> expected settling position (1 = leader) from REAL in-run
    history. Runners with no in-run data (debutants) sit at a neutral 5.0 on the
    0-10 scale rather than a made-up figure."""
    active = [e for e in entries if not _get(e, "scratched")]
    speed = {e["horse_name"]: early_speed_of(e) for e in active}
    order = sorted(active, key=lambda e: -(speed[e["horse_name"]] if speed[e["horse_name"]] is not None else 5.0))
    return {e["horse_name"]: i for i, e in enumerate(order, start=1)}


def _going_parts(going):
    """'Heavy 8' -> ('Heavy', 8); 'Good' -> ('Good', None)."""
    parts = (going or "").split()
    word = parts[0].capitalize() if parts else None
    num = None
    if len(parts) > 1:
        try:
            num = int(parts[1])
        except ValueError:
            num = None
    return word, num


def real_history(entry, today_distance):
    """Recent-history snapshot for the angles, built from the runner's REAL runs.

    Form King has no sectional times on race runs, so the late-sectional flags
    are always False and the angles that need them do not fire.
    """
    runs = _runs_of(entry)
    try:
        fk = json.loads(_get(entry, "fk_json") or "{}")
    except Exception:
        fk = {}
    last = runs[0] if runs else {}
    two_back = runs[1] if len(runs) > 1 else {}
    last_distance = last.get("dist") or today_distance
    two_back_distance = two_back.get("dist") or last_distance
    last_condition, last_severity = _going_parts(last.get("going"))

    # Runs earlier in THIS prep: newest-first runs whose prep number counts down.
    today_prep = _get(entry, "prep_run_num") or 1
    this_prep = []
    for i, r in enumerate(runs):
        if r.get("prep") == today_prep - 1 - i and r.get("prep", 0) >= 1:
            this_prep.append(r)
        else:
            break
    at_trip = sum(1 for r in this_prep if r.get("dist") and abs(r["dist"] - today_distance) <= 100)

    days_since = fk.get("days_since_run")
    weight = _get(entry, "weight")
    weight_drop = (last.get("wt") - float(weight)) if (last.get("wt") and weight) else 0.0

    return {
        "last_distance": last_distance,
        "two_back_distance": two_back_distance,
        "rose_two_back_m": last_distance - two_back_distance,
        "days_since": days_since if days_since is not None else 999,
        "last_condition": last_condition,
        "last_severity": last_severity or 0,
        "runs_since_heavy": 0,          # last_condition is the immediately previous run
        "is_second_at_trip": at_trip == 1,
        "late_sectional_above_avg": False,   # no race sectionals in the Form King feed
        "elite_late_sectional": False,
        "weight_drop": round(weight_drop, 1),
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
    """Assemble all active angles for one runner from its real history."""
    today_distance = race["distance"]
    today_condition = (meeting["condition"] or "Good").split()[0]
    weight = entry["weight"]
    hist = real_history(entry, today_distance)
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
