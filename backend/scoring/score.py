"""Route scoring (spec D2, D3, D5).

* The route is split into segments between consecutive checkpoints
  (origin and destination are checkpoints).
* A segment's level is the worse of its two endpoints (D2, conservative).
* miles_by_level sums segment lengths per level. Severe and No Travel miles
  are kept separate (D3): a No Travel segment adds to no_travel_mi only.
* avg_risk is the distance-weighted mean of segment scores (D5).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from truckrisk_schemas import RiskLevel


@dataclass(frozen=True)
class Segment:
    start_mi: float
    end_mi: float
    level: RiskLevel

    @property
    def length_mi(self) -> float:
        return self.end_mi - self.start_mi


@dataclass(frozen=True)
class RouteScore:
    miles_by_level: dict[RiskLevel, float]
    avg_risk: float
    max_level: RiskLevel
    segments: list[Segment]

    @property
    def no_travel_mi(self) -> float:
        return self.miles_by_level[RiskLevel.NO_TRAVEL]

    @property
    def severe_mi(self) -> float:
        return self.miles_by_level[RiskLevel.SEVERE]

    @property
    def high_mi(self) -> float:
        return self.miles_by_level[RiskLevel.HIGH]

    @property
    def has_no_travel(self) -> bool:
        return self.no_travel_mi > 0

    def to_dict(self) -> dict:
        return {
            "miles_by_level": {lv.value: round(mi, 1) for lv, mi in self.miles_by_level.items()},
            "severe_mi": round(self.severe_mi, 1),
            "high_mi": round(self.high_mi, 1),
            "no_travel_mi": round(self.no_travel_mi, 1),
            "has_no_travel": self.has_no_travel,
            "avg_risk": round(self.avg_risk, 2),
            "max_level": self.max_level.value,
        }


def _worse(a: RiskLevel, b: RiskLevel) -> RiskLevel:
    return a if a.score >= b.score else b


def score_route(miles: Sequence[float], levels: Sequence[RiskLevel]) -> RouteScore:
    """miles[i] is checkpoint i's position along the route; levels[i] its risk level."""
    if len(miles) != len(levels) or not miles:
        raise ValueError("need one level per checkpoint")
    if any(b < a for a, b in zip(miles, miles[1:], strict=False)):
        raise ValueError("checkpoint miles must be non-decreasing")

    segments = [
        Segment(miles[i], miles[i + 1], _worse(levels[i], levels[i + 1]))
        for i in range(len(miles) - 1)
    ]
    by_level = {lv: 0.0 for lv in RiskLevel}
    for seg in segments:
        by_level[seg.level] += seg.length_mi

    total = sum(by_level.values())
    max_level = max(levels, key=lambda lv: lv.score)
    if total > 0:
        avg = sum(seg.length_mi * seg.level.score for seg in segments) / total
    else:  # degenerate single-point route: its only checkpoint decides
        avg = float(max_level.score)
    return RouteScore(miles_by_level=by_level, avg_risk=avg, max_level=max_level, segments=segments)
