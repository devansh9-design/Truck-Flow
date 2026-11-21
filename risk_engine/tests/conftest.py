"""Scripted weather for tests: no network, no current date."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta

import pytest
from weather import Cell, Series

from truckrisk_schemas import Weather

CALM = Weather(wind_mph=5.0, rain_in_hr=0.0, snow_in_hr=0.0)
START = datetime(2026, 11, 20, 0, tzinfo=UTC)
HOURS = 17 * 24  # past_days=1 + forecast_days=16


class FakeProvider:
    """weather_fn(lat, lon, hour) -> Weather, served as Series per 0.1 deg cell."""

    def __init__(self, weather_fn: Callable[[float, float, datetime], Weather] | None = None,
                 start: datetime = START, hours: int = HOURS):
        self.fn = weather_fn or (lambda lat, lon, hour: CALM)
        self.start, self.hours = start, hours
        self.requested: list[Cell] = []

    def series(self, cells: Iterable[Cell]):
        cells = list(dict.fromkeys(cells))
        self.requested.extend(cells)
        out = {}
        for c in cells:
            lat, lon = c[0] / 10, c[1] / 10
            ws = [self.fn(lat, lon, self.start + timedelta(hours=h)) for h in range(self.hours)]
            out[c] = Series(
                index={int((self.start + timedelta(hours=h)).timestamp()): h for h in range(self.hours)},
                wind_mph=[w.wind_mph for w in ws],
                rain_in_hr=[w.rain_in_hr for w in ws],
                snow_in_hr=[w.snow_in_hr for w in ws],
            )
        return out, {"cache_hits": 0, "fetched": len(cells)}


@pytest.fixture
def fake_provider():
    return FakeProvider()
