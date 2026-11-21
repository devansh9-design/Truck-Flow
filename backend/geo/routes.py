"""Three truck routes from HERE Routing v8 (CORE-1, spec D12 and D13).

Request (`GET /v8/routes`), parameters confirmed against the HERE v8 API
reference:
    transportMode=truck, origin, destination, departureTime (RFC 3339),
    alternatives (0..6), return=polyline,summary, spans=length,duration,speedLimit,
    vehicle[grossWeight] (kilograms), via=<lat>,<lng>!passThrough=true, apiKey.
Response fields read:
    routes[].id, routes[].sections[].polyline (flexible polyline),
    sections[].summary.length (m), sections[].summary.duration (s),
    sections[].spans[].offset, sections[].spans[].duration (s).

Selection:
    1. Ask for the optimal route plus up to 5 alternatives.
    2. Sort by duration; walk fastest first and drop any route that shares
       > 90% of its length with one already kept (near-duplicate).
    3. If fewer than 3 remain, request detours through via points offset to
       either side of the fastest route's midpoint (bounded budget, see
       VIA_OFFSET_FRACTIONS), and keep distinct ones.
    4. Keep the 3 fastest distinct routes. Fewer only when HERE returned no
       third distinct route; `notes` records the attempts and outcome.

Errors (C1): only HERE's `noRouteFound` result becomes NO_ROUTE. Auth
failures, rate limits (429, not retried), invalid requests (other 4xx) and
outages become upstream errors and never claim that no route exists.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

import flexpolyline
from django.conf import settings

from api.errors import NoRoute, UpstreamError, UpstreamTimeout
from routing.overlap import Footprint, footprint, is_near_duplicate
from routing.track import (
    LatLonT,
    SectionInput,
    Track,
    build_track,
    destination_point,
    initial_bearing_deg,
)
from truckrisk_schemas import Place, lb_to_kg, meters_to_miles

from .http import get_json

log = logging.getLogger(__name__)

PROVIDER = "HERE routing"
TARGET_ROUTES = 3
MAX_ALTERNATIVES = 5
# Via-point offsets as a fraction of the route length, tried in order, each
# on both sides of the midpoint. Clamped to [VIA_MIN_MI, VIA_MAX_MI]; at most
# 6 extra HERE calls per trip (C3 attempt budget).
VIA_OFFSET_FRACTIONS = (0.10, 0.20, 0.35)
VIA_MIN_MI = 5.0
VIA_MAX_MI = 150.0


@dataclass
class CandidateRoute:
    track: Track
    distance_mi: float
    duration_s: float
    source: str  # "router" or "via"
    here_id: str = ""
    _fp: Footprint | None = field(default=None, repr=False)

    @property
    def fp(self) -> Footprint:
        if self._fp is None:
            self._fp = footprint(self.track)
        return self._fp


def gross_weight_kg(load_lb: float) -> int:
    """Router weight (D13): load as entered + configurable tare, in kg."""
    return round(lb_to_kg(load_lb + settings.TRUCK_TARE_LB))


def _fmt(p: LatLonT) -> str:
    return f"{p[0]:.6f},{p[1]:.6f}"


def _parse_route(raw: dict, source: str) -> CandidateRoute:
    sections: list[SectionInput] = []
    for sec in raw.get("sections", []):
        poly = sec.get("polyline")
        summary = sec.get("summary") or {}
        if not poly or "length" not in summary or "duration" not in summary:
            raise UpstreamError("HERE returned a route without geometry or summary.")
        coords = [(pt[0], pt[1]) for pt in flexpolyline.decode(poly)]
        spans = [
            (int(s["offset"]), float(s["duration"]))
            for s in sec.get("spans") or []
            if "offset" in s and "duration" in s
        ]
        sections.append(
            SectionInput(
                coords=coords,
                length_mi=meters_to_miles(float(summary["length"])),
                duration_s=float(summary["duration"]),
                spans=spans,
            )
        )
    if not sections:
        raise UpstreamError("HERE returned a route with no sections.")
    track = build_track(sections)
    return CandidateRoute(
        track=track,
        distance_mi=sum(s.length_mi for s in sections),
        duration_s=sum(s.duration_s for s in sections),
        source=source,
        here_id=str(raw.get("id", "")),
    )


def fetch_routes(
    origin: Place,
    destination: Place,
    departure: datetime,
    load_lb: float,
    *,
    alternatives: int,
    via: LatLonT | None = None,
    source: str = "router",
) -> list[CandidateRoute]:
    if not settings.HERE_API_KEY:
        raise UpstreamError("HERE_API_KEY is not configured on the server.")
    params: list[tuple[str, str]] = [
        ("transportMode", "truck"),
        ("origin", _fmt((origin.lat, origin.lon))),
        ("destination", _fmt((destination.lat, destination.lon))),
        ("departureTime", departure.isoformat()),
        ("alternatives", str(alternatives)),
        ("return", "polyline,summary"),
        ("spans", "length,duration,speedLimit"),
        ("vehicle[grossWeight]", str(gross_weight_kg(load_lb))),
    ]
    if via is not None:
        params.append(("via", f"{_fmt(via)}!passThrough=true"))
    params.append(("apiKey", settings.HERE_API_KEY))

    status, payload = get_json(settings.HERE_ROUTES_URL, params, provider=PROVIDER)
    return [_parse_route(r, source) for r in _routes_or_raise(status, payload)]


class RateLimited(UpstreamError):
    """HERE answered 429. Not retried: there is no deliberate backoff policy (C1)."""


def _routes_or_raise(status: int, payload: object) -> list[dict]:
    """Classify a HERE response (C1). Only a genuine no-route result becomes NO_ROUTE.

    Shapes confirmed from real responses (tests/fixtures/here_no_route.json,
    here_bad_request.json):
      no route -> HTTP 200, "routes": [], notices[].code == "noRouteFound"
      4xx      -> {"title", "status", "code", "cause", "action", "correlationId"}
    5xx and timeouts never reach here: get_json retries once, then raises.
    """
    # HERE's `title` explains a 4xx; it never contains the key.
    title = payload.get("title") if isinstance(payload, dict) else None
    detail = f" ({title})" if title else ""
    if status in (401, 403):
        raise UpstreamError("HERE rejected the API key.")
    if status == 429:
        raise RateLimited("The routing service is rate-limiting requests. Please try again in a minute.")
    if status >= 400:
        raise UpstreamError(f"The routing service could not process this request{detail}.")
    if not isinstance(payload, dict):
        raise UpstreamError("HERE returned an unreadable routing response.")
    routes = payload.get("routes") or []
    if routes:
        return routes
    notices = [n for n in payload.get("notices") or [] if isinstance(n, dict)]
    if any(n.get("code") == "noRouteFound" for n in notices):
        raise NoRoute("No truck route was found between these places.")
    reason = next((n.get("title") for n in notices if n.get("title")), None)
    raise UpstreamError(
        "HERE returned no route without saying why" + (f" ({reason})." if reason else ".")
    )


def select_distinct(candidates: list[CandidateRoute], limit: int | None = None) -> tuple[
    list[CandidateRoute], int
]:
    """Fastest-first; drop near-duplicates. Returns (kept, dropped_count)."""
    kept: list[CandidateRoute] = []
    dropped = 0
    for cand in sorted(candidates, key=lambda c: c.duration_s):
        if any(is_near_duplicate(cand.fp, k.fp) for k in kept):
            dropped += 1
            continue
        kept.append(cand)
    return (kept[:limit] if limit else kept), dropped


def via_points(base: Track) -> list[LatLonT]:
    """Deterministic via points left and right of the route midpoint, nearest first.

    Offsets that clamp to the same distance are tried once, so the attempt budget
    is at most 2 x len(VIA_OFFSET_FRACTIONS).
    """
    total = base.distance_mi
    (mid, _) = base.locate(total / 2)
    (before, _) = base.locate(total * 0.45)
    (after, _) = base.locate(total * 0.55)
    heading = initial_bearing_deg(before, after)
    dists = dict.fromkeys(
        round(min(max(total * f, VIA_MIN_MI), VIA_MAX_MI), 3) for f in VIA_OFFSET_FRACTIONS
    )
    return [
        destination_point(mid, heading + side, dist) for dist in dists for side in (90.0, -90.0)
    ]


@dataclass
class RoutePlan:
    routes: list[CandidateRoute]
    notes: list[str]


def plan_routes(
    origin: Place, destination: Place, departure: datetime, load_lb: float
) -> RoutePlan:
    notes: list[str] = []
    # The first call decides the trip: NoRoute, rate limits and outages propagate.
    raw = fetch_routes(origin, destination, departure, load_lb, alternatives=MAX_ALTERNATIVES)

    distinct, dropped = select_distinct(raw)
    msg = f"Router returned {len(raw)} route{'s' if len(raw) != 1 else ''}"
    if dropped:
        msg += f"; {dropped} near-duplicate{'s' if dropped != 1 else ''} dropped"
    notes.append(msg + ".")

    search = _DetourSearch()
    if len(distinct) < TARGET_ROUTES:
        search.run(distinct, origin, destination, departure, load_lb)
        notes.append(search.note())

    distinct.sort(key=lambda c: c.duration_s)
    kept = distinct[:TARGET_ROUTES]
    if len(kept) < TARGET_ROUTES:
        # What we know is what HERE returned, not what roads exist (C3).
        n = len(kept)
        notes.append(
            f"Showing {n} route{'s' if n != 1 else ''}: HERE did not return a "
            f"{'second' if n == 1 else 'third'} distinct route from its alternatives or "
            f"{search.attempts} via-point detour{'s' if search.attempts != 1 else ''}. "
            "Another road may still exist."
        )
    return RoutePlan(routes=kept, notes=notes)


@dataclass
class _DetourSearch:
    """Bounded via-point fallback with a record of what happened (C3).

    Never fabricates a route; failed or empty attempts are counted, not treated
    as proof that no road exists. A rate limit stops the search early.
    """

    attempts: int = 0
    added: int = 0
    duplicates: int = 0
    no_route: int = 0
    failed: int = 0
    rate_limited: bool = False

    def run(self, distinct: list[CandidateRoute], origin: Place, destination: Place,
            departure: datetime, load_lb: float) -> None:
        for via in via_points(distinct[0].track):
            if len(distinct) >= TARGET_ROUTES:
                return
            self.attempts += 1
            try:
                detours = fetch_routes(
                    origin, destination, departure, load_lb,
                    alternatives=0, via=via, source="via",
                )
            except NoRoute:
                self.no_route += 1
                continue
            except RateLimited:
                self.rate_limited = True
                return
            except (UpstreamError, UpstreamTimeout):
                self.failed += 1
                continue
            for cand in detours:
                if len(distinct) >= TARGET_ROUTES:
                    break
                if any(is_near_duplicate(cand.fp, k.fp) for k in distinct):
                    self.duplicates += 1
                    continue
                distinct.append(cand)
                self.added += 1

    def note(self) -> str:
        parts = [f"{self.added} added"]
        if self.duplicates:
            parts.append(f"{self.duplicates} near-duplicate{'s' if self.duplicates != 1 else ''} skipped")
        if self.no_route:
            parts.append(f"{self.no_route} with no route")
        if self.failed:
            parts.append(f"{self.failed} failed")
        text = (
            f"Tried {self.attempts} via-point detour{'s' if self.attempts != 1 else ''}: "
            + ", ".join(parts) + "."
        )
        if self.rate_limited:
            text += " Detour search stopped early: the routing service is rate-limiting requests."
        return text
