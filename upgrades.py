"""Read a horse's last starts the way a good judge does: against the day.

A run is worth more or less than the bare result depending on what was winning
at that meeting. A horse that came from the back on a day the leaders dominated
ran better than its placing says; one that led on that same day ran worse. The
same goes for the draw, for the strength of the race, and for a horse that
rated the best run in the race without winning.

Everything here is computed from real stored runs: no estimates, no guesses
from a name. Where the data for a meeting is thin, no flag is produced.
"""

MIN_WINNERS = 5          # winners needed at a meeting before calling its bias
STRONG = 0.60            # share of winners that makes a day's pattern a bias
TOP_PLACING = 3          # "ran well" for the purposes of an upgrade


def _zone(settle, field):
    """Where a horse was early: led, handy, midfield or back."""
    if not settle or not field or field < 5:
        return None
    if settle == 1:
        return "led"
    if settle <= 3:
        return "handy"
    return "midfield" if settle <= round(field * 0.6) else "back"


def _third(barrier, field):
    if not barrier or not field or field < 8:
        return None
    t = -(-field // 3)
    return "inside" if barrier <= t else "middle" if barrier <= 2 * t else "wide"


def meeting_bias(winners):
    """winners: rows of (settle_pos, barrier, field_size) for a meeting's winners.
    Returns {'pace': 'on-pace'|'backmarkers'|None, 'draw': 'inside'|'wide'|None, 'n': int}."""
    zones = [z for z in (_zone(s, f) for s, _b, f in winners) if z]
    thirds = [t for t in (_third(b, f) for _s, b, f in winners) if t]
    out = {"pace": None, "draw": None, "n": len(winners), "n_pace": len(zones), "n_draw": len(thirds)}
    if len(zones) >= MIN_WINNERS:
        on = sum(1 for z in zones if z in ("led", "handy")) / len(zones)
        if on >= STRONG:
            out["pace"] = "on-pace"
        elif 1 - on >= STRONG:
            out["pace"] = "backmarkers"
    if len(thirds) >= MIN_WINNERS:
        ins = sum(1 for t in thirds if t == "inside") / len(thirds)
        wide = sum(1 for t in thirds if t == "wide") / len(thirds)
        if ins >= 0.5:
            out["draw"] = "inside"
        elif wide >= 0.5:
            out["draw"] = "wide"
    return out


def run_flags(run, bias, best_rating=None):
    """Flags for one past run. `run` needs pos, field, settle, barrier, rating;
    `bias` is that meeting's bias; `best_rating` the best rating in that race.

    Each flag is (code, text, direction) where direction is +1 for an upgrade,
    -1 for a downgrade. Only facts we hold produce a flag.
    """
    out = []
    pos, field = run.get("pos"), run.get("field")
    zone = _zone(run.get("settle"), field)
    third = _third(run.get("barrier"), field)
    ran_well = bool(pos and pos <= TOP_PLACING)
    bias = bias or {}

    if bias.get("pace") == "on-pace" and zone in ("midfield", "back"):
        out.append(("pace_against", "came from behind on a day the leaders dominated", 1 if ran_well else 0))
    if bias.get("pace") == "backmarkers" and zone in ("led", "handy"):
        out.append(("pace_against", "was on the pace on a day they ran them down", 1 if ran_well else 0))
    if bias.get("pace") == "on-pace" and zone in ("led", "handy") and ran_well:
        out.append(("pace_with", "led or sat handy on a day that suited exactly that", -1))
    if bias.get("pace") == "backmarkers" and zone == "back" and ran_well:
        out.append(("pace_with", "came from the back on a day that suited exactly that", -1))
    if bias.get("draw") == "inside" and third == "wide":
        out.append(("draw_against", "drew the outside third on a day the fence was winning", 1 if ran_well else 0))
    if bias.get("draw") == "wide" and third == "inside" and ran_well:
        out.append(("draw_with", "drew inside on a day the wide draws were winning", -1))

    r = run.get("rating")
    if r and best_rating and pos and pos > 1 and r >= best_rating - 0.05:
        out.append(("best_in_race", "rated the best run in the race without winning", 1))
    nr, nw = run.get("next_runs") or 0, run.get("next_wins") or 0
    if nr >= 8 and nw >= 3:
        out.append(("strong_race", "{} winners have come out of that race since".format(nw), 1))
    if nr >= 10 and nw == 0:
        out.append(("weak_race", "nothing out of that race has won since", -1))
    return [f for f in out if f[2] != 0]


def load_context(db, race_ids):
    """For a set of past race ids: each race's meeting bias and best rating.

    Two queries against the history database, whatever the size of the card.
    Returns {race_id: {'bias': {...}, 'best_rating': float|None}}.
    """
    ids = sorted({r for r in race_ids if r})
    if not ids:
        return {}
    out, meetings = {}, {}
    for chunk in (ids[i:i + 400] for i in range(0, len(ids), 400)):
        marks = ",".join("?" for _ in chunk)
        for rid, mid, best in db.query(
                "SELECT ra.race_id, ra.meeting_id, MAX(NULLIF(r.wfa_rating, 0)) "
                "FROM races ra LEFT JOIN runs r ON r.race_id = ra.race_id "
                "WHERE ra.race_id IN ({}) GROUP BY ra.race_id, ra.meeting_id".format(marks), tuple(chunk)):
            out[rid] = {"meeting_id": mid, "best_rating": best, "bias": None}
            meetings.setdefault(mid, [])
    mids = [m for m in meetings if m]
    for chunk in (mids[i:i + 200] for i in range(0, len(mids), 200)):
        marks = ",".join("?" for _ in chunk)
        for mid, settle, barrier, field in db.query(
                "SELECT ra.meeting_id, r.settle_pos, r.barrier, COALESCE(r.field_size, ra.field_size) "
                "FROM runs r JOIN races ra ON ra.race_id = r.race_id "
                "WHERE ra.meeting_id IN ({}) AND r.finish_pos = 1".format(marks), tuple(chunk)):
            meetings[mid].append((settle, barrier, field))
    bias = {mid: meeting_bias(rows) for mid, rows in meetings.items()}
    for rid, v in out.items():
        v["bias"] = bias.get(v["meeting_id"])
    return out


def annotate(last_runs, ctx):
    """Add 'flags' to each last run in place and return the runner-level summary:
    the flags on the most recent run, which is the one that changes today's price."""
    for run in last_runs or []:
        c = ctx.get(run.get("rid")) or {}
        fl = run_flags(run, c.get("bias"), c.get("best_rating"))
        if fl:
            run["flags"] = [{"code": a, "text": b, "dir": d} for a, b, d in fl]
    first = (last_runs or [{}])[0].get("flags") or []
    up = [f for f in first if f["dir"] > 0]
    down = [f for f in first if f["dir"] < 0]
    return {"up": len(up), "down": len(down),
            "summary": "; ".join(f["text"] for f in (up + down)) or None,
            "code": (up or down or [{}])[0].get("code")}
