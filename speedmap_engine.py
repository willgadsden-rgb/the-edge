"""Tactical speed-map engine for The Edge (Phase 6).

Turns barrier + early-speed + track geometry into institutional-grade tactical
settling: a lateral lane, a running zone, and a tactical risk tag per runner.
Early speed is read live from each runner's real in-run positions (posSettling /
pos400m) via early_speed_from_runs; the name-hash figure is only a fallback for
debutants with no in-run history (see CLAUDE.md, strict live-only).
"""

import json

# Lateral lanes off the inside rail.
LANE_NAMES = {1: "Rail (Fence)", 2: "One-Off", 3: "3-Wide", 4: "4-Wide"}

# Running zones from the front of the field to the back.
ZONE_LEADER = "Leader"
ZONE_BOXSEAT = "Leader's Back / Box Seat"
ZONE_HANDY = "Handy"
ZONE_MIDFIELD = "Midfield"
ZONE_WORSE = "Worse Than Midfield"
ZONE_BACK = "Backmarker"

# Tactical tags.
TAG_3WNC = "3WNC"            # three-wide no cover - caught wide, paying an energy tax
TAG_BOXSEAT = "Box Seat"    # dream run behind the leader on the fence
TAG_POCKETED = "Pocketed"   # held up behind slower runners on the rail
TAG_DUEL = "Contested Duel"  # suicidal early pressure up front
TAG_CLEAR = "Clear Run"

TAG_BLURB = {
    TAG_3WNC: "3WNC - Energy Tax",
    TAG_BOXSEAT: "Box Seat - Dream Run",
    TAG_POCKETED: "Pocketed - Needs Luck",
    TAG_DUEL: "Contested Duel - Suicidal Pace",
    TAG_CLEAR: "Clear Run",
}


def early_speed_rating(horse_name):
    """Neutral early-speed figure (5.0 on the 0-10 scale) for a runner with no
    in-run history, e.g. a debutant. No figure is derived from the name."""
    return 5.0


# Recency weights for the last-5 in-run positions (newest first).
_ES_WEIGHTS = (0.40, 0.25, 0.15, 0.12, 0.08)


def early_speed_from_runs(last5):
    """Real early-speed figure (0-10) from a runner's in-run positions.

    Each past run's settled position as a fraction of the field (0 = led, 1 =
    last) is turned into an early-speed score (led -> ~10, last -> ~0) and
    recency-weighted. Uses posSettling, falling back to the 400m then 800m
    position. Returns None when no run carries usable in-run data (e.g. a
    debutant), so the caller can fall back to the name-hash figure.
    """
    vals, weights = [], []
    for i, r in enumerate(last5 or []):
        if i >= len(_ES_WEIGHTS):
            break
        settle = r.get("settle") or r.get("pos400") or r.get("pos800")
        if not isinstance(settle, int) or settle < 1:
            continue
        # Field size normalises the settling position; the feed doesn't always
        # carry it, so fall back to a typical field of 10 rather than skipping.
        nrun = r.get("nrun")
        field = nrun if (isinstance(nrun, int) and nrun >= 2) else 10
        frac = min(1.0, (settle - 1) / (field - 1))
        vals.append((1.0 - frac) * 10.0)
        weights.append(_ES_WEIGHTS[i])
    if not vals:
        return None
    return round(sum(v * w for v, w in zip(vals, weights)) / sum(weights), 1)


def _last5_of(entry):
    """Parse a card entry's last-5 runs, whether stored as JSON or a list."""
    raw = entry.get("last5_json")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return []
    v = entry.get("last5")
    return v if isinstance(v, list) else []


def _zone(rank, n, is_leader_group):
    if rank == 1:
        return ZONE_LEADER
    frac = rank / max(1, n)
    if rank <= 3 and frac <= 0.35:
        return ZONE_BOXSEAT if rank == 2 else ZONE_HANDY
    if frac <= 0.35:
        return ZONE_HANDY
    if frac <= 0.60:
        return ZONE_MIDFIELD
    if frac <= 0.82:
        return ZONE_WORSE
    return ZONE_BACK


