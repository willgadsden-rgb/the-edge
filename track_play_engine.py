"""Historical track-play synthesis for The Edge.

Given a track, its rail position and the day's wind, describe how the track is
likely to play (on-pace vs swoopers, inside vs wide draws). The rail and wind
notes are rules of thumb; the history line is counted from the winners on file
(form_model.track_stats) and says so plainly when there are none.
"""


def rail_out_m(rail_position):
    """Parse a rail-position string ('True', '+3m', '6m') to metres out from true."""
    s = (rail_position or "").lower().replace("m", "").replace("+", "").strip()
    if s in ("true", "", "0"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def analyze_track_play(track_name, rail_position, wind, distance=None, history_stats=None):
    """Return a dict describing how the track is likely to play today."""
    out = rail_out_m(rail_position)

    # --- rail effect ------------------------------------------------------
    if out <= 0:
        rail_note = "True rail — even going right across the track; no strong fence bias."
        rail_pace, rail_wide = 0, 0
    elif out < 5:
        rail_note = ("Rail out {:.0f}m — fresh, rested ground on the fence. Runners who find the "
                     "rail are hard to pass; on-pace and inside draws are favoured.").format(out)
        rail_pace, rail_wide = 2, -1
    else:
        rail_note = ("Rail out {:.0f}m — a big move onto fresh ground. Strong advantage to the "
                     "fence and on-pace runners; wide draws give away ground.").format(out)
        rail_pace, rail_wide = 3, -2

    # --- wind effect (v_parallel: + = headwind in the straight) -----------
    vp = float(wind.get("v_parallel", 0.0)) if wind else 0.0
    label = (wind or {}).get("label", "calm")
    if vp >= 12:
        wind_note = ("Headwind down the home straight ({}) — leaders are exposed and tire late, "
                     "so swoopers get a tow and are advantaged.").format(label)
        wind_pace = -2
    elif vp <= -12:
        wind_note = ("Tailwind down the home straight ({}) — on-pace runners get pushed along and "
                     "are hard to run down.").format(label)
        wind_pace = 2
    else:
        wind_note = "Light or cross wind ({}) — little effect on where the race is won.".format(label)
        wind_pace = 0

    pace = rail_pace + wind_pace
    if pace >= 2:
        headline, lean = "On-pace & inside bias", "Leaders / on-pace"
    elif pace <= -2:
        headline, lean = "Swoopers & off-pace favoured", "Backmarkers / swoopers"
    else:
        headline, lean = "Fairly even — no strong bias", "No strong lean"

    # --- real history: winners on file at this track ----------------------
    leader_pct = inside_pct = avg_bar = None
    hs = (history_stats or {})
    pick = hs.get("near_trip") if (hs.get("near_trip") or {}).get("races", 0) >= 15 else hs.get("all")
    if pick:
        leader_pct, inside_pct, avg_bar = pick["leader_pct"], pick["inside_pct"], pick["avg_barrier"]
        scope = "within 200m of today's trip" if pick is hs.get("near_trip") else "all distances"
        parts = []
        if leader_pct is not None:
            parts.append("leaders won {}% ({} races)".format(leader_pct, pick["leader_n"]))
        if inside_pct is not None:
            parts.append("inside-half barriers won {}% ({} races)".format(inside_pct, pick["inside_n"]))
        if avg_bar is not None:
            parts.append("average winning barrier {:.1f}".format(avg_bar))
        history = "Winners on file here, {} ({} races): {}.".format(scope, pick["races"], "; ".join(parts))
    else:
        history = "No winners on file at this track yet - the history database fills this in as cards are harvested."

    return {
        "headline": headline, "lean": lean, "rail_note": rail_note, "wind_note": wind_note,
        "history": history, "pace": pace, "wide": rail_wide, "rail_out": out,
        "leader_pct": leader_pct, "inside_pct": inside_pct, "avg_bar": avg_bar,
    }


if __name__ == "__main__":
    w = {"v_parallel": 18.0, "label": "Headwind 18 km/h"}
    print(analyze_track_play("Rosehill", "+6m", w, 1400)["headline"])
    print(analyze_track_play("Flemington", "True", {"v_parallel": 2.0, "label": "calm"}, 1600)["history"])
    print(analyze_track_play("Flemington", "True", None, 1600, history_stats={"all": {
        "races": 40, "leader_pct": 22, "leader_n": 38, "inside_pct": 55, "inside_n": 36, "avg_barrier": 6.1}})["history"])
