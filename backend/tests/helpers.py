"""Synthetic geometry + HERE-shaped payloads for tests (no network)."""

from __future__ import annotations

import flexpolyline

from routing.track import SectionInput, Track, build_track, destination_point, haversine_mi
from truckrisk_schemas import miles_to_meters


def straight_line(miles: float, *, start=(39.0, -100.0), bearing=90.0, step_mi=1.0):
    """Points along a great circle, about `step_mi` apart."""
    n = max(1, round(miles / step_mi))
    return [destination_point(start, bearing, miles * i / n) for i in range(n + 1)]


def line_length(coords) -> float:
    return sum(haversine_mi(coords[i - 1], coords[i]) for i in range(1, len(coords)))


def track_for(coords, mph: float = 60.0) -> Track:
    length = line_length(coords)
    return build_track([SectionInput(coords=coords, length_mi=length, duration_s=length / mph * 3600)])


def here_section(coords, *, length_mi=None, duration_s=None, spans=None) -> dict:
    length_mi = line_length(coords) if length_mi is None else length_mi
    duration_s = length_mi / 60 * 3600 if duration_s is None else duration_s
    sec = {
        "id": "s",
        "type": "vehicle",
        "polyline": flexpolyline.encode(coords),
        "summary": {"length": round(miles_to_meters(length_mi)), "duration": round(duration_s)},
    }
    if spans is not None:
        sec["spans"] = spans
    return sec


def here_route(coords, rid="route", **kw) -> dict:
    return {"id": rid, "sections": [here_section(coords, **kw)]}


def bowed(miles: float, bow_mi: float, *, start=(39.0, -100.0), bearing=90.0, n=40):
    """An O->D path bulging `bow_mi` sideways at the middle (a distinct road)."""
    end = destination_point(start, bearing, miles)
    pts = []
    for i in range(n + 1):
        f = i / n
        base = destination_point(start, bearing, miles * f)
        offset = bow_mi * (1 - (2 * f - 1) ** 2)
        pts.append(destination_point(base, bearing - 90, offset) if offset != 0 else base)
    pts[-1] = end
    return pts
