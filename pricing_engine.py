"""Pricing engine for PIE - Phase 2.

Converts adjusted 0-100 scores into a strict 100% fair market via a
temperature-scaled softmax, writes fair_odds back to race_entries, and computes
the value edge against market_odds. Mock data only (see CLAUDE.md).

Pricing rules (CLAUDE.md):
    Sum(P_i) = 1.0 ;  Fair Price = 1 / P_i
    Dynamic scratching: P_new = P_old / (1 - Sum(P_scratched))
"""

import math

from database import get_connection

# Temperature for the softmax. Calibrated for racing: a larger T flattens the
# market so even clearly superior horses are beatable. ~12 maps a top-to-bottom
# score gap of ~35 points to roughly a 25x win-probability ratio.
TEMPERATURE = 12.0

# Minimum value edge to flag a runner as a positive-EV overlay.
OVERLAY_EDGE = 0.20


def _softmax(scores, temperature=TEMPERATURE):
    """Temperature-scaled softmax that sums to exactly 1.0 (float tolerance)."""
    if not scores:
        return []
    # Subtract the max for numerical stability before exponentiating.
    top = max(scores)
    exps = [math.exp((s - top) / temperature) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]


# Net-of-commission pricing. Betting-exchange / tote commission reduces the real
# payout, so value must be judged on the price you actually keep.
DEFAULT_COMMISSION = 0.08       # 8% default
NSW_COMMISSION = 0.10           # 10% for NSW races


def effective_odds(market_odds, commission_rate=DEFAULT_COMMISSION):
    """Odds net of commission: 1 + (odds - 1) * (1 - commission)."""
    return round(1.0 + (market_odds - 1.0) * (1.0 - commission_rate), 2)


def commission_for_state(state):
    """Commission rate for a race's state (NSW is higher)."""
    return NSW_COMMISSION if (state or "").strip().upper() in ("NSW", "NEW SOUTH WALES") else DEFAULT_COMMISSION


def fair_book_from_scores(score_by_entry, temperature=TEMPERATURE):
    """Build a strict 100% fair book from a map of entry_id -> projected score.

    The softmax guarantees Sum(P_i) = 1.0, so whenever projected scores change
    (situational angles, manual overrides) or runners are removed (scratchings),
    re-calling this re-normalises the remaining field to exactly 100%.
    Returns {entry_id: probability}; fair odds are 1 / probability.
    """
    ids = list(score_by_entry)
    if not ids:
        return {}
    probs = _softmax([score_by_entry[i] for i in ids], temperature)
    total = sum(probs)
    assert abs(total - 1.0) < 1e-9, "fair book does not sum to 1.0: {}".format(total)
    return {i: p for i, p in zip(ids, probs)}


def devig_market_odds(runners):
    """De-vig the market: normalise market implied probabilities to sum 1.0.

    runners: iterable of dicts with 'id' and 'market_odds' (optional 'scratched').
    Scratched runners and invalid/zero/<=1 odds are dropped. Returns
    {id: p_market} where p_raw = 1/price and p_market = p_raw / sum(p_raw), so
    the bookmaker's overround is removed and the field sums to exactly 1.0.
    """
    raw = [(r["id"], 1.0 / r["market_odds"]) for r in runners
           if not r.get("scratched") and r.get("market_odds") and r["market_odds"] > 1.0]
    total = sum(p for _, p in raw)
    if total <= 0:
        return {}
    return {i: p / total for i, p in raw}


