"""High-percentage plays, fades and form tags for a published runner.

Pure functions (no database, no network) so they can be unit-tested and the
rules read in one place. A "play" is a rule-based shortlist, not a proven edge:
every play is written to the paper-bet ledger the first time it is flagged and
graded against the result and the Betfair SP, so the rules earn (or lose) their
place on evidence.
"""

import re

EXCUSE_RE = re.compile(r"(held up|checked|blocked|crowded|bumped|hampered|steadied|shoe|slow(ly)? (away|to begin)|"
                       r"missed the start|without cover|no clear run|clipped heels|eased|awkwardly)", re.I)

PLAY_MIN_CHANCE = 0.25           # our chance of winning
PLAY_MIN_PRICE = 1.60
FADE_RATIO = 1.2                 # model chance at least 20% below the market's
FADE_BAND = (2.2, 18.0)
GOOD_ZONES = ("Leader", "Leader's Back / Box Seat", "Handy", "Midfield")
BAD_TAGS = ("3WNC", "Pocketed", "Contested Duel")

BAND_KEYS = {"Good": ("good", "dead", "fast", "firm"), "Soft": ("slow", "soft"), "Heavy": ("heavy",), "Synthetic": ("synthetic",)}


def going_band(going):
    w = str(going or "").split(" ")[0].lower()
    if w in ("firm", "good", "dead", "fast"):
        return "Good"
    if w in ("soft", "slow"):
        return "Soft"
    if w == "heavy":
        return "Heavy"
    if w.startswith("synth"):
        return "Synthetic"
    return None


def _rec(text):
    m = re.match(r"^(\d+):(\d+)-(\d+)-(\d+)", str(text or ""))
    return tuple(int(x) for x in m.groups()) if m else None


def going_verdict(going_form, band):
    """'suited' | 'fair' | 'poor' | 'unraced' on today's going band, from Form King's
    own going records (same thresholds as the site's track-condition tag)."""
    if not band or band not in BAND_KEYS:
        return "fair"
    g = {str(k).lower(): v for k, v in (going_form or {}).items()}
    n = w = p = 0
    for k in BAND_KEYS[band]:
        r = _rec(g.get(k))
        if r:
            n += r[0]; w += r[1]; p += r[1] + r[2] + r[3]
    if n == 0:
        return "unraced"
    if w / n >= 0.25 or (n >= 2 and p / n >= 0.5):
        return "suited"
    if n >= 3 and w == 0 and p / n < 0.25:
        return "poor"
    return "fair"


def last_start_tags(last_runs, distance):
    """Simple facts about the last start that the Pattern Lab tests."""
    tags = []
    last = (last_runs or [None])[0]
    if not last:
        return tags
    if last.get("pos") == 1:
        tags.append("won_last")
    if last.get("comment") and EXCUSE_RE.search(last["comment"]):
        tags.append("excuse_last")
    m = last.get("margin")
    if last.get("pos") and last["pos"] > 1 and m is not None and abs(m) <= 1.0:
        tags.append("close_last")
    if distance and last.get("dist"):
        if distance - last["dist"] >= 200:
            tags.append("up_trip")
        if last["dist"] - distance >= 200:
            tags.append("down_trip")
    return tags


def class_move(par_today, par_last, threshold=1.5):
    """'up' / 'down' / None from the winning par of today's class vs last start's."""
    if par_today is None or par_last is None:
        return None, None
    d = par_today - par_last
    return ("up" if d >= threshold else "down" if d <= -threshold else None), round(d, 1)


def is_fade(p, p_market, price, fades_proven):
    return bool(fades_proven and p and p_market and price and p <= p_market / FADE_RATIO
                and FADE_BAND[0] <= price <= FADE_BAND[1])


def play_check(r):
    """r: p, p_market, price, fair, map_zone, map_tag, form_rank, form_conf, going, tags, fade.
    Returns (is_play, reasons, misses)."""
    reasons, misses = [], []

    def need(ok, yes, no):
        (reasons if ok else misses).append(yes if ok else no)

    p, price, fair = r.get("p") or 0, r.get("price") or 0, r.get("fair") or 0
    need(p >= PLAY_MIN_CHANCE, "our chance {:.0f}%".format(p * 100), "chance under {:.0f}%".format(PLAY_MIN_CHANCE * 100))
    need(price >= PLAY_MIN_PRICE, "price ${:.2f}".format(price), "price under ${:.2f}".format(PLAY_MIN_PRICE))
    need(bool(fair) and price >= fair, "price at or above ours (${:.2f})".format(fair), "price shorter than ours")
    need(not r.get("fade"), "not a fade", "model fade")
    need(r.get("map_zone") in GOOD_ZONES and r.get("map_tag") not in BAD_TAGS,
         "maps well ({})".format(r.get("map_zone")), "map against it")
    fr = r.get("form_rank")
    need(fr is not None and fr <= 2 and r.get("form_conf") != "Low", "top-2 form in the race", "form not top-2 or thin")
    need(r.get("going") != "poor", "going {}".format(r.get("going") or "ok"), "poor on the going")
    tags = r.get("tags") or []
    need("excuse_last" not in tags and "down_trip" not in tags, "no fade angle", "carries a fade angle")
    return (not misses), reasons, misses
