"""In-race AI Co-Pilot (Situational Analyst) for The Edge - Phase 5.

A local, rule-based analyst (no external API / keys, consistent with the
project's mock mode). It is fed the full context of the selected race and
answers nuanced situational questions - pace & bias suitability, heavy-track
bounce risk, and underrated value angles - recommending positive or negative
manual score adjustments. All reasoning is derived from the supplied context,
not an LLM.
"""


def build_context(race, meeting, rows, par, track_bias):
    """Assemble the analytical context dict from evaluated runner rows."""
    runners = []
    for r in rows:
        if r.get("scratched"):
            continue
        runners.append({
            "name": r["horse_name"], "barrier": r["barrier"], "weight": r["weight"],
            "projected": r["projected"], "par_delta": r["par_delta"],
            "lane": r.get("settling"), "market": r.get("market"),
            "fair": r.get("disp_fair"), "edge": r.get("edge"),
            "angles": r.get("angles", []),
        })
    return {
        "track": meeting["track_name"], "distance": race["distance"],
        "rail": meeting["rail_position"], "condition": meeting["condition"],
        "par": par, "pace": race["pace_pressure_index"], "bias": track_bias,
        "runners": runners,
    }


SAMPLE_PROMPTS = [
    "🔍 Analyze Pace & Bias Suitability",
    "⚠️ Check Heavy Track Bounce Risks",
    "💡 Find Underrated Value Angles",
]


def _hdr(ctx):
    return ("**{track} {dist}m — {cond}** · Rail {rail} · Par to win **{par:.1f}** · "
            "Pace Pressure **{pace:.2f}** · Track bias: **{bias}**").format(
        track=ctx["track"], dist=ctx["distance"], cond=ctx["condition"],
        rail=ctx["rail"], par=ctx["par"], pace=ctx["pace"], bias=ctx["bias"])


def _analyze_pace(ctx):
    leaders = [r for r in ctx["runners"] if r["lane"] and r["lane"] <= 2]
    swoopers = [r for r in ctx["runners"] if r["lane"] and r["lane"] >= 6]
    lines = [_hdr(ctx), "", "**Pace & bias read:**"]
    hot = ctx["pace"] >= 1.05
    lines.append("- Projected on-pace runners: " + (", ".join(
        "{} (lane {})".format(r["name"], r["lane"]) for r in leaders) or "none"))
    lines.append("- Projected swoopers/backmarkers: " + (", ".join(
        "{} (lane {})".format(r["name"], r["lane"]) for r in swoopers) or "none"))
    if hot and len(leaders) >= 3:
        lines.append("- ⚠️ **Hot, contested lead** (pace {:.2f}, {} on-pace). Expect a genuine "
                     "tempo — leaners up front are vulnerable late.".format(ctx["pace"], len(leaders)))
    elif ctx["pace"] <= 0.95:
        lines.append("- 🐢 **Soft tempo likely** — on-pace runners can dictate and prove hard to run down.")
    if ctx["bias"] == "Leader Bias":
        lines.append("- With a **leader-biased** surface, lean **+** on genuine on-pacers and "
                     "**−** on swoopers that need luck from behind.")
    elif ctx["bias"] == "Swooper Bias":
        lines.append("- With a **swooper-biased** surface, lean **+** on strong finishers wide/back "
                     "and **−** on one-paced leaders.")
    else:
        lines.append("- Track rated **fair** — no blanket on-pace/back adjustment; judge on merit.")
    lines.append("")
    lines.append("**Suggested manual nudges:** " + (", ".join(
        "{} {:+.1f}".format(r["name"],
                            1.5 if ctx["bias"] == "Leader Bias" else (-1.0 if ctx["bias"] == "Swooper Bias" else 0.0))
        for r in leaders) or "none obvious"))
    return "\n".join(lines)