def calculate_blended_fair_prices(runners, market_weight=0.70):
    """Bayesian market shrinkage: blend the model's book with the de-vigged
    market so model prices are anchored to live consensus (kills phantom overlays).

    runners: dicts with 'id', 'score' (0-100 projected) and 'market_odds'
    (optional 'scratched', and 'effective_odds' to also get edge_pct).

        p_model   = softmax(scores)            -> sums to 1
        p_market  = devig_market_odds(...)      -> sums to 1
        p_blended = w*p_market + (1-w)*p_model  -> renormalised to 1
        my_price  = 1 / p_blended
        edge_pct  = (effective_odds / my_price - 1) * 100

    With no market odds in the field the weight collapses to 0 (pure model).
    Returns {id: {my_price, p_blended, p_model, p_market, edge_pct?}}.
    """
    active = [r for r in runners if not r.get("scratched")]
    if not active:
        return {}
    ids = [r["id"] for r in active]
    p_model = dict(zip(ids, _softmax([r["score"] for r in active])))
    p_market = devig_market_odds(active)
    w = market_weight if p_market else 0.0   # no market -> pure model

    blended = {}
    for i in ids:
        pm = p_market.get(i)
        blended[i] = p_model[i] if pm is None else (w * pm + (1.0 - w) * p_model[i])
    total = sum(blended.values()) or 1.0

    out = {}
    for r in active:
        i = r["id"]
        pb = blended[i] / total
        my_price = round(1.0 / pb, 2) if pb > 0 else None
        res = {"my_price": my_price, "p_blended": pb,
               "p_model": p_model[i], "p_market": p_market.get(i)}
        eff = r.get("effective_odds")
        if eff and my_price:
            res["edge_pct"] = (eff / my_price - 1.0) * 100.0
        out[i] = res
    return out


def renormalize_after_scratching(prob_by_entry, scratched_entry_ids):
    """Re-normalise a fair book after scratchings: P_new = P_old / (1 - Sum(scratched)).

    prob_by_entry maps entry_id -> probability; returns a new map for the
    remaining runners whose probabilities again sum to 1.0.
    """
    scratched = set(scratched_entry_ids)
    removed_mass = sum(p for eid, p in prob_by_entry.items() if eid in scratched)
    if removed_mass >= 1.0:
        raise ValueError("Cannot re-normalise: scratched probability mass >= 1.0")

    denom = 1.0 - removed_mass
    return {
        eid: p / denom
        for eid, p in prob_by_entry.items()
        if eid not in scratched
    }


def _value_flag(edge):
    """Human-readable value tag from a decimal edge (e.g. 0.35 -> overlay)."""
    if edge >= OVERLAY_EDGE:
        return "overlay"      # positive EV
    if edge >= 0.0:
        return "fair"
    return "underlay"


def price_race(race_id, conn=None):
    """Price every runner in race_id from its stored score_0_to_100.

    Writes fair_odds back to race_entries and returns a list of per-runner
    result dicts sorted by fair_odds (shortest price / best chance first).
    Requires score_0_to_100 to already be populated for the race.
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT entry_id, horse_name, score_0_to_100, market_odds
            FROM race_entries
            WHERE race_id = ?
            ORDER BY entry_id
            """,
            (race_id,),
        ).fetchall()

        if not rows:
            return []

        missing = [r["horse_name"] for r in rows if r["score_0_to_100"] is None]
        if missing:
            raise ValueError(
                "score_0_to_100 not set for: {} (run the rating engine first)"
                .format(", ".join(missing))
            )

        scores = [r["score_0_to_100"] for r in rows]
        probs = _softmax(scores)

        # Strict 100% normalisation guarantee.
        total_p = sum(probs)
        assert abs(total_p - 1.0) < 1e-9, "fair book does not sum to 1.0: {}".format(total_p)

        results = []
        for row, prob in zip(rows, probs):
            fair_odds = round(1.0 / prob, 2)
            market_odds = row["market_odds"]
            edge = (market_odds / fair_odds) - 1.0 if market_odds else None

            conn.execute(
                "UPDATE race_entries SET fair_odds = ? WHERE entry_id = ?",
                (fair_odds, row["entry_id"]),
            )

            results.append({
                "entry_id": row["entry_id"],
                "horse_name": row["horse_name"],
                "score_0_to_100": row["score_0_to_100"],
                "probability": prob,
                "fair_odds": fair_odds,
                "market_odds": market_odds,
                "edge": edge,
                "flag": _value_flag(edge) if edge is not None else "n/a",
            })

        conn.commit()
        results.sort(key=lambda r: r["fair_odds"])
        return results
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    import sys
    rid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    for r in price_race(rid):
        print("{:<18} score={:<5} fair=${:<6} market=${:<6} edge={:+.1%} {}".format(
            r["horse_name"], r["score_0_to_100"], r["fair_odds"],
            r["market_odds"], r["edge"], r["flag"]))
