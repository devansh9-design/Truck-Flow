"""Open-Meteo hourly forecasts at each checkpoint's ETA hour (CORE-2).

Request (`GET https://api.open-meteo.com/v1/forecast`), checked against a
recorded real response (tests/fixtures/open_meteo_two_points.json):
    latitude=<a>,<b>,... longitude=<a>,<b>,...   (several locations per call)
    hourly=wind_speed_10m,rain,showers,snowfall
    wind_speed_unit=mph  precipitation_unit=inch
    forecast_days=16  past_days=1  timezone=GMT  timeformat=unixtime
Response: a JSON list (one object per location; a plain object for one
location) with `hourly_units` and `hourly.{time, wind_speed_10m, rain,
showers, snowfall}`. Errors come back as {"error": true, "reason": "..."}.

Interpretations:
    D8  wind = sustained wind_speed_10m (not gusts)
    D9  rain = rain + showers (liquid); snowfall is separate
    D10 units are converted explicitly from `hourly_units`, whatever they are
    Open-Meteo's hourly precipitation is the total for the preceding hour, so
    the value stamped at the forecast hour is used as that hour's in/hr rate.

Points are deduplicated to a 0.1 deg grid cell (about 7 mi) and the cell's
centre is requested; a location's whole series is cached for 30 minutes.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx
from cachetools import TTLCache

from truckrisk_schemas import Weather

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARS = "wind_speed_10m,rain,showers,snowfall"
FORECAST_DAYS = 16
BATCH_SIZE = 50  # locations per request (keeps the URL short)
MAX_WORKERS = 4
CACHE_TTL_S = 30 * 60
TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)
RETRY_BACKOFF_S = 0.5

WIND_TO_MPH = {"mp/h": 1.0, "mph": 1.0, "km/h": 1 / 1.609344, "m/s": 2.2369363, "kn": 1.1507794}
PRECIP_TO_IN = {"inch": 1.0, "in": 1.0, "mm": 1 / 25.4, "cm": 1 / 2.54}

Cell = tuple[int, int]  # (round(lat*10), round(lon*10))


class WeatherUpstreamError(Exception):
    def __init__(self, message: str, *, timeout: bool = False):
        super().__init__(message)
        self.timeout = timeout


def cell_of(lat: float, lon: float) -> Cell:
    return (round(lat * 10), round(lon * 10))


@dataclass(frozen=True)
class Series:
    """One location's hourly forecast, already in imperial units."""

    index: dict[int, int]  # unix hour -> position
    wind_mph: Sequence[float | None]
    rain_in_hr: Sequence[float | None]  # rain + showers
    snow_in_hr: Sequence[float | None]

    @property
    def last_hour(self) -> datetime:
        return datetime.fromtimestamp(max(self.index), UTC)

    def at(self, hour: datetime) -> Weather | None:
        """Weather for that exact UTC hour, or None if the forecast doesn't cover it."""
        i = self.index.get(int(hour.timestamp()))
        if i is None:
            return None
        w, r, s = self.wind_mph[i], self.rain_in_hr[i], self.snow_in_hr[i]
        if w is None or r is None or s is None:
            return None
        return Weather(wind_mph=w, rain_in_hr=r, snow_in_hr=s)


class ForecastProvider(Protocol):
    def series(self, cells: Iterable[Cell]) -> tuple[dict[Cell, Series], dict[str, int]]:
        """Series per cell, plus meta counts {"cache_hits", "fetched"}."""


def _factor(table: dict[str, float], unit: str | None, var: str) -> float:
    if unit not in table:
        raise WeatherUpstreamError(f"Open-Meteo reported an unexpected unit for {var}: {unit!r}")
    return table[unit]


