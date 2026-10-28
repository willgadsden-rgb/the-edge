"""Scratching engine for PIE - Phase 3.

Marks a runner as scratched and dynamically re-normalises the remaining field
back to a 100% fair book, then refreshes fair odds and value edges. Mock data
only (see CLAUDE.md). The re-normalisation math lives in pricing_engine so there
is a single source of truth:  P_new(i) = P_old(i) / (1 - Sum(P_scratched)).
"""

from database import get_connection, ensure_schema
from pricing_engine import renormalize_after_scratching


def scratch_runner(race_id, horse_name, conn=None):
    """Scratch horse_name from race_id and re-price the remaining field.

    Returns a dict:
        scratched        - {horse_name, removed_prob}
        runners          - list of remaining runners with old/new fair odds,
                           market odds and refreshed edge (sorted by new fair)
    Raises ValueError if the horse is not found / already scratched, or if the
    field has not been priced yet.
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()

    try:
        ensure_schema(conn)

        # The currently-active runners (including the target) form a book that
        # sums to 1.0; capture them before marking the scratching.
        active = conn.execute(
            """
            SELECT entry_id, horse_name, fair_odds, market_odds
            FROM race_entries
            WHERE race_id = ? AND scratched = 0
            ORDER BY entry_id
            """,
            (race_id,),
        ).fetchall()

        target = next((r for r in active if r["horse_name"] == horse_name), None)
        if target is None:
            raise ValueError(
                "{} is not an active runner in race {}".format(horse_name, race_id))
        if any(r["fair_odds"] is None for r in active):
            raise ValueError("Race {} has not been priced yet.".format(race_id))

        # Old probabilities from the current fair book.
        prob_by_entry = {r["entry_id"]: 1.0 / r["fair_odds"] for r in active}
        removed_prob = prob_by_entry[target["entry_id"]]

        # Mark the scratching and drop its fair price.
        conn.execute(
            "UPDATE race_entries SET scratched = 1, fair_odds = NULL WHERE entry_id = ?",
            (target["entry_id"],),
        )

        # Re-normalise the survivors and write back refreshed fair odds.
        new_probs = renormalize_after_scratching(prob_by_entry, [target["entry_id"]])

        runners = []
        for r in active:
            if r["entry_id"] == target["entry_id"]:
                continue
            p_new = new_probs[r["entry_id"]]
            new_fair = round(1.0 / p_new, 2)
            conn.execute(
                "UPDATE race_entries SET fair_odds = ? WHERE entry_id = ?",
                (new_fair, r["entry_id"]),
            )
            edge = (r["market_odds"] / new_fair) - 1.0 if r["market_odds"] else None
            runners.append({
                "horse_name": r["horse_name"],
                "old_fair_odds": round(r["fair_odds"], 2),
                "new_fair_odds": new_fair,
                "market_odds": r["market_odds"],
                "edge": edge,
            })

        conn.commit()
        runners.sort(key=lambda x: x["new_fair_odds"])
        return {
            "scratched": {"horse_name": horse_name, "removed_prob": removed_prob},
            "runners": runners,
        }
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    import sys
    rid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    name = sys.argv[2] if len(sys.argv) > 2 else None
    if name:
        out = scratch_runner(rid, name)
        print("Scratched {} (removed {:.1%} of the book)".format(
            out["scratched"]["horse_name"], out["scratched"]["removed_prob"]))
        for r in out["runners"]:
            print("  {:<18} ${:>6} -> ${:>6}  edge {:+.1%}".format(
                r["horse_name"], r["old_fair_odds"], r["new_fair_odds"], r["edge"]))
