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
    3. If fewer than 3 remain, request detours through a via point offset to
       either side of the fastest route's midpoint, and keep distinct ones.
    4. Keep the 3 fastest distinct routes. Fewer only when no third distinct
       road was found; `notes` then says why.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

import flexpolyline
from django.conf import settings

from api.errors import NoRoute, UpstreamError
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
# on both sides of the midpoint. Clamped to [VIA_MIN_MI, VIA_MAX_MI].
VIA_OFFSET_FRACTIONS = (0.15, 0.30)
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
    if status in (401, 403):
        raise UpstreamError("HERE rejected the API key.")
    if status >= 400:
        # HERE explains 4xx in `title`/`cause`; neither contains the key.
        title = payload.get("title") if isinstance(payload, dict) else None
        raise NoRoute(f"The router rejected this trip{f': {title}' if title else ''}.")
    routes = payload.get("routes") or []
    return [_parse_route(r, source) for r in routes]


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
    """Candidate via points left and right of the route midpoint."""
    total = base.distance_mi
    (mid, _) = base.locate(total / 2)
    (before, _) = base.locate(total * 0.45)
    (after, _) = base.locate(total * 0.55)
    heading = initial_bearing_deg(before, after)
    points: list[LatLonT] = []
    for frac in VIA_OFFSET_FRACTIONS:
        dist = min(max(total * frac, VIA_MIN_MI), VIA_MAX_MI)
        for side in (90.0, -90.0):
            points.append(destination_point(mid, heading + side, dist))
    return points


@dataclass
class RoutePlan:
    routes: list[CandidateRoute]
    notes: list[str]


def plan_routes(
    origin: Place, destination: Place, departure: datetime, load_lb: float
) -> RoutePlan:
    notes: list[str] = []
    raw = fetch_routes(origin, destination, departure, load_lb, alternatives=MAX_ALTERNATIVES)
    if not raw:
        raise NoRoute("No truck route was found between these places.")

    distinct, dropped = select_distinct(raw)
    msg = f"Router returned {len(raw)} route{'s' if len(raw) != 1 else ''}"
    if dropped:
        msg += f"; {dropped} near-duplicate{'s' if dropped != 1 else ''} dropped"
    notes.append(msg + ".")

    if len(distinct) < TARGET_ROUTES:
        base = distinct[0].track
        added = 0
        for via in via_points(base):
            if len(distinct) >= TARGET_ROUTES:
                break
            try:
                detours = fetch_routes(
                    origin, destination, departure, load_lb,
                    alternatives=0, via=via, source="via",
                )
            except NoRoute:
                continue
            for cand in detours:
                if len(distinct) >= TARGET_ROUTES:
                    break
                if any(is_near_duplicate(cand.fp, k.fp) for k in distinct):
                    continue
                distinct.append(cand)
                added += 1
        if added:
            notes.append(
                f"Added {added} via-point detour{'s' if added != 1 else ''} "
                "to reach 3 distinct routes."
            )

    distinct.sort(key=lambda c: c.duration_s)
    kept = distinct[:TARGET_ROUTES]
    if len(kept) < TARGET_ROUTES:
        notes.append(
            f"Only {len(kept)} distinct truck route{'s' if len(kept) != 1 else ''} "
            "exist between these places; no third road could be found, "
            "even through detours either side of the route."
        )
    return RoutePlan(routes=kept, notes=notes)
