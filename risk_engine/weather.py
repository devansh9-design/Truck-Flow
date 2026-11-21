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

import itertools
import logging
import math
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
    """Open-Meteo failed or sent data we cannot use (Django maps it to 502/504)."""

    def __init__(self, message: str, *, timeout: bool = False):
        super().__init__(message)
        self.timeout = timeout


class IncompleteWeather(WeatherUpstreamError):
    """An hour inside the forecast range is missing or has a null value (C4).

    Distinct from BeyondForecast: the forecast does reach this hour, the provider
    just did not deliver usable numbers for it. Never treated as calm weather.
    """


class BeyondForecast(Exception):
    """The requested hour is later than the last forecast hour (422)."""


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

    def at(self, hour: datetime) -> Weather:
        """Weather for that exact UTC hour.

        Raises BeyondForecast when the hour is after the last forecast hour, and
        IncompleteWeather when the hour is inside the range but missing or null.
        """
        ts = int(hour.timestamp())
        when = f"{datetime.fromtimestamp(ts, UTC):%Y-%m-%d %H:00} UTC"
        if ts > max(self.index):
            raise BeyondForecast()
        i = self.index.get(ts)
        if i is None:
            raise IncompleteWeather(f"Open-Meteo returned no data for {when}.")
        values = {"wind": self.wind_mph[i], "rain/showers": self.rain_in_hr[i],
                  "snowfall": self.snow_in_hr[i]}
        missing = [k for k, v in values.items() if v is None]
        if missing:
            raise IncompleteWeather(f"Open-Meteo returned no {', '.join(missing)} value for {when}.")
        return Weather(wind_mph=self.wind_mph[i], rain_in_hr=self.rain_in_hr[i],
                       snow_in_hr=self.snow_in_hr[i])


class ForecastProvider(Protocol):
    def series(self, cells: Iterable[Cell]) -> tuple[dict[Cell, Series], dict[str, int]]:
        """Series per cell, plus meta counts {"cache_hits", "fetched"}."""


def _factor(table: dict[str, float], unit: str | None, var: str) -> float:
    if unit not in table:
        raise WeatherUpstreamError(f"Open-Meteo reported an unexpected unit for {var}: {unit!r}")
    return table[unit]


def _bad(msg: str) -> WeatherUpstreamError:
    return WeatherUpstreamError(f"Open-Meteo returned malformed data: {msg}.")


def _is_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _values(hourly: dict, var: str, n: int) -> list[float | None]:
    """One hourly array: same length as `time`; each entry null or a finite number >= 0.

    Nulls are kept (C4 reports them only if a checkpoint needs that hour); anything
    else that is not a usable measurement rejects the whole response (C5).
    """
    arr = hourly.get(var)
    if not isinstance(arr, list):
        raise _bad(f"hourly.{var} is missing")
    if len(arr) != n:
        raise _bad(f"hourly.{var} has {len(arr)} values for {n} hours")
    for v in arr:
        if v is None:
            continue
        if not _is_number(v) or not math.isfinite(v) or v < 0:
            raise _bad(f"hourly.{var} contains {v!r}")
    return arr


def parse_location(obj: object) -> Series:
    """Validate one Open-Meteo location object and turn it into a Series (D10, C5)."""
    if not isinstance(obj, dict):
        raise _bad("a location is not an object")
    units = obj.get("hourly_units")
    hourly = obj.get("hourly")
    if not isinstance(units, dict) or not isinstance(hourly, dict):
        raise _bad("hourly data or units are missing")
    times = hourly.get("time")
    if units.get("time") != "unixtime" or not isinstance(times, list) or not times:
        raise WeatherUpstreamError("Open-Meteo returned no hourly times.")
    if not all(_is_number(t) and math.isfinite(t) and t == int(t) for t in times):
        raise _bad("hourly.time contains invalid timestamps")
    stamps = [int(t) for t in times]
    if any(b <= a for a, b in itertools.pairwise(stamps)):
        raise _bad("hourly.time is not strictly increasing")

    kw = _factor(WIND_TO_MPH, units.get("wind_speed_10m"), "wind_speed_10m")
    kr = _factor(PRECIP_TO_IN, units.get("rain"), "rain")
    ks = _factor(PRECIP_TO_IN, units.get("showers"), "showers")
    kn = _factor(PRECIP_TO_IN, units.get("snowfall"), "snowfall")
    n = len(stamps)
    wind = _values(hourly, "wind_speed_10m", n)
    rain = _values(hourly, "rain", n)
    showers = _values(hourly, "showers", n)
    snow = _values(hourly, "snowfall", n)

    def scale(v, k):
        return None if v is None else v * k

    def liquid(r, s):
        return None if r is None or s is None else r * kr + s * ks

    return Series(
        index={t: i for i, t in enumerate(stamps)},
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
        if isinstance(payload, dict):
            objs = [payload]
        elif isinstance(payload, list):
            objs = payload
        else:
            raise _bad("the response is not a JSON object or list")
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