def _lane(barrier, es10, zone, is_leader_group, run_to_turn_m, n):
    """Lateral lane 1-4, applying the 600m slotting rule.

    Long run to the turn (>=350m): there is ample time to ease and slot, so wide-drawn
    backmarkers/midfielders come to the rail or one-off; only Handy/pressing runners with
    real early speed that are out-paced by inside speed and fail to cross stay 3/4-wide.
    Short run (<300m) or a straight course: retain the wide traps for wide barriers.
    """
    long_run = run_to_turn_m is not None and run_to_turn_m >= 350

    # The leader holds the fence; other genuine speed crosses to the fence/one-off.
    if zone == ZONE_LEADER:
        return 1
    if is_leader_group:
        return 1 if barrier <= 5 else 2

    if long_run:
        # Only a pressing/handy runner with moderate+ speed from a wide gate gets caught wide.
        if zone == ZONE_HANDY and es10 >= 5.0 and barrier >= 7:
            return 4 if (barrier >= 10 and es10 >= 6.5) else 3
        if zone in (ZONE_BACK, ZONE_WORSE):
            return 1          # ease right back and save ground on the fence
        if zone == ZONE_MIDFIELD:
            return 2          # one-off, tucked in behind the leaders
        if zone == ZONE_BOXSEAT:
            return 1
        return 1 if barrier <= 4 else 2   # remaining Handy slot in

    # No track geometry (the live feed carries none): settle by position in the run
    # and the draw, the way a form analyst draws a map. Whoever leads holds the
    # fence; the box seat is the fence behind it; anyone else handy from a middle
    # or wide gate sits outside them; backmarkers drop in and save ground.
    if zone == ZONE_LEADER:
        return 1
    if zone == ZONE_BOXSEAT:
        return 1 if barrier <= 6 else 2
    if zone == ZONE_HANDY:
        if barrier <= 4:
            return 1
        return 3 if (barrier >= 10 and es10 >= 5.0) else 2
    if zone == ZONE_MIDFIELD:
        if barrier <= 4:
            return 1
        return 3 if barrier >= 11 else 2
    # Worse than midfield / backmarker: ease and slot in.
    return 1 if barrier <= 7 else 2


def _tag(lane, zone, in_duel):
    if in_duel:
        return TAG_DUEL
    if lane == 1 and zone in (ZONE_BOXSEAT, ZONE_HANDY):
        return TAG_BOXSEAT
    if lane >= 3 and zone in (ZONE_HANDY, ZONE_MIDFIELD, ZONE_WORSE):
        return TAG_3WNC
    if lane == 1 and zone in (ZONE_MIDFIELD, ZONE_WORSE):
        return TAG_POCKETED
    return TAG_CLEAR


# -----------------------------------------------------------------------------
# Predictive pace / tempo modelling (4-tier)
# -----------------------------------------------------------------------------
TEMPO_SLOW = "SLOW"
TEMPO_GENUINE = "GENUINE"
TEMPO_FAST = "FAST"
TEMPO_SUICIDAL = "SUICIDAL"

TEMPO_BADGE = {
    TEMPO_SLOW: "🐢 SLOW (Sit & Sprint)",
    TEMPO_GENUINE: "⚖️ GENUINE",
    TEMPO_FAST: "🔥 FAST",
    TEMPO_SUICIDAL: "💣 SUICIDAL SPEED DUEL",
}


def classify_tempo(n_leaders, pace_pressure):
    """Classify the projected tempo into one of four tiers."""
    # Live cards may carry no pace index; treat a missing value as neutral.
    if pace_pressure is None:
        pace_pressure = 1.0
    if n_leaders >= 4 or pace_pressure >= 1.15:
        tier = TEMPO_SUICIDAL
    elif n_leaders == 3 or pace_pressure >= 1.05:
        tier = TEMPO_FAST
    elif n_leaders <= 1 and pace_pressure <= 0.92:
        tier = TEMPO_SLOW
    else:
        tier = TEMPO_GENUINE
    return tier, TEMPO_BADGE[tier]


def tempo_modifier(tier, zone):
    """Return (points, badge-or-None) for a runner under a given tempo tier.

    Slow tempo boosts leaders / penalises backmarkers; a suicidal duel penalises
    the leaders and upgrades swoopers.
    """
    if tier == TEMPO_SLOW:
        if zone in (ZONE_LEADER, ZONE_BOXSEAT):
            return 1.5, {"name": "Slow-Tempo On-Pace", "points": 1.5, "type": "bonus"}
        if zone in (ZONE_BACK, ZONE_WORSE):
            return -1.5, {"name": "Slow-Tempo Backmarker", "points": -1.5, "type": "penalty"}
    elif tier == TEMPO_SUICIDAL:
        if zone == ZONE_LEADER:
            return -2.0, {"name": "Suicidal-Duel Leader", "points": -2.0, "type": "penalty"}
        if zone in (ZONE_BACK, ZONE_WORSE):
            return 2.0, {"name": "Suicidal-Duel Swooper", "points": 2.0, "type": "bonus"}
    return 0.0, None


import math as _math


