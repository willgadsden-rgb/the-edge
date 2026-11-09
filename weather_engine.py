"""Environmental physics & live wind vectors for The Edge (Phase 7).

Models how wind down the home straight helps or hurts different running styles.
Track compass bearings give the direction horses run in the straight; a wind
vector (speed + direction it blows FROM) is resolved onto that axis. The vector
is read LIVE from the Open-Meteo weather API for the track's coordinates
(fetch_live_wind). When the call fails or the track's coordinates are unknown there
is no wind read at all - nothing is made up.
"""

import math

import requests

# Track coordinates (lat, lon) for the live wind lookup.
TRACK_COORDS = {
    "Flemington": (-37.787, 144.908), "Caulfield": (-37.882, 145.042),
    "Moonee Valley": (-37.765, 144.932), "Sandown": (-37.945, 145.164),
    "Ballarat": (-37.512, 143.836), "Bendigo": (-36.741, 144.300),
    "Geelong": (-38.168, 144.342), "Pakenham": (-38.067, 145.520),
    "Randwick": (-33.905, 151.231), "Rosehill": (-33.827, 151.025),
    "Warwick Farm": (-33.912, 150.943), "Kembla Grange": (-34.482, 150.800),
    "Eagle Farm": (-27.431, 153.072), "Doomben": (-27.428, 153.065),
    "Gold Coast": (-28.071, 153.368), "Sunshine Coast": (-26.767, 153.047),
    "Morphettville": (-34.976, 138.546), "Ascot": (-31.920, 115.922),
    "Canberra": (-35.319, 149.198),
}

_WIND_TIMEOUT = 8
_wind_cache = {}            # track_name -> wind dict (per-process; refreshes on reboot)

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


def fetch_live_wind(track_name):
    """Live wind for a track from Open-Meteo: {speed_kmh, from_deg, live:True}.

    Returns None when the track's coordinates are unknown or the call fails, so
    the caller simply skips the wind read. Cached per process (refreshes on a
    reboot) so the race views don't re-hit the API on every rerun.
    """
    if track_name in _wind_cache:
        return _wind_cache[track_name]
    coords = TRACK_COORDS.get(track_name)
    if not coords:
        return None
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": coords[0], "longitude": coords[1],
                    "current": "wind_speed_10m,wind_direction_10m",
                    "wind_speed_unit": "kmh"},
            timeout=_WIND_TIMEOUT)
        resp.raise_for_status()
        cur = resp.json().get("current") or {}
        spd, deg = cur.get("wind_speed_10m"), cur.get("wind_direction_10m")
        if spd is None or deg is None:
            return None
        wind = {"speed_kmh": float(spd), "from_deg": float(deg), "live": True}
        _wind_cache[track_name] = wind
        return wind
    except Exception:
        return None


def wind_for(track_name, meeting_date=""):
    """Live wind from Open-Meteo, or None when it can't be fetched. There is no
    made-up fallback: no live wind means no wind adjustment."""
    return fetch_live_wind(track_name)


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
            "kind": kind, "label": label, "bearing": bearing_for(track_name),
            "live": wind.get("live", False)}


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
    w = {"speed_kmh": 20.0, "from_deg": 180.0, "live": False}   # fixed test vector
    s = classify_wind(w, "Flemington")
    print(w, s)
    print(wind_modifier(s, {"settle_zone": "Leader", "tactical_tag": "Clear Run", "lane": 1}))