def _analyze_bounce(ctx):
    risky = [r for r in ctx["runners"]
             if any(a["name"] == "Heavy Hangover" for a in r["angles"])]
    lines = [_hdr(ctx), "", "**Heavy-track bounce / fatigue check:**"]
    if risky:
        for r in risky:
            lines.append("- 🔴 **{}** flags a *Heavy Hangover* (quick back-up on Good after a Heavy "
                         "run). Bounce/fatigue risk — consider a **−1.0 to −1.5** manual adjustment.".format(r["name"]))
    else:
        lines.append("- No runners currently trip the Heavy-Hangover angle for this race "
                     "(today's deck is **{}**). No bounce penalty warranted.".format(
                         ctx["condition"].split()[0]))
    heavy_stoppers = [r for r in ctx["runners"]
                      if any(a["name"] == "Weight Stopper" for a in r["angles"])]
    if heavy_stoppers:
        lines.append("- ⚖️ Weight-stopper watch: " + ", ".join(r["name"] for r in heavy_stoppers)
                     + " (≥60kg stepping up) — tiring late is a risk.")
    return "\n".join(lines)


def _analyze_value(ctx):
    lines = [_hdr(ctx), "", "**Underrated value angles:**"]
    # Runners the model likes (projected >= par) that are drifting / priced long.
    picks = sorted(ctx["runners"], key=lambda r: -(r["edge"] or 0))
    shown = 0
    for r in picks:
        pos_angles = [a for a in r["angles"] if a["points"] > 0]
        if (r["edge"] is not None and r["edge"] >= 0.10
                and r["projected"] >= ctx["par"] - 1.5):
            tag = (" + angles: " + ", ".join("{} ({:+.1f})".format(a["name"], a["points"])
                                             for a in pos_angles)) if pos_angles else ""
            lines.append("- 💡 **{}** — projected {:.1f} (Δpar {:+.1f}), ${:.2f} vs fair ${:.2f} "
                         "(+{:.0f}% edge){}.".format(
                             r["name"], r["projected"], r["par_delta"], r["market"],
                             r["fair"], r["edge"] * 100, tag))
            shown += 1
        if shown >= 4:
            break
    if shown == 0:
        lines.append("- Nothing clearly underrated right now — prices broadly track the model. "
                     "Try a market tick or a track-bias setting to surface angles.")
    else:
        lines.append("")
        lines.append("These are where live price lags the projected rating — the core of a value edge.")
    return "\n".join(lines)


import re
import custom_rules

# Quantitative point calibration (points -> approx lengths of real-world impact).
CAL_DOMINANT = 2.5      # dominant pattern / outside straight gutter (~1.7-2.0L)
CAL_ONPACE = 1.75       # solid tactical on-pace / leader bias (~1.0-1.3L)
CAL_MINOR = 1.0         # minor tactical / barrier advantage (~0.7L)
CAL_3WNC = -2.0         # three-wide no cover penalty
CAL_TRAPPED = -1.5      # trapped back / on the rail


def _explicit_points(low):
    # Explicit "+2.5 pts" / "2 points" form.
    m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(?:pts?|points?)", low)
    if m:
        return float(m.group(1))
    # A signed number like "+1.5" or "-2", but NOT a number inside a range such
    # as the "-7" in "lanes 4-7" (guarded by the look-behind/ahead).
    m = re.search(r"(?<![\d.\-])([+-]\d+(?:\.\d+)?)(?!\d)", low)
    if m:
        return float(m.group(1))
    return None


