"""Public API: health, geocode, validation, and the Chunk 1 debug route endpoint."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from django.core.cache import cache
from freezegun import freeze_time
from rest_framework.test import APIClient

from .helpers import bowed, here_route, straight_line

GEOCODE_URL = "https://geocode.test/v1/geocode"
ROUTES_URL = "https://router.test/v8/routes"
RISK_URL = "http://risk.test"
NOW = "2026-11-20T04:00:00Z"


@pytest.fixture(autouse=True)
def _settings(settings, monkeypatch):
    settings.DEBUG = True
    settings.HERE_API_KEY = "test-key"
    settings.HERE_GEOCODE_URL = GEOCODE_URL
    settings.HERE_ROUTES_URL = ROUTES_URL
    settings.RISK_ENGINE_URL = RISK_URL
    monkeypatch.setattr("geo.http.RETRY_BACKOFF_S", 0)
    cache.clear()


@pytest.fixture
def client():
    return APIClient()


def _geo_item(label, lat, lng):
    return {"title": label, "resultType": "locality", "address": {"label": label},
            "position": {"lat": lat, "lng": lng}}


def _geocode_side_effect(request):
    q = request.url.params["q"].lower()
    if "denver" in q:
        return httpx.Response(200, json={"items": [_geo_item("Denver, CO, United States", 39.0, -100.0)]})
    if "hays" in q:
        return httpx.Response(200, json={"items": [_geo_item("Hays, KS, United States", 39.0, -98.0)]})
    return httpx.Response(200, json={"items": []})


def _body(**over):
    body = {
        "origin": "Denver, CO",
        "destination": "Hays, KS",
        "departure_time": "2026-11-21T06:00:00-07:00",
        "load_weight_lb": 42000,
        "interval_mi": 25,
    }
    body.update(over)
    return body


# --- health ------------------------------------------------------------------


@respx.mock
@freeze_time(NOW)
def test_health_reports_risk_engine_ok(client):
    respx.get(f"{RISK_URL}/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "risk_engine": "ok", "time": NOW}


@respx.mock
def test_health_reports_risk_engine_down(client):
    respx.get(f"{RISK_URL}/health").mock(side_effect=httpx.ConnectError("refused"))
    assert client.get("/api/health").json()["risk_engine"] == "down"


# --- geocode -----------------------------------------------------------------


@respx.mock
def test_geocode_maps_here_items_and_caches(client):
    route = respx.get(GEOCODE_URL).mock(side_effect=_geocode_side_effect)
    r = client.get("/api/geocode", {"q": "Denver"})
    assert r.status_code == 200
    assert r.json() == {"results": [{"label": "Denver, CO, United States", "lat": 39.0, "lon": -100.0}]}
    client.get("/api/geocode", {"q": "  denver "})
    assert route.call_count == 1  # normalised query hits the cache
    assert route.calls[0].request.url.params["limit"] == "5"


@respx.mock
def test_geocode_returns_at_most_five(client):
    items = [_geo_item(f"P{i}", 1.0, 1.0) for i in range(8)]
    respx.get(GEOCODE_URL).mock(return_value=httpx.Response(200, json={"items": items}))
    assert len(client.get("/api/geocode", {"q": "Springfield"}).json()["results"]) == 5


@pytest.mark.parametrize("q", ["", "a", "x" * 201])
def test_geocode_validates_length(client, q):
    r = client.get("/api/geocode", {"q": q})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_geocode_requires_q(client):
    r = client.get("/api/geocode")
    assert r.status_code == 400 and r.json()["error"]["details"] == {"field": "q"}


@respx.mock
def test_geocode_upstream_failure_is_502_without_key(client):
    respx.get(GEOCODE_URL).mock(return_value=httpx.Response(500))
    r = client.get("/api/geocode", {"q": "Denver"})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "UPSTREAM_ERROR"
    assert "test-key" not in r.content.decode()


# --- debug routes (Chunk 1 core check) ---------------------------------------


def _three_routes():
    return {
        "routes": [
            here_route(straight_line(107), rid="a", duration_s=6000),
            here_route(bowed(107, 30), rid="b", duration_s=7000),
            here_route(bowed(107, -30), rid="c", duration_s=7500),
        ]
    }


@respx.mock
@freeze_time(NOW)
def test_debug_routes_returns_three_routes_with_checkpoints_and_etas(client):
    respx.get(GEOCODE_URL).mock(side_effect=_geocode_side_effect)
    respx.get(ROUTES_URL).mock(return_value=httpx.Response(200, json=_three_routes()))
    r = client.post("/api/debug/routes", _body(), format="json")
    assert r.status_code == 200, r.content
    data = r.json()

    assert data["trip"]["departure_time"] == "2026-11-21T13:00:00Z"
    assert data["trip"]["origin"]["label"] == "Denver, CO, United States"
    assert len(data["routes"]) == 3
    assert [rt["id"] for rt in data["routes"]] == ["r0", "r1", "r2"]
    assert len(data["corridor"]["bbox"]) == 4

    dep = datetime(2026, 11, 21, 13, tzinfo=UTC)
    for rt in data["routes"]:
        cps = rt["checkpoints"]
        assert cps[0]["mile"] == 0.0 and cps[0]["eta"] == "2026-11-21T13:00:00Z"
        assert cps[-1]["mile"] == pytest.approx(rt["distance_mi"], abs=0.1)
        assert [c["mile"] for c in cps[:-1]] == [25.0 * i for i in range(len(cps) - 1)]
        etas = [datetime.fromisoformat(c["eta"]) for c in cps]
        assert etas == sorted(etas)
        for c in cps:
            assert c["id"] == f"{rt['id']}-c{c['index']}"
            fh = datetime.fromisoformat(c["forecast_hour"])
            assert fh.minute == 0 and abs(fh - datetime.fromisoformat(c["eta"])) <= timedelta(minutes=30)
        arrival = datetime.fromisoformat(rt["arrival_time"])
        assert arrival == dep + timedelta(seconds=rt["duration_s"])
        assert rt["geometry"]["type"] == "LineString"


@respx.mock
@freeze_time(NOW)
def test_debug_routes_accepts_resolved_places_without_geocoding(client):
    geo = respx.get(GEOCODE_URL)
    respx.get(ROUTES_URL).mock(return_value=httpx.Response(200, json=_three_routes()))
    body = _body(
        origin={"label": "O", "lat": 39.0, "lon": -100.0},
        destination={"label": "D", "lat": 39.0, "lon": -98.0},
    )
    assert client.post("/api/debug/routes", body, format="json").status_code == 200
    assert geo.call_count == 0


@respx.mock
@freeze_time(NOW)
def test_unknown_place_is_404(client):
    respx.get(GEOCODE_URL).mock(side_effect=_geocode_side_effect)
    r = client.post("/api/debug/routes", _body(destination="Atlantis"), format="json")
    assert r.status_code == 404
    assert r.json()["error"] == {
        "code": "PLACE_NOT_FOUND",
        "message": 'Could not find "Atlantis".',
        "details": {"field": "destination"},
    }


@respx.mock
@freeze_time(NOW)
def test_same_place_after_geocoding_is_400(client):
    respx.get(GEOCODE_URL).mock(side_effect=_geocode_side_effect)
    r = client.post("/api/debug/routes", _body(destination="Denver, Colorado"), format="json")
    assert r.status_code == 400
    assert r.json()["error"]["details"] == {"field": "destination"}


@freeze_time(NOW)
@pytest.mark.parametrize(
    "override,field",
    [
        ({"load_weight_lb": 0}, "load_weight_lb"),
        ({"load_weight_lb": 100_001}, "load_weight_lb"),
        ({"interval_mi": 20}, "interval_mi"),
        ({"departure_time": "2026-11-20T02:59:00Z"}, "departure_time"),  # > 1 h in the past
        ({"departure_time": "2026-12-07T00:00:00Z"}, "departure_time"),  # beyond 16 days
        ({"departure_time": "2026-11-21T06:00:00"}, "departure_time"),  # no offset
        ({"departure_time": "tomorrow"}, "departure_time"),
        ({"destination": "denver, co"}, "destination"),
        ({"origin": "x"}, "origin"),
    ],
)
def test_validation_errors(client, override, field):
    r = client.post("/api/debug/routes", _body(**override), format="json")
    assert r.status_code == 400, r.content
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["details"] == {"field": field}


@freeze_time(NOW)
def test_load_message_matches_contract(client):
    r = client.post("/api/debug/routes", _body(load_weight_lb=0), format="json")
    assert r.json()["error"]["message"] == "Load weight must be between 1 and 100,000 lb."


@freeze_time(NOW)
def test_departure_within_last_hour_is_allowed_by_validation(client):
    # 03:30Z is 30 min in the past: validation passes, then geocoding runs.
    with respx.mock:
        respx.get(GEOCODE_URL).mock(side_effect=_geocode_side_effect)
        respx.get(ROUTES_URL).mock(return_value=httpx.Response(200, json=_three_routes()))
        r = client.post("/api/debug/routes", _body(departure_time="2026-11-20T03:30:00Z"),
                        format="json")
    assert r.status_code == 200


def test_debug_endpoint_hidden_when_not_debug(client, settings):
    settings.DEBUG = False
    assert client.post("/api/debug/routes", _body(), format="json").status_code == 404


def test_malformed_json_uses_error_shape(client):
    r = client.post("/api/debug/routes", "{not json", content_type="application/json")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
