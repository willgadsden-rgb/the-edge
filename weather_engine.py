"""Environmental physics & BOM wind vectors for The Edge (Phase 7).

Models how wind down the home straight helps or hurts different running styles.
Track compass bearings give the direction horses run in the straight; a BOM wind
vector (speed + direction it blows FROM) is resolved onto that axis. Mock data
only (see CLAUDE.md) - wind is simulated deterministically per meeting unless
supplied.
"""

import hashlib
import math

# Direction (degrees) the horses run TOWARD down the home/straight.
TRACK_BEARINGS = {
    "Flemington": 220,       # straight six runs to the SW
    "Moonee Valley": 180,    # home straight to the S
    "Caulfield": 70,
    "Randwick": 100,
    "Rosehill": 300,
    "Flemington Straight": 220,
}
DEFAULT_BEARING = 200

HEADWIND_MIN = 15.0          # km/h parallel component to trigger an effect
TAILWIND_MIN = 15.0

DRAG_TAX = -2.0              # solitary leader into a headwind
SLIPSTREAM_BONUS = 1.5      # mid-pack stalker with cover into a headwind
TAILWIND_BONUS = 1.5        # on-pace runner with a tailwind

_DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def bearing_for(track_name):
    return TRACK_BEARINGS.get(track_name, DEFAULT_BEARING)


def compass_point(deg):
    return _DIRS[int((deg % 360) / 45.0 + 0.5) % 8]


def simulate_wind(track_name, meeting_date=""):
    """Deterministic mock BOM reading: {speed_kmh, from_deg} for a meeting."""
    h = int(hashlib.md5(("wind:" + track_name + str(meeting_date)).encode("utf-8")).hexdigest(), 16)
    speed = 6 + (h % 26)                 # 6-31 km/h
    from_deg = (h // 100) % 360
    return {"speed_kmh": float(speed), "from_deg": float(from_deg)}


def parallel_component(wind, track_name):
    """V_parallel = V_wind * cos(wind_from_deg - track_bearing).

    Positive = headwind (wind comes from where the horses are heading);
    negative = tailwind.
    """
    bearing = bearing_for(track_name)
    return round(wind["speed_kmh"] * math.cos(math.radians(wind["from_deg"] - bearing)), 2)


def classify_wind(wind, track_name):
    """Return a summary dict describing the wind's effect on the straight."""
    vpar = parallel_component(wind, track_name)
    if vpar >= HEADWIND_MIN:
        kind, label = "headwind", "Headwind {:.0f} km/h".format(abs(vpar))
    elif vpar <= -TAILWIND_MIN:
        kind, label = "tailwind", "Tailwind {:.0f} km/h".format(abs(vpar))
    else:
        kind, label = "crosswind", "Light/Cross {:.0f} km/h".format(wind["speed_kmh"])
    return {"speed_kmh": wind["speed_kmh"], "from_deg": wind["from_deg"],
            "from_point": compass_point(wind["from_deg"]), "v_parallel": vpar,
            "kind": kind, "label": label, "bearing": bearing_for(track_name)}


def wind_modifier(summary, runner):
    """Return (points, badge-or-None) for a runner given the wind summary.

    runner carries: settle_zone, tactical_tag, lane.
    """
    kind = summary["kind"]
    zone = (runner.get("settle_zone") or "")
    tag = (runner.get("tactical_tag") or "")
    on_pace = zone in ("Leader", "Leader's Back / Box Seat", "Handy")
    solitary_leader = zone == "Leader"
    has_cover = ("Box Seat" in tag) or (zone in ("Leader's Back / Box Seat", "Handy", "Midfield")
                                        and (runner.get("lane") or 9) <= 2)

    if kind == "headwind":
        if solitary_leader:
            return DRAG_TAX, {"name": "Aerodynamic Drag Tax", "points": DRAG_TAX, "type": "penalty"}
        if has_cover and zone in ("Leader's Back / Box Seat", "Handy", "Midfield"):
            return SLIPSTREAM_BONUS, {"name": "Slipstream Drafting", "points": SLIPSTREAM_BONUS, "type": "bonus"}
    elif kind == "tailwind":
        if on_pace:
            return TAILWIND_BONUS, {"name": "Tailwind Propulsion", "points": TAILWIND_BONUS, "type": "bonus"}
    return 0.0, None


if __name__ == "__main__":
    w = simulate_wind("Flemington", "2026-10-26")
    s = classify_wind(w, "Flemington")
    print(w, s)
    print(wind_modifier(s, {"settle_zone": "Leader", "tactical_tag": "Clear Run", "lane": 1}))
