"""CORE-1 route selection: Testing strategy §2.2a."""

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from freezegun import freeze_time

from api.errors import NoRoute, UpstreamError, UpstreamTimeout
from geo import routes as routes_mod
from geo.routes import gross_weight_kg, plan_routes, select_distinct
from routing.overlap import is_near_duplicate, shared_fraction
from routing.track import destination_point
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


# --- C2: metre-based overlap ----------------------------------------------------


def _parallel(coords, metres: float):
    """The same line moved `metres` to the north (a separate road alongside)."""
    return [destination_point(p, 0.0, metres / 1609.344) for p in coords]


def test_same_road_shifted_and_simplified_is_near_duplicate():
    base = straight_line(MILES, step_mi=0.2)
    shifted = _parallel(base, 25)  # a few metres of drift between encodings
    simplified = shifted[::5] + [shifted[-1]]  # far fewer vertices
    assert shared_fraction(track_for(base), track_for(simplified)) > 0.99
    assert is_near_duplicate(track_for(base), track_for(simplified))


@pytest.mark.parametrize("metres", [300, 450, 600])
def test_parallel_distinct_roads_hundreds_of_metres_apart_are_not_shared(metres):
    base = straight_line(MILES, step_mi=0.5)
    other = _parallel(base, metres)
    assert shared_fraction(track_for(base), track_for(other)) < 0.05


def test_tolerance_is_metres_at_every_latitude():
    # 150 m apart must stay distinct at 25 N and at 48 N alike (degree grids could not do this).
    for lat in (25.0, 48.0):
        base = straight_line(50, start=(lat, -100.0), step_mi=0.5)
        assert shared_fraction(track_for(base), track_for(_parallel(base, 150))) < 0.05
        assert shared_fraction(track_for(base), track_for(_parallel(base, 40))) > 0.99


def _diverging(share: float):
    """Same road for `share` of 20 mi, then a separate road 2 km to the north."""
    a = straight_line(20, step_mi=0.25)
    cut = round(len(a) * share)
    b = a[:cut] + _parallel(a[cut:], 2000)
    return track_for(a), track_for(b)


def test_sharing_most_but_not_enough_stays_distinct():
    a, b = _diverging(0.80)
    assert 0.7 < shared_fraction(a, b) < 0.86
    assert not is_near_duplicate(a, b)


def test_sharing_nearly_all_is_near_duplicate():
    a, b = _diverging(0.96)
    assert shared_fraction(a, b) > 0.93
    assert is_near_duplicate(a, b)


def test_shared_fraction_is_symmetric():
    a, b = _diverging(0.6)
    assert shared_fraction(a, b) == pytest.approx(shared_fraction(b, a), abs=0.01)


def _fp(pieces):
    """Hand-built footprints: a road along y=0 and pieces with exact lengths."""
    from routing.overlap import Footprint, Piece

    road = Footprint(pieces=[Piece((0.0, 0.0), 100.0, 1.0)], segments=[((0.0, 0.0), (1e6, 0.0))],
                     length_mi=1.0, cell=200.0)
    a = Footprint(
        pieces=[Piece((1000.0 * i, y), 100.0, length) for i, (y, length) in enumerate(pieces)],
        segments=[], length_mi=sum(length for _, length in pieces), cell=200.0,
    )
    return a, road


@pytest.mark.parametrize(
    "off_road_mi, dup",
    [(1.0, False), (0.99, True), (1.01, False)],
    ids=["exactly-90pct", "just-over-90pct", "just-under-90pct"],
)
def test_exactly_90_percent_is_not_more_than_90(off_road_mi, dup):
    # 9 mi on the road plus one piece 5 km off it.
    a, road = _fp([(0.0, 1.0)] * 9 + [(5000.0, off_road_mi)])
    assert is_near_duplicate(a, road) is dup
    expected = 9 / (9 + off_road_mi)
    assert shared_fraction(a, road) == pytest.approx(expected)


def test_three_genuinely_distinct_candidates_survive_selection():
    def cand(coords, minutes, rid):
        return routes_mod.CandidateRoute(
            track=track_for(coords), distance_mi=MILES, duration_s=minutes * 60,
            source="router", here_id=rid,
        )

    base = straight_line(MILES, step_mi=0.5)
    cands = [
        cand(base, 100, "a"),
        cand(_parallel(base, 20), 100.5, "a-again"),  # same road, re-encoded
        cand(_parallel(base, 500), 101, "b"),  # separate road 500 m away
        cand(bowed(MILES, 20), 120, "c"),
    ]
    kept, dropped = select_distinct(cands)
    assert [k.here_id for k in kept] == ["a", "b", "c"]
    assert dropped == 1


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
        httpx.Response(200, json={"routes": [_route(0.01, f"v{i}", 101)]}) for i in range(6)
    ]
    plan = plan_routes(ORIGIN, DEST, DEP, 20_000)
    assert len(plan.routes) == 1
    assert route.call_count == 7  # 1 + 6 via attempts (3 offsets x 2 sides): budget exhausted
    assert "Tried 6 via-point detours: 0 added, 6 near-duplicates skipped." in plan.notes
    last = plan.notes[-1]
    assert "HERE did not return a second distinct route" in last
    assert "may still exist" in last
    assert "no third road" not in last and "exist between" not in last


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
    assert "Tried 2 via-point detours: 1 added, 1 failed." in plan.notes