def parse_location(obj: dict) -> Series:
    """Turn one Open-Meteo location object into a Series (explicit unit conversion, D10)."""
    units = obj.get("hourly_units") or {}
    hourly = obj.get("hourly") or {}
    times = hourly.get("time")
    if not times or units.get("time") != "unixtime":
        raise WeatherUpstreamError("Open-Meteo returned no hourly times.")
    kw = _factor(WIND_TO_MPH, units.get("wind_speed_10m"), "wind_speed_10m")
    kr = _factor(PRECIP_TO_IN, units.get("rain"), "rain")
    ks = _factor(PRECIP_TO_IN, units.get("showers"), "showers")
    kn = _factor(PRECIP_TO_IN, units.get("snowfall"), "snowfall")
    try:
        wind, rain, showers, snow = (
            hourly["wind_speed_10m"], hourly["rain"], hourly["showers"], hourly["snowfall"]
        )
    except KeyError as exc:
        raise WeatherUpstreamError(f"Open-Meteo response is missing {exc.args[0]}.") from None

    def scale(v, k):
        return None if v is None else v * k

    def liquid(r, s):
        return None if r is None or s is None else r * kr + s * ks

    return Series(
        index={int(t): i for i, t in enumerate(times)},
        wind_mph=[scale(v, kw) for v in wind],
        rain_in_hr=[liquid(r, s) for r, s in zip(rain, showers, strict=True)],
        snow_in_hr=[scale(v, kn) for v in snow],
    )


class OpenMeteoProvider:
    def __init__(self, client: httpx.Client | None = None, url: str = OPEN_METEO_URL):
        self._client = client or httpx.Client(timeout=TIMEOUT)
        self._url = url
        self._cache: TTLCache[Cell, Series] = TTLCache(maxsize=20_000, ttl=CACHE_TTL_S)
        self._lock = threading.Lock()

    def series(self, cells: Iterable[Cell]) -> tuple[dict[Cell, Series], dict[str, int]]:
        wanted = list(dict.fromkeys(cells))
        out: dict[Cell, Series] = {}
        missing: list[Cell] = []
        with self._lock:
            for c in wanted:
                s = self._cache.get(c)
                if s is None:
                    missing.append(c)
                else:
                    out[c] = s
        hits = len(wanted) - len(missing)
        batches = [missing[i : i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
        if batches:
            with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(batches))) as pool:
                for fetched in pool.map(self._fetch, batches):
                    out.update(fetched)
            with self._lock:
                for c in missing:
                    self._cache[c] = out[c]
        return out, {"cache_hits": hits, "fetched": len(missing)}

    def _fetch(self, cells: list[Cell]) -> dict[Cell, Series]:
        params = {
            "latitude": ",".join(f"{c[0] / 10:.1f}" for c in cells),
            "longitude": ",".join(f"{c[1] / 10:.1f}" for c in cells),
            "hourly": HOURLY_VARS,
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "forecast_days": FORECAST_DAYS,
            "past_days": 1,
            "timezone": "GMT",
            "timeformat": "unixtime",
        }
        payload = self._get(params)
        objs = payload if isinstance(payload, list) else [payload]
        if len(objs) != len(cells):
            raise WeatherUpstreamError("Open-Meteo returned the wrong number of locations.")
        return {c: parse_location(o) for c, o in zip(cells, objs, strict=True)}

    def _get(self, params: dict):
        timed_out = False
        for attempt in range(2):
            if attempt:
                time.sleep(RETRY_BACKOFF_S)
            try:
                resp = self._client.get(self._url, params=params)
            except httpx.TimeoutException:
                timed_out = True
                log.warning("Open-Meteo timed out (attempt %d)", attempt + 1)
                continue
            except httpx.TransportError as exc:
                timed_out = False
                log.warning("Open-Meteo connection failed (attempt %d): %s", attempt + 1,
                            type(exc).__name__)
                continue
            timed_out = False
            try:
                body = resp.json()
            except ValueError:
                body = None
            if resp.status_code == 200 and not (isinstance(body, dict) and body.get("error")):
                return body
            reason = body.get("reason") if isinstance(body, dict) else None
            log.warning("Open-Meteo returned %d (attempt %d): %s", resp.status_code, attempt + 1,
                        reason)
            if resp.status_code < 500 and resp.status_code != 429:
                raise WeatherUpstreamError(f"Open-Meteo rejected the request: {reason or resp.status_code}")
        if timed_out:
            raise WeatherUpstreamError("Open-Meteo did not respond in time.", timeout=True)
        raise WeatherUpstreamError("Open-Meteo is unavailable right now.")
