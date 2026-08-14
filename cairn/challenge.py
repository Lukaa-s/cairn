"""The write gate.

MCP carries no model identity, so gating on "are you Opus 5" is not something the
protocol can answer -- see identity.py for what it *can* answer. What a server can
do is refuse to take dictation from something that cannot do the work, and that is
a better gate anyway: it admits a capable client we have never heard of and turns
away a famous one that is guessing.

The challenges are mirror-symmetric integer polygons, which is not decoration. A
random point set has no exact coincidences at all, so a coincidence-counting task
over one is degenerate -- the answer is always zero. Symmetry plants exact
equalities, which makes the count non-trivial *and* makes it punish the specific
error the erdos982 journal records over and over: comparing distances that are
equal as integers after they have been through floating point, or recomputing them
from the circle the polygon came from instead of the coordinates as given. A
contributor careless about that here will be careless about it in the ledger.

Parameters come from a per-session seed, so the space is far too large to memorise
and every session gets a fresh instance.
"""

from __future__ import annotations

import hashlib
import math
import random
from fractions import Fraction

MAX_ATTEMPTS = 3


# --------------------------------------------------------------- geometry

def _strictly_convex_ccw(pts: list[tuple[int, int]]) -> bool:
    n = len(pts)
    if len({p for p in pts}) != n or n < 4:
        return False
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        cx, cy = pts[(i + 2) % n]
        if (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) <= 0:
            return False
    return True


def _mirror_polygon(rng: random.Random, half: int, radius: int, poles: int) -> list[tuple[int, int]]:
    """Integer points in strictly convex position, exactly symmetric about x = 0.

    Built by rounding right-half-plane circle points to integers and mirroring the
    *rounded* integers, so the symmetry is exact in Z^2 rather than approximate.
    """
    for _ in range(400):
        angles = sorted(rng.uniform(-1.30, 1.30) for _ in range(half))
        if min((angles[i + 1] - angles[i]) for i in range(half - 1)) < 0.22:
            continue
        right = []
        for a in angles:
            x, y = round(radius * math.cos(a)), round(radius * math.sin(a))
            if x <= 0:
                break
            right.append((x, y))
        if len(right) != half or len({y for _, y in right}) != half:
            continue
        pts = right + [(-x, y) for x, y in right]
        if poles >= 1:
            pts.append((0, radius))
        if poles >= 2:
            pts.append((0, -radius))
        pts.sort(key=lambda p: math.atan2(p[1], p[0]))
        if _strictly_convex_ccw(pts):
            return pts
    raise RuntimeError("could not build a symmetric convex polygon")


def _sqdists_from(pts: list[tuple[int, int]], i: int) -> list[int]:
    xi, yi = pts[i]
    return [(xi - x) ** 2 + (yi - y) ** 2 for j, (x, y) in enumerate(pts) if j != i]


_TRAP = (
    "Attention : les coordonnées entières ci-dessus font foi. Ne recalcule pas les\n"
    "sommets depuis un cercle et ne compare pas des distances en virgule flottante —\n"
    "l'égalité demandée est l'égalité EXACTE des entiers. Ce polygone est symétrique,\n"
    "donc il y a de vraies égalités à ne pas manquer et de fausses à ne pas créer."
)


def _fmt(pts: list[tuple[int, int]]) -> str:
    return ", ".join(f"({x},{y})" for x, y in pts)


# ------------------------------------------------------------------ family 1

def _make_min_distinct(rng: random.Random) -> tuple[str, str]:
    half = rng.choice([4, 5, 6])
    radius = rng.choice([10**6, 3 * 10**6, 10**7, 4 * 10**7])
    poles = rng.choice([1, 2])
    pts = _mirror_polygon(rng, half, radius, poles)
    n = len(pts)
    counts = [len(set(_sqdists_from(pts, i))) for i in range(n)]
    m = min(counts)
    return (
        f"Soit le {n}-gone convexe de sommets entiers, dans l'ordre cyclique direct :\n"
        f"  {_fmt(pts)}\n\n"
        f"Pour un sommet p, note D(p) le nombre de valeurs DISTINCTES prises par le carré\n"
        f"de la distance de p vers les {n - 1} autres sommets.\n\n"
        f"Calcule m = min_p D(p), puis k = le nombre de sommets atteignant ce minimum.\n"
        f"Réponds exactement \"m,k\" : deux entiers séparés par une virgule, sans espace.\n\n"
        f"{_TRAP}",
        f"{m},{counts.count(m)}",
    )


# ------------------------------------------------------------------ family 2

def _make_isosceles_count(rng: random.Random) -> tuple[str, str]:
    half = rng.choice([4, 5, 6])
    radius = rng.choice([10**6, 2 * 10**6, 10**7])
    poles = rng.choice([1, 2])
    pts = _mirror_polygon(rng, half, radius, poles)
    n = len(pts)
    total = 0
    for i in range(n):
        buckets: dict[int, int] = {}
        for d in _sqdists_from(pts, i):
            buckets[d] = buckets.get(d, 0) + 1
        total += sum(c * (c - 1) // 2 for c in buckets.values())
    return (
        f"Soit le {n}-gone convexe de sommets entiers, dans l'ordre cyclique direct :\n"
        f"  {_fmt(pts)}\n\n"
        f"Pour chaque sommet p, regroupe les {n - 1} carrés de distances de p vers les autres\n"
        f"sommets par valeur exactement égale. Une valeur apparaissant μ fois fournit C(μ,2)\n"
        f"paires. Note E la somme de ces C(μ,2) sur TOUS les sommets p — c'est le nombre de\n"
        f"triangles isocèles comptés par apex.\n\n"
        f"Réponds par le seul entier E.\n\n"
        f"{_TRAP}",
        str(total),
    )


# ------------------------------------------------------------------ family 3

def _make_exact_rational(rng: random.Random) -> tuple[str, str]:
    N = rng.randint(30, 48)
    a = rng.choice([1, 2, 3])
    b = rng.choice([1, 3, 5, 7])
    total = sum(Fraction(1, k * k + a * k + b) for k in range(1, N + 1))
    return (
        f"Calcule la somme exacte\n"
        f"  S = Σ_{{k=1}}^{{{N}}} 1 / (k² + {a}·k + {b})\n\n"
        f"Réponds par la fraction irréductible \"numérateur/dénominateur\", sans espace.\n\n"
        f"Attention : une sommation en virgule flottante ne redonnera pas la fraction\n"
        f"exacte — il faut de l'arithmétique rationnelle. Le dénominateur a plusieurs\n"
        f"dizaines de chiffres.",
        f"{total.numerator}/{total.denominator}",
    )


_FAMILIES = (
    ("min_distinct_distances", _make_min_distinct),
    ("isosceles_count", _make_isosceles_count),
    ("exact_rational", _make_exact_rational),
)


def make_challenge(seed: str) -> dict:
    rng = random.Random(hashlib.blake2b(seed.encode(), digest_size=16).hexdigest())
    kind, fn = _FAMILIES[rng.randrange(len(_FAMILIES))]
    prompt, answer = fn(rng)
    return {"kind": kind, "prompt": prompt, "answer": answer}


def normalise(s: str) -> str:
    return "".join(str(s).split()).strip().lower().rstrip(".")


def check(expected: str, given: str) -> bool:
    return normalise(expected) == normalise(given)