def parse_rule_request(text, runners):
    """Translate a conversational rule request into a proposed CustomRule spec.

    `runners` is a list of dicts carrying lane/barrier/settle_zone/weight/
    prep_stage/prep_run_num/tactical_tag so we can preview the target horses.
    Returns a proposal dict, or None if the request could not be understood.
    """
    low = (text or "").lower().strip()
    if not low:
        return None
    penalty_word = any(w in low for w in ("penal", "tax", "disadvant", "against",
                                          "trapped", "caught", "docked", "downgrade"))
    bonus_word = any(w in low for w in ("bonus", "reward", "boost", "favour", "favor",
                                        "give", "upgrade", "suit", "advantage", "dominant"))
    pts = _explicit_points(low)

    ft, params, desc, base = None, {}, None, None
    m_lane = re.search(r"lanes?\s*(\d+)\s*(?:-|to|through|thru|and|&)\s*(\d+)", low)
    m_bar = re.search(r"barriers?\s*(\d+)\s*(?:-|to|through|thru|and|&)\s*(\d+)", low)
    m_up = re.search(r"(\d)(?:st|nd|rd|th)[\s-]?up", low)
    m_over = re.search(r"(?:over|above|>=?|at least)\s*(\d+(?:\.\d+)?)\s*kg", low)
    m_under = re.search(r"(?:under|below|<|less than)\s*(\d+(?:\.\d+)?)\s*kg", low)

    if "3wnc" in low or ("3" in low and "wide" in low) or ("three" in low and "wide" in low):
        ft, params, base, desc = "tactical_tag", {"tag": "3WNC"}, CAL_3WNC, "3WNC Tax (caught wide, no cover)"
    elif "box seat" in low or "dream run" in low:
        ft, params, base, desc = "tactical_tag", {"tag": "Box Seat"}, CAL_ONPACE, "Box Seat Bonus"
    elif "duel" in low or "suicidal" in low:
        ft, params, base, desc = "tactical_tag", {"tag": "Contested Duel"}, -2.0, "Contested Duel Penalty"
    elif "pocket" in low or ("trap" in low and "rail" in low):
        ft, params, base, desc = "tactical_tag", {"tag": "Pocketed"}, CAL_TRAPPED, "Pocketed / Trapped Penalty"
    elif m_lane:
        a, b = int(m_lane.group(1)), int(m_lane.group(2))
        ft, params, base, desc = "lane_range", {"min_lane": a, "max_lane": b}, CAL_DOMINANT, "Lanes {}-{} Bias".format(a, b)
    elif "outside" in low and ("straight" in low or "gutter" in low or "run down" in low):
        ft, params, base, desc = "lane_range", {"min_lane": 3, "max_lane": 7}, CAL_DOMINANT, "Outside-Straight Gutter Bias"
    elif m_bar:
        a, b = int(m_bar.group(1)), int(m_bar.group(2))
        ft, params, base, desc = "barrier_range", {"min_barrier": a, "max_barrier": b}, CAL_MINOR, "Barriers {}-{} Bias".format(a, b)
    elif "leader" in low or "on-pace" in low or "on pace" in low or "frontrunner" in low or "lead" in low:
        ft, params, base, desc = "settle_zone", {"zones": ["Leader"]}, CAL_ONPACE, "Leader / On-Pace Bias"
    elif "backmarker" in low or "swooper" in low or "get back" in low:
        ft, params, base, desc = "settle_zone", {"zones": ["Backmarker", "Worse Than Midfield"]}, CAL_ONPACE, "Backmarker Bias"
    elif m_over or "topweight" in low or "big weight" in low:
        thr = float(m_over.group(1)) if m_over else 60.0
        ft, params, base, desc = "weight_threshold", {"min_weight": thr}, CAL_TRAPPED, "Weight >= {}kg".format(thr)
    elif m_under or "lightweight" in low:
        thr = float(m_under.group(1)) if m_under else 54.5
        ft, params, base, desc = "weight_threshold", {"max_weight": thr}, CAL_MINOR, "Weight < {}kg".format(thr)
    elif m_up:
        stage = {"1": "1st-up", "2": "2nd-up", "3": "3rd-up", "4": "4th-up", "5": "5th+ up"}[m_up.group(1)]
        ft, params, base, desc = "prep_stage", {"stage": stage}, CAL_MINOR, "{} Bias".format(stage.title())
    else:
        return None

    if pts is not None:
        points = pts
    else:
        points = base
        if penalty_word and points > 0:
            points = -abs(points)
        elif bonus_word and points < 0 and not penalty_word:
            points = abs(points)

    full_desc = "{} ({:+.1f} pts)".format(desc, points)
    targets = [r["name"] for r in runners if custom_rules.match(ft, params, r)]
    return {"description": full_desc, "points": round(points, 2),
            "filter_type": ft, "filter_params": params, "targets": targets}


def analyze(ctx, question):
    """Route a question (sample prompt or free text) to the right analysis."""
    q = (question or "").lower()
    if "pace" in q or "bias" in q or "suitab" in q:
        return _analyze_pace(ctx)
    if "bounce" in q or "heavy" in q or "fatigue" in q:
        return _analyze_bounce(ctx)
    if "value" in q or "underrated" in q or "angle" in q:
        return _analyze_value(ctx)
    # Generic: brief overview + top rated.
    top = sorted(ctx["runners"], key=lambda r: -r["projected"])[:3]
    lines = [_hdr(ctx), "", "**Quick read:** top projected — " + ", ".join(
        "{} ({:.1f})".format(r["name"], r["projected"]) for r in top),
        "", "Ask about **pace & bias**, **bounce risks**, or **value angles** for a deeper look."]
    return "\n".join(lines)