@respx.mock
def test_via_errors_and_no_route_are_counted_not_proof():
    route = respx.get(ROUTES_URL)
    route.side_effect = [
        httpx.Response(200, json={"routes": [_route(0, "a", 100), _route(30, "b", 120)]}),
        httpx.Response(200, json={"routes": [], "notices": [{"code": "noRouteFound"}]}),
        httpx.ReadTimeout("slow"),
        httpx.ReadTimeout("slow"),  # the retry of that attempt
        httpx.Response(503),
        httpx.Response(503),
        httpx.Response(200, json={"routes": [_route(0.01, "dup", 101)]}),
        httpx.Response(200, json={"routes": [_route(-30, "c", 130)]}),
    ]
    plan = plan_routes(ORIGIN, DEST, DEP, 20_000)
    assert [r.here_id for r in plan.routes] == ["a", "b", "c"]
    assert (
        "Tried 5 via-point detours: 1 added, 1 near-duplicate skipped, 1 with no route, 2 failed."
        in plan.notes
    )


@respx.mock
def test_rate_limit_during_detours_stops_search_and_says_so():
    route = respx.get(ROUTES_URL)
    route.side_effect = [
        httpx.Response(200, json={"routes": [_route(0, "a", 100), _route(30, "b", 120)]}),
        httpx.Response(429, json={"title": "Too Many Requests", "status": 429}),
    ]
    plan = plan_routes(ORIGIN, DEST, DEP, 20_000)
    assert route.call_count == 2  # no blind retry, no further attempts
    assert [r.here_id for r in plan.routes] == ["a", "b"]
    assert any("stopped early" in n and "rate-limiting" in n for n in plan.notes)
    assert "HERE did not return a third distinct route" in plan.notes[-1]


# --- C1: HERE error classification ---------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"


def _recorded(name: str) -> httpx.Response:
    rec = json.loads((FIXTURES / name).read_text())
    return httpx.Response(rec["status"], json=rec["body"])


@respx.mock
def test_recorded_no_route_response_is_no_route():
    respx.get(ROUTES_URL).mock(return_value=_recorded("here_no_route.json"))
    with pytest.raises(NoRoute):
        plan_routes(ORIGIN, DEST, DEP, 20_000)


@respx.mock
def test_recorded_bad_request_is_upstream_error_not_no_route():
    respx.get(ROUTES_URL).mock(return_value=_recorded("here_bad_request.json"))
    with pytest.raises(UpstreamError) as exc:
        plan_routes(ORIGIN, DEST, DEP, 20_000)
    assert not isinstance(exc.value, NoRoute)
    assert "Malformed request" in exc.value.message


@respx.mock
@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_is_upstream_error(status):
    respx.get(ROUTES_URL).mock(return_value=httpx.Response(status, json={"title": "Unauthorized"}))
    with pytest.raises(UpstreamError, match="API key"):
        plan_routes(ORIGIN, DEST, DEP, 20_000)


@respx.mock
def test_429_is_rate_limit_error_and_not_retried():
    route = respx.get(ROUTES_URL).mock(
        return_value=httpx.Response(429, json={"title": "Too Many Requests", "status": 429})
    )
    with pytest.raises(routes_mod.RateLimited) as exc:
        plan_routes(ORIGIN, DEST, DEP, 20_000)
    assert isinstance(exc.value, UpstreamError) and not isinstance(exc.value, NoRoute)
    assert route.call_count == 1


@respx.mock
@pytest.mark.parametrize("status", [400, 404, 422])
def test_other_4xx_is_upstream_error(status):
    respx.get(ROUTES_URL).mock(return_value=httpx.Response(status, json={"title": "Nope"}))
    with pytest.raises(UpstreamError) as exc:
        plan_routes(ORIGIN, DEST, DEP, 20_000)
    assert not isinstance(exc.value, NoRoute)


@respx.mock
def test_empty_routes_without_no_route_notice_is_upstream_error():
    respx.get(ROUTES_URL).mock(return_value=httpx.Response(
        200, json={"routes": [], "notices": [{"code": "somethingElse", "title": "Odd"}]}
    ))
    with pytest.raises(UpstreamError, match="Odd"):
        plan_routes(ORIGIN, DEST, DEP, 20_000)


@respx.mock
@freeze_time("2026-11-20T12:00:00Z")
def test_no_route_maps_to_422_no_route_through_the_api(client):
    respx.get(ROUTES_URL).mock(return_value=_recorded("here_no_route.json"))
    r = _analyze(client)
    assert r.status_code == 422 and r.json()["error"]["code"] == "NO_ROUTE"


@respx.mock
@freeze_time("2026-11-20T12:00:00Z")
def test_rate_limit_maps_to_502_upstream_error_through_the_api(client):
    respx.get(ROUTES_URL).mock(return_value=httpx.Response(429, json={"status": 429}))
    r = _analyze(client)
    assert r.status_code == 502 and r.json()["error"]["code"] == "UPSTREAM_ERROR"


@pytest.fixture
def client():
    from rest_framework.test import APIClient

    return APIClient()


def _analyze(client):
    return client.post(
        "/api/analyze",
        {
            "origin": {"label": "O", "lat": ORIGIN.lat, "lon": ORIGIN.lon},
            "destination": {"label": "D", "lat": DEST.lat, "lon": DEST.lon},
            "departure_time": "2026-11-21T13:00:00Z",
            "load_weight_lb": 20000,
            "interval_mi": 25,
        },
        format="json",
    )


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
