"""Checkpoint sampling and ETAs (CORE-2, spec D2 and D7).

* Checkpoints sit every `interval_mi` along the route, starting at mile 0.
  The origin and the destination are always checkpoints; when the route
  length is not a multiple of the interval, the destination is added as a
  final, shorter step (a 103 mi route at 25 mi -> 0, 25, 50, 75, 100, 103).
* ETA = departure + cumulative router travel time to that point.
* forecast_hour = ETA rounded to the nearest hour (:30:00 rounds up).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .track import Track

ALLOWED_INTERVALS_MI = (10, 25, 50)
# A destination closer than this to the last interval mark is merged into it,
# so float noise never creates a zero-length final segment.
_MERGE_EPS_MI = 0.01


@dataclass(frozen=True)
class Checkpoint:
    index: int
    mile: float
    lat: float
    lon: float
    elapsed_s: float
    eta: datetime
    forecast_hour: datetime


def round_to_hour(t: datetime) -> datetime:
    """Nearest whole hour; exactly :30:00 rounds up."""
    floor = t.replace(minute=0, second=0, microsecond=0)
    return floor + timedelta(hours=1) if t - floor >= timedelta(minutes=30) else floor


def checkpoint_miles(total_mi: float, interval_mi: float) -> list[float]:
    if interval_mi <= 0:
        raise ValueError("interval_mi must be positive")
    if total_mi <= 0:
        return [0.0]
    marks: list[float] = []
    k = 0
    while k * interval_mi < total_mi - _MERGE_EPS_MI:
        marks.append(k * interval_mi)
        k += 1
    marks.append(total_mi)
    return marks


def sample_checkpoints(track: Track, interval_mi: float, departure: datetime) -> list[Checkpoint]:
    if departure.tzinfo is None:
        raise ValueError("departure must be timezone-aware")
    departure = departure.astimezone(UTC)
    out: list[Checkpoint] = []
    for i, mile in enumerate(checkpoint_miles(track.distance_mi, interval_mi)):
        (lat, lon), elapsed = track.locate(mile)
        eta = departure + timedelta(seconds=elapsed)
        out.append(
            Checkpoint(
                index=i,
                mile=mile,
                lat=lat,
                lon=lon,
                elapsed_s=elapsed,
                eta=eta,
                forecast_hour=round_to_hour(eta),
            )
        )
    return out
