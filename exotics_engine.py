"""Exotics & derivative pricing for The Edge (Phase 7).

Takes the normalised 100% win-probability vector and derives fair prices for
Exactas, Quinellas and Trifectas using the Harville model (with an optional
Henery refinement), then compares to simulated TAB tote dividends to surface
high-yield exotic overlays. Mock data only (see CLAUDE.md).
"""

import itertools
import random

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


def top_exotics(probs, names, seed=7, min_edge=0.25, overround=1.25, top=5):
    """Return (exacta_overlays, trifecta_overlays) with Edge >= min_edge.

    Each combo: type, combo (names), fair dividend, simulated tote dividend, edge.
    """
    rng = random.Random(seed)
    ids = list(probs)

    exactas = []
    for i, j in itertools.permutations(ids, 2):
        p = harville_exacta(probs, i, j)
        if p <= 1e-7:
            continue
        fd = 1.0 / p
        tote = round(max(1.5, fd * overround * rng.uniform(0.70, 1.55)), 2)
        exactas.append({"type": "Exacta", "combo": [names[i], names[j]],
                        "prob": p, "fair": round(fd, 2), "tote": tote, "edge": tote / fd - 1.0})

    trifectas = []
    for i, j, k in itertools.permutations(ids, 3):
        p = harville_trifecta(probs, i, j, k)
        if p <= 1e-6:
            continue
        fd = 1.0 / p
        tote = round(max(2.0, fd * overround * rng.uniform(0.65, 1.7)), 2)
        trifectas.append({"type": "Trifecta", "combo": [names[i], names[j], names[k]],
                          "prob": p, "fair": round(fd, 2), "tote": tote, "edge": tote / fd - 1.0})

    ex = sorted([e for e in exactas if e["edge"] >= min_edge], key=lambda x: -x["edge"])[:top]
    tri = sorted([t for t in trifectas if t["edge"] >= min_edge], key=lambda x: -x["edge"])[:top]
    return ex, tri


if __name__ == "__main__":
    pr = {1: 0.4, 2: 0.3, 3: 0.2, 4: 0.1}
    nm = {1: "A", 2: "B", 3: "C", 4: "D"}
    print("sums:", exotic_prob_sums(pr))
    ex, tri = top_exotics(pr, nm)
    print("exacta overlays:", len(ex), "trifecta overlays:", len(tri))
