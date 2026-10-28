"""Mock data generator for the Punting Intelligence Engine (PIE).

Phase 1: produces a realistic Saturday meeting at Flemington with two races.
No outbound API calls (see CLAUDE.md) - everything here is synthesised locally.

The generator returns plain Python dictionaries so that ingest.py can insert
them without re-deriving any structure. Only the fields that are known at
Phase 1 are populated; Phase 2+ model fields (speed_rating, score_0_to_100,
fair_odds, and the whole bets_ledger) are intentionally left out / NULL.

Market pricing (Phase 2 refinement): market_odds form a *coherent* betting
book rather than independent random prices. Each runner's market price is
derived from its underlying ability (via the rating engine) plus market noise,
then an overround margin is applied so the implied book sums to ~OVERROUND
(e.g. 118%). The market deliberately does NOT see the prep-peak signal that the
model uses - that gap is the source of the value edges PIE is built to find.
"""

import datetime
import math
import random

from rating_engine import calculate_0_to_100_score

# Deterministic output so repeated runs during development are reproducible.
SEED = 2026

# Softmax temperature used to turn perceived ability into market probabilities.
# Kept in step with the pricing engine so the market lives on the same scale as
# the model's fair book.
from pricing_engine import TEMPERATURE

# Book overround: total implied probability of the market (1.18 = 118% book,
# a typical competitive race margin). Spread of individual noise below.
OVERROUND = 1.18
MARKET_NOISE_SD = 3.5  # points of perceived-score noise per runner

# Believable price bounds for the mock market.
MIN_ODDS = 1.20
MAX_ODDS = 101.0

HORSE_NAMES = [
    "Gallant Spur", "Midnight Tempo", "Velvet Thunder", "Harbour Lights",
    "Crimson Reign", "Northern Echo", "Silver Falcon", "Desert Mirage",
    "Lucky Cadence", "Iron Resolve", "Coastal Breeze", "Golden Verdict",
    "Shadow Dancer", "Rapid Ascent", "Bold Horizon", "Winter Solstice",
    "Emerald Isle", "Stellar Drift", "Phantom Quill", "Riviera Gold",
]

# A larger deterministic name pool (adjective x noun) so each meeting gets a
# distinct field with no cross-meeting horse-name collisions. The curated
# HORSE_NAMES above are used first so the Flemington card stays familiar.
_ADJ = ["Royal", "Mystic", "Savage", "Electric", "Noble", "Wild", "Secret",
        "Diamond", "Atlantic", "Scarlet", "Thunder", "Blazing", "Regal",
        "Arctic", "Sapphire", "Gilded", "Obsidian", "Crimson", "Lunar", "Rogue"]
_NOUN = ["Storm", "Blaze", "Arrow", "Empire", "Saint", "Comet", "Legend",
         "Whisper", "Crown", "Vortex", "Monarch", "Tide", "Phoenix", "Oracle",
         "Rebel", "Nomad", "Spirit", "Baron", "Flyer", "Knight"]

# Several mock meetings spread across dates relative to "today" (day_offset:
# negative = past/completed, 0 = today, positive = upcoming/early market).
# Flemington stays first (and keeps its two races) so Phase-2/3 audits that key
# off race_id 1 & 2 hold.
MEETING_SPECS = [
    {"track_id": "FLE", "track_name": "Flemington", "rail_position": "True",
     "condition": "Good 4", "day_offset": -1,
     "races": [(1, 1200, "Maiden Plate", 8, (30, 55)),
               (2, 1600, "Open Benchmark 84", 10, (60, 85))]},
    {"track_id": "CAU", "track_name": "Caulfield", "rail_position": "True",
     "condition": "Good 4", "day_offset": -6,
     "races": [(1, 1100, "Benchmark 78", 9, (60, 82)),
               (2, 2400, "Group 1 Cup", 10, (78, 95))]},
    {"track_id": "ROS", "track_name": "Rosehill", "rail_position": "+3m",
     "condition": "Soft 5", "day_offset": 0,
     "races": [(1, 1100, "Benchmark 70", 9, (45, 68)),
               (2, 1400, "Group 3 Sprint", 9, (70, 90)),
               (3, 2000, "Benchmark 78", 10, (55, 80))]},
    {"track_id": "EFM", "track_name": "Eagle Farm", "rail_position": "True",
     "condition": "Good 3", "day_offset": 0,
     "races": [(1, 1000, "Class 1 Handicap", 8, (35, 58)),
               (2, 1200, "Open Handicap", 9, (60, 82))]},
    {"track_id": "MVR", "track_name": "Moonee Valley", "rail_position": "+6m",
     "condition": "Heavy 8", "day_offset": 1,
     "races": [(1, 1500, "Benchmark 64", 9, (40, 62)),
               (2, 2040, "Group 2 Cup", 10, (72, 92))]},
    {"track_id": "RAN", "track_name": "Randwick", "rail_position": "+2m",
     "condition": "Good 4", "day_offset": 2,
     "races": [(1, 1300, "Benchmark 88", 10, (66, 88)),
               (2, 1600, "Group 1 Mile", 10, (80, 96))]},
]


