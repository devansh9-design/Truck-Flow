"""NWS active alerts along the routes (B4, non-core, informational only).

One `GET /alerts/active?point=lat,lon` per distinct point (NWS has no
multi-point query). Points are rounded to 2 decimals (~1 km) before the call,
so the three routes' shared stretches are fetched once; each point's answer is
cached for 10 minutes. NWS answers 400 "out of bounds" for points outside its
area (e.g. Canada, Mexico): such points are skipped, and a request where every
point is out of bounds has coverage "unsupported_region".

Alerts never change a risk level or the ranking; this module does not import
the rules.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from cachetools import TTLCache

from truckrisk_schemas import ALERT_SEVERITIES, Alert, AlertsRequest, AlertsResponse

log = logging.getLogger(__name__)

NWS_URL = "https://api.weather.gov/alerts/active"
DEFAULT_USER_AGENT = "truckrisk-alerts"
CACHE_TTL_S = 10 * 60
TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
WORKERS = 8
RETRY_BACKOFF_S = 0.5

Point = tuple[float, float]


class AlertsUpstreamError(Exception):
    def __init__(self, message: str, *, timeout: bool = False):
        super().__init__(message)
        self.timeout = timeout


class OutOfBounds(Exception):
    """NWS does not cover this point."""


class AlertSource(Protocol):
    def active(self, point: Point) -> list[dict[str, Any]]:
        """Raw NWS feature `properties` for one point; raises OutOfBounds / AlertsUpstreamError."""
        ...


class NwsClient:
    def __init__(self, user_agent: str = "", client: httpx.Client | None = None,
                 url: str = NWS_URL):
        self._client = client or httpx.Client(timeout=TIMEOUT)
        self._url = url
        self._headers = {
            "User-Agent": user_agent or DEFAULT_USER_AGENT,
            "Accept": "application/geo+json",
        }
        self._cache: TTLCache[Point, list[dict[str, Any]] | None] = TTLCache(
            maxsize=5_000, ttl=CACHE_TTL_S)
        self._lock = threading.Lock()

    def active(self, point: Point) -> list[dict[str, Any]]:
        with self._lock:
            if point in self._cache:
                cached = self._cache[point]
                if cached is None:
                    raise OutOfBounds
                return cached
        try:
            props = self._fetch(point)
        except OutOfBounds:
            with self._lock:
                self._cache[point] = None
            raise
        with self._lock:
            self._cache[point] = props
        return props

    def _fetch(self, point: Point) -> list[dict[str, Any]]:
        params = {"point": f"{point[0]:.2f},{point[1]:.2f}"}
        timed_out = False
        for attempt in range(2):
            if attempt:
                time.sleep(RETRY_BACKOFF_S)
            try:
                resp = self._client.get(self._url, params=params, headers=self._headers)
            except httpx.TimeoutException:
                timed_out = True
                continue
            except httpx.TransportError:
                timed_out = False
                continue
            if resp.status_code == 200:
                try:
                    features = resp.json().get("features")
                except ValueError:
                    raise AlertsUpstreamError("NWS returned an unreadable response.") from None
                if not isinstance(features, list):
                    raise AlertsUpstreamError("NWS returned an unexpected response.")
                return [f.get("properties") or {} for f in features if isinstance(f, dict)]
            if resp.status_code in (400, 404) and _is_out_of_bounds(resp):
                raise OutOfBounds
            if resp.status_code == 429 or 400 <= resp.status_code < 500:
                raise AlertsUpstreamError(f"NWS rejected the request ({resp.status_code}).")
            timed_out = False  # 5xx: retry once
        if timed_out:
            raise AlertsUpstreamError("NWS did not respond in time.", timeout=True)
        raise AlertsUpstreamError("NWS is unavailable right now.")


def _is_out_of_bounds(resp: httpx.Response) -> bool:
    """NWS: 400 InvalidParameter, detail 'Parameter "point" is invalid: out of bounds'."""
    try:
        detail = str(resp.json().get("detail", ""))
    except ValueError:
        return False
    return "out of bounds" in detail.lower()


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else None


def _to_alert(props: dict[str, Any], point_index: int) -> Alert | None:
    alert_id, event = props.get("id"), props.get("event")
    if not isinstance(alert_id, str) or not isinstance(event, str):
        return None
    severity = props.get("severity")
    headline = props.get("headline")
    return Alert(
        id=alert_id,
        event=event,
        severity=severity if severity in ALERT_SEVERITIES else "Unknown",
        headline=headline if isinstance(headline, str) else None,
        areas=str(props.get("areaDesc") or ""),
        onset=_utc(props.get("onset")) or _utc(props.get("effective")),
        ends=_utc(props.get("ends")),
        point_index=point_index,
    )


def collect_alerts(req: AlertsRequest, source: AlertSource) -> AlertsResponse:
    """Deduplicated alerts (by NWS id), most severe first; each keeps its first point."""
    keys = [(round(p.lat, 2), round(p.lon, 2)) for p in req.points]
    distinct = list(dict.fromkeys(keys))

    def fetch(pt: Point) -> list[dict[str, Any]] | None:
        try:
            return source.active(pt)
        except OutOfBounds:
            return None

    with ThreadPoolExecutor(max_workers=min(WORKERS, len(distinct))) as pool:
        answers = dict(zip(distinct, pool.map(fetch, distinct), strict=True))

    if all(a is None for a in answers.values()):
        return AlertsResponse(alerts=[], coverage="unsupported_region")

    seen: dict[str, Alert] = {}
    for idx, key in enumerate(keys):
        for props in answers[key] or []:
            alert = _to_alert(props, idx)
            if alert and alert.id not in seen:
                seen[alert.id] = alert
    rank = {s: i for i, s in enumerate(ALERT_SEVERITIES)}
    ordered = sorted(seen.values(), key=lambda a: (rank[a.severity], a.point_index))
    return AlertsResponse(alerts=ordered, coverage="US")
