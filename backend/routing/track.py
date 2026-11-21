"""A route as a polyline with cumulative distance and elapsed time per vertex.

How the per-vertex time is built (spec D7, architecture §3):

* Each HERE section gives a polyline, a summary (length in meters, duration
  in seconds) and, when requested, `spans` with `offset` (index into the
  section polyline) and `duration` (seconds).
* A span's duration is spread over the polyline steps it covers in
  proportion to each step's length. Without spans, the section duration is
  spread over the whole section the same way.
* Step times are then scaled so they add up to the section's summary
  duration, and step distances are scaled so they add up to the section's
  summary length. The router's road distance and time are authoritative; the
  polyline only says *where* along the road a mile or second falls.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass

EARTH_RADIUS_MI = 3958.7613  # mean Earth radius (IUGG), miles

LatLonT = tuple[float, float]


def haversine_mi(a: LatLonT, b: LatLonT) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(h)))


def initial_bearing_deg(a: LatLonT, b: LatLonT) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def destination_point(origin: LatLonT, bearing_deg: float, distance_mi: float) -> LatLonT:
    lat1, lon1 = map(math.radians, origin)
    brg = math.radians(bearing_deg)
    d = distance_mi / EARTH_RADIUS_MI
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(brg))
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    lon2 = (math.degrees(lon2) + 540) % 360 - 180
    return math.degrees(lat2), lon2


@dataclass(frozen=True)
class SectionInput:
    """One router section, already decoded and converted to imperial units."""

    coords: Sequence[LatLonT]
    length_mi: float
    duration_s: float
    # (polyline offset, duration seconds) per span; empty if spans were not returned.
    spans: Sequence[tuple[int, float]] = ()


@dataclass(frozen=True)
class Track:
    coords: list[LatLonT]
    cum_mi: list[float]
    cum_s: list[float]

    @property
    def distance_mi(self) -> float:
        return self.cum_mi[-1]

    @property
    def duration_s(self) -> float:
        return self.cum_s[-1]

    def locate(self, mile: float) -> tuple[LatLonT, float]:
        """Point and elapsed seconds at `mile` along the track (linear interpolation)."""
        mile = min(max(mile, 0.0), self.distance_mi)
        i = bisect.bisect_left(self.cum_mi, mile)
        if i == 0:
            return self.coords[0], self.cum_s[0]
        if i >= len(self.cum_mi):
            return self.coords[-1], self.cum_s[-1]
        m0, m1 = self.cum_mi[i - 1], self.cum_mi[i]
        f = 0.0 if m1 == m0 else (mile - m0) / (m1 - m0)
        (la0, lo0), (la1, lo1) = self.coords[i - 1], self.coords[i]
        point = (la0 + f * (la1 - la0), lo0 + f * (lo1 - lo0))
        return point, self.cum_s[i - 1] + f * (self.cum_s[i] - self.cum_s[i - 1])


def _spread(total: float, weights: Sequence[float]) -> list[float]:
    s = sum(weights)
    if not weights:
        return []
    if s <= 0:
        return [total / len(weights)] * len(weights)
    return [total * w / s for w in weights]


def _section_steps(sec: SectionInput) -> tuple[list[float], list[float]]:
    """Per-step (distance_mi, seconds) for one section, scaled to its summary."""
    coords = list(sec.coords)
    raw = [haversine_mi(coords[i - 1], coords[i]) for i in range(1, len(coords))]
    n_steps = len(raw)
    if n_steps == 0:
        return [], []

    if sec.spans:
        times = [0.0] * n_steps
        spans = sorted(sec.spans)
        for j, (offset, dur) in enumerate(spans):
            start = max(0, min(offset, n_steps))
            end = spans[j + 1][0] if j + 1 < len(spans) else n_steps
            end = max(start, min(end, n_steps))
            if end == start:
                # Zero-length span (a single vertex): give its time to the next step.
                if start < n_steps:
                    times[start] += dur
                continue
            for k, t in enumerate(_spread(dur, raw[start:end])):
                times[start + k] += t
        # Spans must account for the summary duration; rescale any drift.
        times = _spread(sec.duration_s, times) if sum(times) > 0 else _spread(sec.duration_s, raw)
    else:
        times = _spread(sec.duration_s, raw)

    raw_total = sum(raw)
    if raw_total > 0 and sec.length_mi > 0:
        scale = sec.length_mi / raw_total
        dists = [d * scale for d in raw]
    else:
        dists = raw
    return dists, times


def build_track(sections: Sequence[SectionInput]) -> Track:
    coords: list[LatLonT] = []
    cum_mi: list[float] = []
    cum_s: list[float] = []
    for sec in sections:
        if not sec.coords:
            continue
        dists, times = _section_steps(sec)
        sec_coords = list(sec.coords)
        if not coords:
            coords.append(sec_coords[0])
            cum_mi.append(0.0)
            cum_s.append(0.0)
        else:
            # Join sections: the next section starts where the previous ended.
            if sec_coords[0] != coords[-1]:
                gap = haversine_mi(coords[-1], sec_coords[0])
                coords.append(sec_coords[0])
                cum_mi.append(cum_mi[-1] + gap)
                cum_s.append(cum_s[-1])
        for pt, d, t in zip(sec_coords[1:], dists, times, strict=True):
            coords.append(pt)
            cum_mi.append(cum_mi[-1] + d)
            cum_s.append(cum_s[-1] + t)
    if len(coords) < 2:
        raise ValueError("A route needs at least two points.")
    return Track(coords=coords, cum_mi=cum_mi, cum_s=cum_s)
