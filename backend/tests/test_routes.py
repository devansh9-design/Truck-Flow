"""CORE-1 route selection: Testing strategy §2.2a."""

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from api.errors import NoRoute, UpstreamError, UpstreamTimeout
from geo import routes as routes_mod
from geo.routes import gross_weight_kg, plan_routes, select_distinct
from routing.overlap import shared_fraction
from truckrisk_schemas import Place

from .helpers import bowed, here_route, straight_line, track_for

ROUTES_URL = "https://router.test/v8/routes"
ORIGIN = Place(label="O", lat=39.0, lon=-100.0)
DEST = Place(label="D", lat=39.0, lon=-98.0)
DEP = datetime(2026, 11, 21, 13, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _settings(settings, monkeypatch):
    settings.HERE_API_KEY = "test-key"
    settings.HERE_ROUTES_URL = ROUTES_URL
    settings.TRUCK_TARE_LB = 35_000
    monkeypatch.setattr("geo.http.RETRY_BACKOFF_S", 0)


MILES = 107.0  # ~ 2 degrees of longitude at 39 N


def _route(bow_mi: float, rid: str, minutes: float) -> dict:
    coords = bowed(MILES, bow_mi) if bow_mi else straight_line(MILES)
    return here_route(coords, rid=rid, duration_s=minutes * 60)


def _query(call) -> dict[str, list[str]]:
    return parse_qs(urlparse(str(call.request.url)).query)


# --- overlap -------------------------------------------------------------------


def test_same_road_is_fully_shared_and_distinct_roads_are_not():
    a = track_for(straight_line(MILES))
    a_shifted = track_for([(lat + 0.0005, lon) for lat, lon in straight_line(MILES)])  # ~55 m
    far = track_for(bowed(MILES, 30))
    assert shared_fraction(a, a_shifted) > 0.99
    assert shared_fraction(a, far) < 0.5


def test_short_detour_counts_as_near_duplicate():
    base = straight_line(MILES, step_mi=0.5)
    # Leave the road for ~4% of the trip.
    detour = list(base)
    for i in range(100, 108):
        lat, lon = detour[i]
        detour[i] = (lat + 0.05, lon)
    assert shared_fraction(track_for(base), track_for(detour)) > 0.9


# --- selection -----------------------------------------------------------------


@respx.mock
def test_five_alternatives_three_kept_fastest_distinct_first():
    body = {
        "routes": [
            _route(0, "fast", 100),
            _route(0.01, "fast-dup", 101),  # same road, slightly slower -> dropped
            _route(25, "mid", 120),
            _route(-25, "mid-other-side", 125),
            _route(50, "far", 140),
            _route(-50, "far-other-side", 150),
        ]
    }
    respx.get(ROUTES_URL).mock(return_value=httpx.Response(200, json=body))
    plan = plan_routes(ORIGIN, DEST, DEP, 20_000)
    assert [r.here_id for r in plan.routes] == ["fast", "mid", "mid-other-side"]
    assert [r.duration_s for r in plan.routes] == sorted(r.duration_s for r in plan.routes)
    assert "1 near-duplicate dropped" in plan.notes[0]
    assert respx.calls.call_count == 1  # no via fallback needed


@respx.mock
def test_near_duplicates_dropped():
    routes = [_route(0, "a", 100), _route(0.02, "b", 105), _route(30, "c", 130)]
    distinct, dropped = select_distinct([routes_mod._parse_route(r, "router") for r in routes])
    assert [c.here_id for c in distinct] == ["a", "c"]
    assert dropped == 1


@respx.mock
def test_via_fallback_until_three_distinct():
    route = respx.get(ROUTES_URL)
    route.side_effect = [
        httpx.Response(200, json={"routes": [_route(0, "only", 100), _route(0.01, "dup", 101)]}),
        httpx.Response(200, json={"routes": [_route(30, "via-left", 130)]}),
        httpx.Response(200, json={"routes": [_route(-30, "via-right", 135)]}),
    ]
    plan = plan_routes(ORIGIN, DEST, DEP, 20_000)
    assert [r.here_id for r in plan.routes] == ["only", "via-left", "via-right"]
    assert [r.source for r in plan.routes] == ["router", "via", "via"]
    assert route.call_count == 3
    first, second = _query(route.calls[0]), _query(route.calls[1])
    assert first["alternatives"] == ["5"] and "via" not in first
    assert second["alternatives"] == ["0"]
    assert second["via"][0].endswith("!passThrough=true")
    assert any("via-point" in n for n in plan.notes)


@respx.mock
def test_via_detour_that_duplicates_is_skipped_and_fewer_routes_noted():
    route = respx.get(ROUTES_URL)
    # Every via request snaps back onto the only road.
    route.side_effect = [httpx.Response(200, json={"routes": [_route(0, "only", 100)]})] + [
        httpx.Response(200, json={"routes": [_route(0.01, f"v{i}", 101)]}) for i in range(4)
    ]
    plan = plan_routes(ORIGIN, DEST, DEP, 20_000)
    assert len(plan.routes) == 1
    assert route.call_count == 5  # 1 + 4 via attempts (2 offsets x 2 sides)
    assert "no third road" in plan.notes[-1]


@respx.mock
def test_via_request_rejected_by_router_is_skipped():
    route = respx.get(ROUTES_URL)
    route.side_effect = [
        httpx.Response(200, json={"routes": [_route(0, "a", 100), _route(30, "b", 120)]}),
        httpx.Response(400, json={"title": "Invalid via", "status": 400}),
        httpx.Response(200, json={"routes": [_route(-30, "c", 130)]}),
    ]
    plan = plan_routes(ORIGIN, DEST, DEP, 20_000)
    assert [r.here_id for r in plan.routes] == ["a", "b", "c"]


@respx.mock
def test_gross_weight_sent_to_here_is_load_plus_tare_in_kg():
    route = respx.get(ROUTES_URL).mock(
        return_value=httpx.Response(
            200, json={"routes": [_route(0, "a", 100), _route(30, "b", 120), _route(-30, "c", 125)]}
        )
    )
    plan_routes(ORIGIN, DEST, DEP, 42_000)
    q = _query(route.calls[0])
    assert q["vehicle[grossWeight]"] == [str(round((42_000 + 35_000) * 0.45359237))]
    assert q["transportMode"] == ["truck"]
    assert q["return"] == ["polyline,summary"]
    assert q["spans"] == ["length,duration,speedLimit"]
    assert q["departureTime"] == ["2026-11-21T13:00:00+00:00"]


def test_gross_weight_uses_configured_tare(settings):
    settings.TRUCK_TARE_LB = 30_000
    assert gross_weight_kg(10_000) == round(40_000 * 0.45359237)


@respx.mock
def test_no_routes_raises_no_route():
    respx.get(ROUTES_URL).mock(
        return_value=httpx.Response(200, json={"routes": [], "notices": [{"code": "noRouteFound"}]})
    )
    with pytest.raises(NoRoute):
        plan_routes(ORIGIN, DEST, DEP, 20_000)


@respx.mock
def test_upstream_5xx_retried_once_then_502():
    route = respx.get(ROUTES_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(UpstreamError):
        plan_routes(ORIGIN, DEST, DEP, 20_000)
    assert route.call_count == 2


@respx.mock
def test_upstream_timeout_retried_once_then_504():
    route = respx.get(ROUTES_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(UpstreamTimeout):
        plan_routes(ORIGIN, DEST, DEP, 20_000)
    assert route.call_count == 2


@respx.mock
def test_error_messages_never_contain_api_key():
    respx.get(ROUTES_URL).mock(side_effect=httpx.ConnectError("boom https://x?apiKey=test-key"))
    with pytest.raises(UpstreamError) as exc:
        plan_routes(ORIGIN, DEST, DEP, 20_000)
    assert "test-key" not in str(exc.value)
    assert exc.value.__cause__ is None and exc.value.__context__ is None


def test_route_distance_and_duration_come_from_router_summary():
    raw = here_route(straight_line(MILES), length_mi=110.0, duration_s=7200)
    cand = routes_mod._parse_route(raw, "router")
    assert cand.distance_mi == pytest.approx(110.0, abs=0.01)
    assert cand.duration_s == 7200
    assert cand.track.distance_mi == pytest.approx(110.0, abs=0.01)


RECORDED = __import__("pathlib").Path(__file__).parent / "fixtures" / "here_routes_denver_slc.json"


@pytest.mark.skipif(not RECORDED.exists(), reason="run scripts/record_here_fixtures.py to record")
def test_recorded_here_response_parses_and_selects():
    import json

    body = json.loads(RECORDED.read_text(encoding="utf-8"))
    cands = [routes_mod._parse_route(r, "router") for r in body["routes"]]
    assert cands, "recorded response has no routes"
    for c in cands:
        assert c.distance_mi > 300 and c.duration_s > 3600
        assert c.track.distance_mi == pytest.approx(c.distance_mi, rel=1e-6)
        assert c.track.duration_s == pytest.approx(c.duration_s, rel=1e-6)
    distinct, _ = select_distinct(cands)
    assert 1 <= len(distinct) <= len(cands)


@pytest.mark.skipif(not RECORDED.exists(), reason="run scripts/record_here_fixtures.py to record")
def test_recorded_eta_follows_span_durations_not_constant_speed():
    """D7: elapsed time at each span start equals the sum of HERE's span durations before it."""
    import json

    raw = json.loads(RECORDED.read_text(encoding="utf-8"))["routes"][0]
    sec = raw["sections"][0]
    spans = sec["spans"]
    assert len(spans) > 1, "spans must split the route (spans=...,speedLimit)"
    cand = routes_mod._parse_route(raw, "router")
    scale = sec["summary"]["duration"] / sum(s["duration"] for s in spans)
    elapsed = 0.0
    for span in spans:
        assert cand.track.cum_s[span["offset"]] == pytest.approx(elapsed * scale, abs=1.0)
        elapsed += span["duration"]
    # Not a constant-speed spread: some span differs from the route-average pace by > 20%.
    avg = sec["summary"]["length"] / sec["summary"]["duration"]
    assert any(abs(s["length"] / s["duration"] - avg) / avg > 0.2 for s in spans if s["duration"])
