"""Statistical track/rail setup profiles for The Edge (Phase 7).

Captures how major Australian track + rail configurations tend to play, used to
nudge the pace/tactical read. Mock data only (see CLAUDE.md).
"""

# Keyed by (track_name, rail_position). leader_edge: extra tactical weight toward
# on-pace runners (points); note: a short, informal descriptor of the bias.
PROFILES = {
    ("Caulfield", "+6m"): {"note": "Rail out 6m, Good 4 — leaders & on-pace favoured", "leader_edge": 1.0},
    ("Moonee Valley", "True"): {"note": "Tight 1805m circuit, true rail — on-pace crucial", "leader_edge": 1.5},
    ("Randwick", "Kensington"): {"note": "Kensington track — hold a position, rails run", "leader_edge": 0.5},
    ("Flemington", "True"): {"note": "True rail — fair, wide-open straight, form holds", "leader_edge": 0.0},
    ("Rosehill", "True"): {"note": "True rail — on-pace with some leader bias", "leader_edge": 0.75},
}
DEFAULT_PROFILE = {"note": "Standard configuration — no strong rail bias", "leader_edge": 0.0}


def profile_for(track_name, rail_position):
    """Return the statistical profile for a track + rail setup."""
    key = (track_name, (rail_position or "").split()[0] if rail_position else "")
    if key in PROFILES:
        return PROFILES[key]
    for (t, _), prof in PROFILES.items():
        if t == track_name:
            return prof
    return DEFAULT_PROFILE


if __name__ == "__main__":
    print(profile_for("Flemington", "True"))
    print(profile_for("Moonee Valley", "True"))