def track_point(d, w, geom):
    """Map travelled distance `d` (from the jump) + lane offset `w` to canvas (x, y).

    Full turning-track geometry in three stages:
      Stage 1  Back straight  (0 .. run_to_turn_m): heads east, rail at y=0.
      Stage 2  90-degree left bend (arc of radius turn_radius): curves up-left.
      Stage 3  Home straight (after the bend): heads north toward the winning post.
    A straight course (no turn) is a single east-bound corridor. Lane offset w is
    measured to the outside of the track, so wider runners travel the longer path.
    """
    direction = geom.get("turn_direction", "straight")
    L1 = geom.get("run_to_turn_m")
    R = geom.get("turn_radius")
    if direction == "straight" or not L1 or not R:
        return (d, -w)
    arc = R * _math.pi / 2.0
    L2 = L1 + arc
    # Compute the left-handed (anti-clockwise, Melbourne) path first, then mirror
    # across the back straight for a right-handed (clockwise, Sydney) course.
    if d <= L1:                                   # back straight
        x, y = d, -w
    elif d <= L2:                                 # sweeping bend
        a = d - L1
        radius = R + w
        ang = -_math.pi / 2.0 + a / R
        x, y = (L1 + radius * _math.cos(ang), R + radius * _math.sin(ang))
    else:                                         # home straight
        x, y = (L1 + R + w, R + (d - L2))
    if direction == "right":                      # clockwise: mirror vertically
        y = -y
    return (x, y)


def fan_lane(settle_lane, zone, tag, rank, n):
    """Off-corner lane (1-6): where a runner fans out as the field straightens.

    Rail leaders / pocketed hold the fence; stalkers roll to lane 2-3; swoopers
    and backmarkers fan wide (4-6) into clear galloping room.
    """
    if "Pocketed" in (tag or "") or zone in (ZONE_LEADER, ZONE_BOXSEAT):
        return 1
    if zone == ZONE_HANDY:
        return 2 if settle_lane <= 2 else 3
    if zone == ZONE_MIDFIELD:
        return 3
    if zone == ZONE_WORSE:
        return 4
    if zone == ZONE_BACK:
        return 4 + (rank % 3)                     # spread backmarkers across 4-6
    return min(6, settle_lane + 1)


def corner_role(zone, tag):
    """Short descriptor of a runner's position rounding into the straight."""
    if "Pocketed" in (tag or ""):
        return "🔒 Held Up / Seeking Run"
    if zone == ZONE_LEADER:
        return "Rail Leader — kicks clear"
    if zone == ZONE_BOXSEAT:
        return "Box Seat — one-paced run"
    if zone in (ZONE_BACK, ZONE_WORSE):
        return "Swooper — fans wide for room"
    return "Stalker — rolls into the clear"


def build_tactical_map(entries, geom=None):
    """Return {horse_name: tactical dict} for the active field, plus duel info.

    Each tactical dict: early_speed, lane, lane_name, zone, tag, tag_blurb, rank,
    is_leader_group.
    """
    field = [e for e in entries if not e.get("scratched")]
    n = max(1, len(field))
    for e in field:
        # Real early speed from the runner's in-run positions; a runner with no
        # in-run data (a debutant) takes a neutral 5.0.
        es = early_speed_from_runs(_last5_of(e))
        e["_es10"] = es if es is not None else early_speed_rating(e["horse_name"])
        e["_es_live"] = es is not None

    order = sorted(field, key=lambda e: -e["_es10"])
    rank_by = {e["horse_name"]: i for i, e in enumerate(order, start=1)}
    leaders = {e["horse_name"] for e in field if e["_es10"] >= 7.0}
    duel = len(leaders) >= 3

    run_to_turn = geom.get("run_to_turn_m") if geom else None
    result = {}
    for e in field:
        name = e["horse_name"]
        rank = rank_by[name]
        is_leader = name in leaders
        zone = _zone(rank, n, is_leader)
        lane = _lane(e["barrier"], e["_es10"], zone, is_leader, run_to_turn, n)
        if zone == ZONE_BOXSEAT and lane != 1:
            zone = ZONE_HANDY      # second in the run but outside the leader, not in the box seat
        # Only the speed horses actually up there (top three in the order) are in the duel.
        tag = _tag(lane, zone, duel and is_leader and rank <= 3)
        result[name] = {
            "early_speed": e["_es10"], "es_live": e.get("_es_live", False),
            "rank": rank, "is_leader_group": is_leader,
            "lane": lane, "lane_name": LANE_NAMES[lane], "zone": zone,
            "tag": tag, "tag_blurb": TAG_BLURB[tag],
        }
    return {"runners": result, "duel": duel, "leaders": leaders, "field_size": n}


if __name__ == "__main__":
    demo = [{"horse_name": "Gallant Spur", "barrier": 1},
            {"horse_name": "Northern Echo", "barrier": 8},
            {"horse_name": "Midnight Tempo", "barrier": 4}]
    tm = build_tactical_map(demo)
    for name, t in tm["runners"].items():
        print(name, t["lane_name"], t["zone"], t["tag_blurb"], "ES", t["early_speed"])
