"""Jockey silks & saddlecloth visual identity for The Edge (Phase 8).

Generates a colour-coded jersey per horse as a VISUAL MARKER only - these are not
the horse's registered racing colours (the feed has no silks). Saddlecloth numbers
and jockeys are the real ones from the Form King card. If a real silk image URL is
later stored in race_entries.silk_url it takes precedence.
"""

import base64
import hashlib

# Bright, high-contrast racing-silk palette.
PALETTE = ["#e11d48", "#2563eb", "#059669", "#f59e0b", "#7c3aed", "#0ea5e9",
           "#111827", "#e5e7eb", "#db2777", "#15803d", "#ea580c", "#facc15"]
PATTERNS = ["solid", "halves", "stripes", "hoops", "sash", "quarters", "spots", "chevron"]

_JOCKEY_CACHE = {}


def _rng_int(key):
    return int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)


def silk_spec(horse_name):
    """Deterministic silk colour/pattern spec for a horse."""
    h = _rng_int("silk:" + horse_name)
    body = PALETTE[h % len(PALETTE)]
    sec = PALETTE[(h // 7) % len(PALETTE)]
    if sec == body:
        sec = PALETTE[(h // 7 + 3) % len(PALETTE)]
    sleeves = PALETTE[(h // 13) % len(PALETTE)]
    cap = PALETTE[(h // 17) % len(PALETTE)]
    pattern = PATTERNS[(h // 23) % len(PATTERNS)]
    return {"body": body, "secondary": sec, "sleeves": sleeves, "cap": cap, "pattern": pattern}


def jockey_for(horse_name):
    """The horse's REAL jockey from its latest Form King card entry ("-" if unknown)."""
    if horse_name in _JOCKEY_CACHE:
        return _JOCKEY_CACHE[horse_name]
    jockey = "-"
    try:
        import json
        from database import get_connection
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT fk_json FROM race_entries WHERE horse_name = ? AND fk_json IS NOT NULL "
                "ORDER BY entry_id DESC LIMIT 1", (horse_name,)).fetchone()
        finally:
            conn.close()
        if row and row["fk_json"]:
            jockey = json.loads(row["fk_json"]).get("jockey") or "-"
    except Exception:
        jockey = "-"
    _JOCKEY_CACHE[horse_name] = jockey
    return jockey


def clear_jockey_cache():
    """Forget cached jockeys (call after a card rebuild: riders change)."""
    _JOCKEY_CACHE.clear()


def primary_color(horse_name):
    return silk_spec(horse_name)["body"]


# Torso geometry (viewBox 100x100).
_TX, _TY, _TW, _TH = 34, 22, 32, 60


def _pattern_svg(spec):
    body, sec, pat = spec["body"], spec["secondary"], spec["pattern"]
    x, y, w, h = _TX, _TY, _TW, _TH
    base = '<rect x="{}" y="{}" width="{}" height="{}" rx="4" fill="{}"/>'.format(x, y, w, h, body)
    extra = ""
    if pat == "halves":
        extra = '<rect x="{}" y="{}" width="{}" height="{}" fill="{}"/>'.format(x + w / 2, y, w / 2, h, sec)
    elif pat == "stripes":
        for i in range(0, w, 8):
            extra += '<rect x="{}" y="{}" width="4" height="{}" fill="{}"/>'.format(x + i, y, h, sec)
    elif pat == "hoops":
        for i in range(0, h, 10):
            extra += '<rect x="{}" y="{}" width="{}" height="5" fill="{}"/>'.format(x, y + i, w, sec)
    elif pat == "sash":
        extra = '<polygon points="{},{} {},{} {},{} {},{}" fill="{}"/>'.format(
            x, y + h - 10, x + 10, y + h, x + w, y + 10, x + w - 10, y, sec)
    elif pat == "quarters":
        extra = ('<rect x="{}" y="{}" width="{}" height="{}" fill="{}"/>'.format(x, y, w / 2, h / 2, sec)
                 + '<rect x="{}" y="{}" width="{}" height="{}" fill="{}"/>'.format(x + w / 2, y + h / 2, w / 2, h / 2, sec))
    elif pat == "spots":
        for cx, cy in [(x + 10, y + 14), (x + 22, y + 26), (x + 12, y + 40), (x + 24, y + 50)]:
            extra += '<circle cx="{}" cy="{}" r="3.5" fill="{}"/>'.format(cx, cy, sec)
    elif pat == "chevron":
        for i in range(0, h, 14):
            extra += '<polyline points="{},{} {},{} {},{}" fill="none" stroke="{}" stroke-width="4"/>'.format(
                x, y + i + 10, x + w / 2, y + i, x + w, y + i + 10, sec)
    return ('<clipPath id="t"><rect x="{}" y="{}" width="{}" height="{}" rx="4"/></clipPath>'.format(x, y, w, h)
            + '<g clip-path="url(#t)">' + base + extra + "</g>")


def build_silk_svg(spec, size=44):
    """Return an SVG string of a racing-silk jersey."""
    sleeves, cap = spec["sleeves"], spec["cap"]
    left = '<polygon points="34,24 19,33 25,53 36,46" fill="{}" stroke="#0b1220" stroke-width="1"/>'.format(sleeves)
    right = '<polygon points="66,24 81,33 75,53 64,46" fill="{}" stroke="#0b1220" stroke-width="1"/>'.format(sleeves)
    torso = _pattern_svg(spec)
    outline = ('<rect x="{}" y="{}" width="{}" height="{}" rx="4" fill="none" '
               'stroke="#0b1220" stroke-width="1.5"/>'.format(_TX, _TY, _TW, _TH))
    collar = '<polygon points="44,22 56,22 50,31" fill="#0b1220"/>'
    capc = '<circle cx="50" cy="12" r="7" fill="{}" stroke="#0b1220" stroke-width="1"/>'.format(cap)
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 100 100">'
            '{left}{right}{torso}{outline}{collar}{cap}</svg>').format(
        s=size, left=left, right=right, torso=torso, outline=outline, collar=collar, cap=capc)


def data_uri(svg):
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return "data:image/svg+xml;base64," + b64


def silk_data_uri(horse_name, size=44):
    """Convenience: generate a silk data URI straight from a horse name."""
    return data_uri(build_silk_svg(silk_spec(horse_name), size))


def assign_saddlecloths_and_silks(conn):
    """Cache marker-jersey SVGs per runner. Saddlecloth numbers are the REAL ones
    from the card; only a runner the feed gave no number gets one by weight order
    (topweight first) after the numbered runners."""
    clear_jockey_cache()
    for race in conn.execute("SELECT race_id FROM races").fetchall():
        ents = conn.execute(
            "SELECT entry_id, horse_name, weight, saddlecloth FROM race_entries WHERE race_id=?",
            (race["race_id"],)).fetchall()
        used = {e["saddlecloth"] for e in ents if e["saddlecloth"]}
        nxt = max(used) + 1 if used else 1
        for e in sorted(ents, key=lambda e: (-e["weight"], e["horse_name"])):
            num = e["saddlecloth"]
            if not num:
                num, nxt = nxt, nxt + 1
            svg = build_silk_svg(silk_spec(e["horse_name"]))
            conn.execute("UPDATE race_entries SET saddlecloth=?, silk_svg=?, silk_url=? WHERE entry_id=?",
                         (num, svg, "", e["entry_id"]))
    conn.commit()


def get_runner_silk(entry_id, conn=None):
    """Return the silk as a data URI for a runner (cached SVG, URL, or generated)."""
    own = conn is None
    if own:
        from database import get_connection
        conn = get_connection()
    try:
        row = conn.execute(
            "SELECT horse_name, silk_url, silk_svg FROM race_entries WHERE entry_id=?",
            (entry_id,)).fetchone()
        if row is None:
            return None
        if row["silk_url"]:
            return row["silk_url"]
        if row["silk_svg"]:
            return data_uri(row["silk_svg"])
        return silk_data_uri(row["horse_name"])
    finally:
        if own:
            conn.close()


if __name__ == "__main__":
    print(silk_data_uri("Northern Echo")[:60], "...")
    print("jockey:", jockey_for("Northern Echo"), "primary:", primary_color("Northern Echo"))
