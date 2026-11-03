"""Historical track bias for The Edge (step 3 of the bias/trigger build).

The Form King feed carries no standalone results table, but every runner's
`last5_json` holds its recent runs — each with the track, going, barrier, field
size, settling position and finish. Aggregating those across the whole card's
runners gives a real, live-derived sample of how a track plays on a given going:
which barrier groups and which settling zones actually win there.

Strict live-only: the sample is real historical form, nothing fabricated. Rail
position is NOT in the per-run data, so the prior is keyed on track + going band
only (not rail band) — see get_historical_track_bias.
"""

import json

MIN_SAMPLE = 20                 # need this many matching runs to show a prior

# Barrier groups (by the gate drawn that run).
BARRIER_GROUPS = [("Inside", 1, 4), ("Middle", 5, 8), ("Outside", 9, 99)]

# Settling zones by settled position as a fraction of field size.
#   <=0.20 Leader · <=0.45 Stalker · <=0.70 Midfield · else Swooper
ZONE_BANDS = [("Leader", 0.20), ("Stalker", 0.45), ("Midfield", 0.70), ("Swooper", 1.01)]


# --- going bands -------------------------------------------------------------
def going_band(going):
    """Map a going string (either naming scheme) to DRY / SOFT / HEAVY / SYN.

    Form King mixes the modern (Good/Soft/Heavy) and legacy (Fast/Dead/Slow)
    labels, so match on keywords. Synthetic surfaces are their own band.
    """
    g = (going or "").strip().lower()
    if not g:
        return None
    if any(t in g for t in ("synthetic", "poly", "tapeta", "cushion")):
        return "SYN"
    if "heavy" in g:
        return "HEAVY"
    if any(t in g for t in ("soft", "dead", "slow")):
        return "SOFT"
    if any(t in g for t in ("good", "firm", "fast")):
        return "DRY"
    return None


def _zone(settle, nrun):
    """Settling zone from settled position and field size (absolute fallback)."""
    if not isinstance(settle, int) or settle < 1:
        return None
    if isinstance(nrun, int) and nrun > 1:
        frac = (settle - 1) / (nrun - 1)
        for name, hi in ZONE_BANDS:
            if frac <= hi:
                return name
    # No field size: crude absolute bands.
    if settle <= 2:
        return "Leader"
    if settle <= 4:
        return "Stalker"
    if settle <= 8:
        return "Midfield"
    return "Swooper"


def _collect_runs(conn, track_name, band):
    """Gather every historical run at `track_name` on going `band` from the
    last5_json of every runner on the card. Returns a list of run dicts."""
    runs = []
    for (blob,) in conn.execute("SELECT last5_json FROM race_entries WHERE last5_json IS NOT NULL"):
        try:
            for r in json.loads(blob or "[]"):
                if (r.get("track") == track_name and going_band(r.get("going")) == band
                        and isinstance(r.get("pos"), int)):
                    runs.append(r)
        except Exception:
            continue
    return runs


def get_historical_track_bias(conn, track_name, track_condition):
    """Barrier-group and settling-zone bias for a track on today's going band.

    Aggregates the card's runners' past runs at this track on a matching going.
    Returns a summary dict, or {"available": False, ...} when the sample is too
    thin. Barrier Impact Value (IV) = a group's win share / its runner share
    (1.0 = neutral, >1 favoured). Zones report win%.
    """
    band = going_band(track_condition)
    out = {"available": False, "track": track_name, "band": band, "n": 0,
           "barrier_iv": {}, "zone_win": {}, "assessment": None}
    if band is None:
        return out

    runs = _collect_runs(conn, track_name, band)
    n = len(runs)
    out["n"] = n
    if n < MIN_SAMPLE:
        return out

    wins = sum(1 for r in runs if r["pos"] == 1)
    if wins == 0:
        return out
    win_share = wins / n

    # Barrier-group impact values.
    barrier_iv = {}
    for name, lo, hi in BARRIER_GROUPS:
        grp = [r for r in runs if isinstance(r.get("barrier"), int) and lo <= r["barrier"] <= hi]
        if len(grp) >= 5:
            grp_win = sum(1 for r in grp if r["pos"] == 1)
            iv = (grp_win / len(grp)) / win_share if win_share else 0.0
            barrier_iv[name] = round(iv, 2)
    out["barrier_iv"] = barrier_iv

    # Settling-zone win rates.
    zone_win = {}
    for name, _ in ZONE_BANDS:
        z = [r for r in runs if _zone(r.get("settle"), r.get("nrun")) == name]
        if len(z) >= 5:
            zone_win[name] = round(100.0 * sum(1 for r in z if r["pos"] == 1) / len(z), 1)
    out["zone_win"] = zone_win

    # Executive assessment string.
    parts = []
    if barrier_iv:
        best_bar = max(barrier_iv, key=barrier_iv.get)
        if barrier_iv[best_bar] >= 1.15:
            parts.append("{} barriers favoured (IV {:.2f})".format(best_bar, barrier_iv[best_bar]))
        worst_bar = min(barrier_iv, key=barrier_iv.get)
        if barrier_iv[worst_bar] <= 0.85:
            parts.append("{} barriers struggle (IV {:.2f})".format(worst_bar, barrier_iv[worst_bar]))
    if zone_win:
        best_zone = max(zone_win, key=zone_win.get)
        parts.append("{}s win {:.0f}%".format(best_zone, zone_win[best_zone]))
    out["available"] = bool(parts)
    out["assessment"] = " · ".join(parts) if parts else None
    return out


def barrier_prior_adjustment(barrier, bias):
    """Small pre-race tactical nudge (+0.5..-0.5 pts) for a runner's barrier,
    from the historical barrier-group IV. Neutral (0.0) without a usable prior."""
    if not bias or not bias.get("available") or barrier is None:
        return 0.0
    for name, lo, hi in BARRIER_GROUPS:
        if lo <= barrier <= hi:
            iv = bias["barrier_iv"].get(name)
            if iv is None:
                return 0.0
            # Map IV 0.7..1.3 -> -0.5..+0.5, clamped.
            return round(max(-0.5, min(0.5, (iv - 1.0) * (0.5 / 0.3))), 2)
    return 0.0


# --- legacy static profile (kept for the rail-profile note on the header) ----
PROFILES = {
    ("Caulfield", "+6m"): {"note": "Rail out 6m, Good 4 — leaders & on-pace favoured", "leader_edge": 1.0},
    ("Moonee Valley", "True"): {"note": "Tight 1805m circuit, true rail — on-pace crucial", "leader_edge": 1.5},
    ("Randwick", "Kensington"): {"note": "Kensington track — hold a position, rails run", "leader_edge": 0.5},
    ("Flemington", "True"): {"note": "True rail — fair, wide-open straight, form holds", "leader_edge": 0.0},
    ("Rosehill", "True"): {"note": "True rail — on-pace with some leader bias", "leader_edge": 0.75},
}
DEFAULT_PROFILE = {"note": "Standard configuration — no strong rail bias", "leader_edge": 0.0}


def profile_for(track_name, rail_position):
    """Return the static rail-setup note for a track + rail (header blurb)."""
    key = (track_name, (rail_position or "").split()[0] if rail_position else "")
    if key in PROFILES:
        return PROFILES[key]
    for (t, _), prof in PROFILES.items():
        if t == track_name:
            return prof
    return DEFAULT_PROFILE


if __name__ == "__main__":
    print(going_band("Dead 5"), going_band("Good 4"), going_band("Heavy 8"), going_band("Synthetic 0"))
