"""Form King native triggers for The Edge (step 2 of the bias/trigger build).

Pure functions over the live-mapped fields — price flucs, apprentice claim, each
runner's recent track speed and going — that produce the #3 trigger signals shown
on the card and folded into the projected score. Strict live-only: every input is
real Form King data, nothing is fabricated.

Signals:
  * Late steam plunge   — price shortened sharply across the last few flucs.
  * Uncontested leader / pace duel — from recent track-speed figures.
  * Apprentice claim    — weight relief, worth +0.38 pts/kg (the engine's
                          WEIGHT_PER_KG), applied via the carried weight.
  * Proven wet-tracker  — a horse with wet-track form, on a Soft/Heavy day.
"""

# --- late steam plunge -------------------------------------------------------
STEAM_DROP_PCT = 0.12          # >= 12% shorter across the recent ticks = steam
STEAM_TICKS = 3                # compare across the last N flucs

# --- pace (from recent track-speed figures, m/s) -----------------------------
LONE_LEADER_SPEED = 16.8       # fast enough to lead unchallenged
LONE_LEADER_CLEAR = 0.8        # m/s clear of the next-fastest runner
PACE_DUEL_SPEED = 17.2         # genuine high-pressure pace
LONE_LEADER_PTS = 1.0
PACE_DUEL_PTS = -1.0

# --- apprentice claim --------------------------------------------------------
CLAIM_PTS_PER_KG = 0.38        # matches rating_engine.WEIGHT_PER_KG

# --- wet form ----------------------------------------------------------------
WET_TOKENS = ("soft", "heavy", "slow", "wet")   # going strings that mean wet


def steam_signal(flucs, firm_or_drift=None, ticks=STEAM_TICKS, drop=STEAM_DROP_PCT):
    """Detect a late steam plunge from the price fluctuation series.

    flucs: list of decimal prices oldest->newest. Returns
    {"is_steaming": bool, "pct": float} where pct is the move across the last
    `ticks` points (negative = shortened/firmed). Falls back to firm_or_drift
    (the feed's own net move) when the series is too short to read.
    """
    seq = [float(f) for f in (flucs or []) if isinstance(f, (int, float)) and f > 1.0]
    if len(seq) >= 2:
        window = seq[-ticks:] if len(seq) >= ticks else seq
        first, last = window[0], window[-1]
        pct = (last / first) - 1.0 if first else 0.0
        return {"is_steaming": pct <= -drop, "pct": pct}
    # Sparse flucs: use the feed's firmOrDrift if it clearly says firming.
    if isinstance(firm_or_drift, (int, float)) and firm_or_drift <= -1.5:
        return {"is_steaming": True, "pct": None}
    return {"is_steaming": False, "pct": None}


def speed_figure(last5):
    """A runner's recent speed figure (m/s): the best track speed in its last 5
    actual runs, or None if the feed carried no track-speed for any of them."""
    spds = [r.get("trackspd") for r in (last5 or []) if isinstance(r.get("trackspd"), (int, float))]
    return max(spds) if spds else None


def pace_signals(speed_by_name):
    """Race-level pace read from {name: speed_figure}.

    Returns {name: (points, chip_name)} for the affected runners:
      * two or more runners at/over PACE_DUEL_SPEED -> each gets a duel penalty,
      * else the fastest, if it clears LONE_LEADER_SPEED and is LONE_LEADER_CLEAR
        ahead of the next, gets the lone-leader bonus.
    Runners with no speed figure are ignored.
    """
    pairs = [(n, s) for n, s in speed_by_name.items() if isinstance(s, (int, float))]
    if len(pairs) < 2:
        return {}
    pairs.sort(key=lambda x: -x[1])
    fast = [n for n, s in pairs if s >= PACE_DUEL_SPEED]
    if len(fast) >= 2:
        return {n: (PACE_DUEL_PTS, "High-Pressure Pace Duel") for n in fast}
    top_name, top = pairs[0]
    second = pairs[1][1]
    if top >= LONE_LEADER_SPEED and (top - second) >= LONE_LEADER_CLEAR:
        return {top_name: (LONE_LEADER_PTS, "Uncontested Leader")}
    return {}


def apprentice_badge(claim):
    """Display chip for an apprentice's weight claim (the points come through the
    reduced carried weight in the base rating). None when there's no claim."""
    if claim and claim > 0:
        pts = claim * CLAIM_PTS_PER_KG
        return {"label": "🎓 {:.1f}kg claim ({:+.1f})".format(claim, pts), "cls": "claim"}
    return None


def _is_wet(going):
    return any(tok in (going or "").strip().lower() for tok in WET_TOKENS)


def wet_form_signal(last5, condition):
    """Proven wet-tracker bonus on a Soft/Heavy day.

    Only fires when today's condition is wet AND the horse has wet-track runs in
    its last 5. Scaled by its best wet finish: a win +1.2, a placing +0.8.
    Returns (points, chip_name) or (0.0, None).
    """
    if not _is_wet(condition):
        return (0.0, None)
    wet = [r for r in (last5 or []) if _is_wet(r.get("going"))]
    best = min((r.get("pos") for r in wet if isinstance(r.get("pos"), int)), default=99)
    if best == 1:
        return (1.2, "Proven Wet-Tracker")
    if best <= 3:
        return (0.8, "Wet-Track Form")
    return (0.0, None)
