"""Exotics & derivative pricing for The Edge (Phase 7).

Takes the normalised 100% win-probability vector and derives fair prices for
Exactas, Quinellas and Trifectas using the Harville model (with an optional
Henery refinement), for the analyst to compare against the live tote. Nothing is simulated.
"""

import itertools

HENERY_L2 = 0.81
HENERY_L3 = 0.65


def harville_exacta(probs, i, j):
    pi = probs[i]
    d = 1.0 - pi
    return pi * probs[j] / d if d > 1e-9 else 0.0


def harville_quinella(probs, i, j):
    return harville_exacta(probs, i, j) + harville_exacta(probs, j, i)


def harville_trifecta(probs, i, j, k):
    pi, pj = probs[i], probs[j]
    d1, d2 = 1.0 - pi, 1.0 - pi - pj
    if d1 <= 1e-9 or d2 <= 1e-9:
        return 0.0
    return pi * (probs[j] / d1) * (probs[k] / d2)


def henery_trifecta(probs, i, j, k):
    """Henery refinement: discounts the favourite's dominance for 2nd/3rd."""
    pi = probs[i]
    others = [x for x in probs if x != i]
    den2 = sum(probs[x] ** HENERY_L2 for x in others)
    if den2 <= 1e-12:
        return 0.0
    p2 = probs[j] ** HENERY_L2 / den2
    others3 = [x for x in others if x != j]
    den3 = sum(probs[x] ** HENERY_L3 for x in others3)
    if den3 <= 1e-12:
        return 0.0
    p3 = probs[k] ** HENERY_L3 / den3
    return pi * p2 * p3


def fair_dividend(prob):
    """Fair dividend to a $1 unit = 1 / probability."""
    return round(1.0 / prob, 2) if prob > 1e-9 else None


def exotic_prob_sums(probs):
    """Total Harville probability over all exacta / trifecta orderings (each ~1.0)."""
    ids = list(probs)
    ex = sum(harville_exacta(probs, i, j) for i, j in itertools.permutations(ids, 2))
    tri = sum(harville_trifecta(probs, i, j, k) for i, j, k in itertools.permutations(ids, 3))
    return ex, tri


def fair_exotics(probs, names, top=5):
    """Most likely exactas and trifectas with their fair (100%) dividends.

    No tote comparison: the Form King feed carries no tote pools, so value is
    judged by the analyst against the live tote.
    """
    ids = list(probs)
    ex = sorted(((harville_exacta(probs, i, j), (i, j))
                 for i, j in itertools.permutations(ids, 2)), reverse=True)[:top]
    tri = sorted(((harville_trifecta(probs, i, j, k), (i, j, k))
                  for i, j, k in itertools.permutations(ids, 3)), reverse=True)[:top]
    fmt = lambda p, c: {"combo": [names[x] for x in c], "fair": round(1.0 / p, 2) if p > 0 else None}
    return [fmt(p, c) for p, c in ex], [fmt(p, c) for p, c in tri]


if __name__ == "__main__":
    pr = {1: 0.4, 2: 0.3, 3: 0.2, 4: 0.1}
    nm = {1: "A", 2: "B", 3: "C", 4: "D"}
    print("sums:", exotic_prob_sums(pr))
    ex, tri = fair_exotics(pr, nm)
    print("top exacta:", ex[0], "top trifecta:", tri[0])
