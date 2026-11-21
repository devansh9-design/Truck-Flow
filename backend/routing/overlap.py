"""How much road two routes share (spec D12: near-duplicate = > 90% shared length).

Each route is cut into short pieces (~0.1 mi). A piece of route A counts as
shared when its midpoint lies within MATCH_TOLERANCE_M metres of route B's
line, measured as an exact point-to-segment distance (review item C2).

Distances are computed in Web Mercator, which is conformal: near latitude phi a
Mercator length L corresponds to L * cos(phi) metres on the ground. So the
tolerance at a point is MATCH_TOLERANCE_M / cos(phi) Mercator units, which keeps
the rule "within 100 m" the same at every latitude. A coarse grid is only used to
find the segments worth measuring; it never decides a match on its own.

The tolerance absorbs the small differences between two encodings of the same
road (polyline simplification, a few metres of drift), while parallel roads a
few hundred metres apart stay distinct.

shared_fraction(A, B) = the larger of the two one-way fractions, i.e. shared
length / length of the shorter route. It is symmetric: f(A, B) == f(B, A).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .track import Track

EARTH_RADIUS_M = 6_378_137.0  # Web Mercator sphere
MATCH_TOLERANCE_M = 100.0
PIECE_MI = 0.1
NEAR_DUPLICATE_SHARE = 0.90

XY = tuple[float, float]
Cell = tuple[int, int]


def _mercator(lat: float, lon: float) -> XY:
    lat = max(min(lat, 85.0), -85.0)
    return (
        EARTH_RADIUS_M * math.radians(lon),
        EARTH_RADIUS_M * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)),
    )


def _tolerance(lat: float) -> float:
    """MATCH_TOLERANCE_M expressed in Mercator units at this latitude."""
    return MATCH_TOLERANCE_M / math.cos(math.radians(max(min(lat, 85.0), -85.0)))


def _seg_dist(p: XY, a: XY, b: XY) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    den = dx * dx + dy * dy
    t = 0.0 if den == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / den))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


@dataclass(frozen=True)
class Piece:
    xy: XY
    tol: float  # match tolerance at this piece, in Mercator units
    length_mi: float


@dataclass
class Footprint:
    """A route as pieces plus a segment index; build once, compare many times."""

    pieces: list[Piece]
    segments: list[tuple[XY, XY]]
    length_mi: float
    cell: float
    _index: dict[Cell, list[int]] | None = field(default=None, repr=False)

    def _key(self, x: float, y: float) -> Cell:
        return (math.floor(x / self.cell), math.floor(y / self.cell))

    @property
    def index(self) -> dict[Cell, list[int]]:
        """Grid cell -> segments passing near it (sampled every half cell)."""
        if self._index is None:
            idx: dict[Cell, list[int]] = {}
            for i, (a, b) in enumerate(self.segments):
                n = max(1, math.ceil(math.dist(a, b) / (self.cell / 2)))
                for k in dict.fromkeys(
                    self._key(a[0] + (b[0] - a[0]) * j / n, a[1] + (b[1] - a[1]) * j / n)
                    for j in range(n + 1)
                ):
                    idx.setdefault(k, []).append(i)
            self._index = idx
        return self._index

    def near(self, p: XY, tol: float) -> bool:
        """True when p is within `tol` (Mercator units) of this route's line."""
        cx, cy = self._key(*p)
        # Segments are sampled every half cell, so the segment point nearest to p is
        # within cell/4 of a sample: searching (tol + cell/4) around p is complete.
        r = math.ceil((tol + self.cell / 4) / self.cell)
        seen: set[int] = set()
        index = self.index
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                for i in index.get((cx + dx, cy + dy), ()):
                    if i in seen:
                        continue
                    seen.add(i)
                    a, b = self.segments[i]
                    if _seg_dist(p, a, b) <= tol:
                        return True
        return False


def footprint(track: Track) -> Footprint:
    xy = [_mercator(lat, lon) for lat, lon in track.coords]
    pieces: list[Piece] = []
    segments: list[tuple[XY, XY]] = []
    for i in range(1, len(track.coords)):
        if xy[i] != xy[i - 1]:
            segments.append((xy[i - 1], xy[i]))
        step = track.cum_mi[i] - track.cum_mi[i - 1]
        if step <= 0:
            continue
        (la0, _), (la1, _) = track.coords[i - 1], track.coords[i]
        n = max(1, math.ceil(step / PIECE_MI))
        for k in range(n):
            f = (k + 0.5) / n
            p = (xy[i - 1][0] + f * (xy[i][0] - xy[i - 1][0]),
                 xy[i - 1][1] + f * (xy[i][1] - xy[i - 1][1]))
            pieces.append(Piece(p, _tolerance(la0 + f * (la1 - la0)), step / n))
    max_lat = max((abs(lat) for lat, _ in track.coords), default=0.0)
    return Footprint(
        pieces=pieces,
        segments=segments,
        length_mi=sum(p.length_mi for p in pieces),
        cell=2 * _tolerance(max_lat),
    )


def _shared_len(a: Footprint, b: Footprint) -> float:
    """Length of a's pieces that lie within tolerance of b's line."""
    return sum(p.length_mi for p in a.pieces if b.near(p.xy, p.tol))


def shared_fraction(a: Track | Footprint, b: Track | Footprint) -> float:
    fa = a if isinstance(a, Footprint) else footprint(a)
    fb = b if isinstance(b, Footprint) else footprint(b)
    if fa.length_mi <= 0 or fb.length_mi <= 0:
        return 1.0
    return max(_shared_len(fa, fb) / fa.length_mi, _shared_len(fb, fa) / fb.length_mi)


def _share_exceeds(a: Footprint, b: Footprint, share: float) -> bool:
    """Does more than `share` of a lie on b? Stops as soon as the answer is known."""
    budget = (1.0 - share) * a.length_mi  # unshared length a may have and still pass
    unshared = 0.0
    for p in a.pieces:
        if not b.near(p.xy, p.tol):
            unshared += p.length_mi
            if unshared >= budget:
                return False
    return True


def is_near_duplicate(a: Track | Footprint, b: Track | Footprint) -> bool:
    """Strictly more than 90% shared: exactly 90% is still a distinct route.

    Same answer as shared_fraction(a, b) > NEAR_DUPLICATE_SHARE, with early exit.
    """
    fa = a if isinstance(a, Footprint) else footprint(a)
    fb = b if isinstance(b, Footprint) else footprint(b)
    if fa.length_mi <= 0 or fb.length_mi <= 0:
        return True
    return _share_exceeds(fa, fb, NEAR_DUPLICATE_SHARE) or _share_exceeds(
        fb, fa, NEAR_DUPLICATE_SHARE
    )
