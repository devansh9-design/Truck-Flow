"""How much road two routes share (spec D12: near-duplicate = > 90% shared length).

Each route is cut into short pieces (~0.1 mi). A piece of route A counts as
shared when its midpoint falls in a grid cell that route B passes through,
or in one of the 8 cells around it (cell ~ 0.003 deg ~ 330 m north-south),
which absorbs the small offsets between two polylines of the same road.

shared_fraction(A, B) = shared length / length of the shorter route, i.e. the
larger of the two one-way fractions. Two routes that differ only by a short
detour therefore count as near-duplicates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .track import Track

CELL_DEG = 0.003
PIECE_MI = 0.1
NEAR_DUPLICATE_SHARE = 0.90

Cell = tuple[int, int]


def _cell(lat: float, lon: float) -> Cell:
    return (math.floor(lat / CELL_DEG), math.floor(lon / CELL_DEG))


def _pieces(track: Track) -> list[tuple[Cell, float]]:
    """(cell of piece midpoint, piece length) along the whole track."""
    out: list[tuple[Cell, float]] = []
    for i in range(1, len(track.coords)):
        step = track.cum_mi[i] - track.cum_mi[i - 1]
        if step <= 0:
            continue
        (la0, lo0), (la1, lo1) = track.coords[i - 1], track.coords[i]
        n = max(1, math.ceil(step / PIECE_MI))
        for k in range(n):
            f = (k + 0.5) / n
            out.append((_cell(la0 + f * (la1 - la0), lo0 + f * (lo1 - lo0)), step / n))
    return out


@dataclass(frozen=True)
class Footprint:
    """A track cut into cell pieces; build once per route, compare many times."""

    pieces: list[tuple[Cell, float]]
    cells: frozenset[Cell]
    length_mi: float


def footprint(track: Track) -> Footprint:
    pieces = _pieces(track)
    return Footprint(pieces, frozenset(c for c, _ in pieces), sum(x for _, x in pieces))


def _shared_len(pieces: list[tuple[Cell, float]], other: frozenset[Cell]) -> float:
    total = 0.0
    for (r, c), length in pieces:
        if any((r + dr, c + dc) in other for dr in (-1, 0, 1) for dc in (-1, 0, 1)):
            total += length
    return total


def shared_fraction(a: Track | Footprint, b: Track | Footprint) -> float:
    fa = a if isinstance(a, Footprint) else footprint(a)
    fb = b if isinstance(b, Footprint) else footprint(b)
    if fa.length_mi <= 0 or fb.length_mi <= 0:
        return 1.0
    return max(
        _shared_len(fa.pieces, fb.cells) / fa.length_mi,
        _shared_len(fb.pieces, fa.cells) / fb.length_mi,
    )


def is_near_duplicate(a: Track | Footprint, b: Track | Footprint) -> bool:
    return shared_fraction(a, b) > NEAR_DUPLICATE_SHARE