def _assign_barriers(n):
    """Return a shuffled list of barriers 1..n (each runner gets a unique gate)."""
    barriers = list(range(1, n + 1))
    random.shuffle(barriers)
    return barriers


def _build_runners(names, n):
    """Create n runner dicts drawn from the supplied name pool.

    barrier, weight (54.0-60.5 kg) and prep_run_num (1-5) follow the Phase 1
    spec; wfa_rating comes from the caller's tier range. market_odds is NOT set
    here - it is assigned per race by _assign_market_book once the whole field
    exists, so the prices form a coherent book.
    """
    chosen = names[:n]
    barriers = _assign_barriers(n)

    runners = []
    for i, horse_name in enumerate(chosen):
        runners.append({
            "horse_name": horse_name,
            "barrier": barriers[i],
            "weight": round(random.uniform(54.0, 60.5), 1),
            "prep_run_num": random.randint(1, 5),
        })
    return runners


def _assign_wfa_ratings(runners, wfa_low, wfa_high):
    """Draw each runner's wfa_rating from the tier-specific range."""
    for r in runners:
        r["wfa_rating"] = round(random.uniform(wfa_low, wfa_high), 1)
    return runners


def _assign_market_book(race):
    """Price the field into a coherent overround book and set each market_odds.

    Perceived ability = base rating score + Gaussian market noise (the market
    does not model the prep peak). These are softmaxed to fair perception
    probabilities, scaled up by OVERROUND, and inverted to prices.
    """
    entries = race["entries"]

    base_scores = [
        calculate_0_to_100_score(
            e["wfa_rating"], e["weight"], race["distance"], race["class_name"])
        for e in entries
    ]
    perceived = [s + random.gauss(0.0, MARKET_NOISE_SD) for s in base_scores]

    # Softmax perceived ability into probabilities (stable: subtract the max).
    top = max(perceived)
    exps = [math.exp((s - top) / TEMPERATURE) for s in perceived]
    total = sum(exps)
    fair_probs = [e / total for e in exps]

    for entry, p in zip(entries, fair_probs):
        market_prob = p * OVERROUND
        odds = 1.0 / market_prob
        entry["market_odds"] = round(max(MIN_ODDS, min(MAX_ODDS, odds)), 2)

    return race


def _name_pool():
    """Deterministic, de-duplicated name pool: curated names first, then combos."""
    seen, pool = set(), []
    for n in HORSE_NAMES:
        if n not in seen:
            pool.append(n); seen.add(n)
    for a in _ADJ:
        for b in _NOUN:
            nm = "{} {}".format(a, b)
            if nm not in seen:
                pool.append(nm); seen.add(nm)
    return pool


def _build_meeting(spec, names):
    """Build one meeting dict ({meeting, races}) from a spec and a name slice."""
    mdate = (datetime.date.today() + datetime.timedelta(days=spec.get("day_offset", 0))).isoformat()
    meeting = {
        "track_id": spec["track_id"], "track_name": spec["track_name"],
        "rail_position": spec["rail_position"], "condition": spec["condition"],
        "track_variant": 0.0, "meeting_date": mdate,
    }
    races, idx = [], 0
    for (rno, dist, cls, n, (wlo, whi)) in spec["races"]:
        runners = _assign_wfa_ratings(_build_runners(names[idx:idx + n], n), wlo, whi)
        idx += n
        race = {
            "race_number": rno, "distance": dist, "class_name": cls,
            "pace_pressure_index": round(random.uniform(0.8, 1.2), 2),
            "entries": runners,
        }
        _assign_market_book(race)
        races.append(race)
    return {"meeting": meeting, "races": races}


def generate_meetings():
    """Generate every mock meeting (Flemington first). Returns a list of
    {"meeting": {...}, "races": [...]} dicts, each with a distinct field."""
    random.seed(SEED)
    pool = _name_pool()
    out, cursor = [], 0
    for spec in MEETING_SPECS:
        need = sum(r[3] for r in spec["races"])
        out.append(_build_meeting(spec, pool[cursor:cursor + need]))
        cursor += need
    return out


def generate_meeting():
    """Backwards-compatible single meeting (the first one: Flemington)."""
    return generate_meetings()[0]


if __name__ == "__main__":
    for data in generate_meetings():
        print(f"Generated meeting at {data['meeting']['track_name']} "
              f"with {len(data['races'])} races.")
        for race in data["races"]:
            book = sum(1.0 / e["market_odds"] for e in race["entries"])
            print(f"  Race {race['race_number']}: {race['distance']}m "
                  f"{race['class_name']} - {len(race['entries'])} runners, "
                  f"market book = {book * 100:.1f}%")
