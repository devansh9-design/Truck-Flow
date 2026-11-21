"""POST /api/analyze end to end (HERE + Flask mocked): response shape and S1–S3 outcomes."""

import json

import httpx
import pytest
import respx
from django.core.cache import cache
from freezegun import freeze_time
from rest_framework.test import APIClient

from truckrisk_schemas import RiskLevel

from .helpers import bowed, here_route, straight_line

ROUTES_URL = "https://router.test/v8/routes"
RISK_URL = "http://risk.test"
NOW = "2026-11-20T04:00:00Z"
SCORES = {lv.value: lv.score for lv in RiskLevel}


@pytest.fixture(autouse=True)
def _settings(settings, monkeypatch):
    settings.HERE_API_KEY = "test-key"
    settings.HERE_ROUTES_URL = ROUTES_URL
    settings.RISK_ENGINE_URL = RISK_URL
    settings.RISK_ENGINE_TOKEN = "test-token"
    monkeypatch.setattr("geo.http.RETRY_BACKOFF_S", 0)
    cache.clear()


def _body(**over):
    body = {
        "origin": {"label": "O", "lat": 39.0, "lon": -100.0},
        "destination": {"label": "D", "lat": 39.0, "lon": -98.0},
        "departure_time": "2026-11-21T06:00:00-07:00",
        "load_weight_lb": 20000,
        "interval_mi": 25,
    }
    body.update(over)
    return body


def _here():
    # fastest = straight; slower ones bow north (+30 mi) and south (-30 mi)
    return {
        "routes": [
            here_route(straight_line(107), rid="straight", duration_s=6000),
            here_route(bowed(107, 30), rid="north", duration_s=7000),
            here_route(bowed(107, -30), rid="south", duration_s=7500),
        ]
    }


def _risk(level, why="scripted"):
    return {
        "level": level,
        "score": SCORES[level],
        "factors": {"wind": level, "rain": "LOW", "snow": "LOW", "load_override": None},
        "reason": "All conditions below Moderate thresholds." if level == "LOW" else why,
    }


def _flask(level_for):
    """Flask fake: level_for(route_id, checkpoint) -> level."""

    def handler(request):
        req = json.loads(request.content)
        results = []
        for cp in req["checkpoints"]:
            rid = cp["id"].split("-")[0]
            lvl = level_for(rid, cp)
            results.append({
                "id": cp["id"],
                "forecast_hour": cp["eta"][:13] + ":00:00Z" if cp["eta"].endswith("Z") else cp["eta"],
                "weather": {"wind_mph": 5.0, "rain_in_hr": 0.0, "snow_in_hr": 0.0},
                "risk": _risk(lvl),
            })
        return httpx.Response(200, json={"results": results, "meta": {"source": "open-meteo"}})

    return handler


def _post(level_for):
    with respx.mock:
        respx.get(ROUTES_URL).mock(return_value=httpx.Response(200, json=_here()))
        flask = respx.post(f"{RISK_URL}/v1/evaluate").mock(side_effect=_flask(level_for))
        r = APIClient().post("/api/analyze", _body(), format="json")
        sent = json.loads(flask.calls[0].request.content) if flask.calls else None
    return r, sent


@freeze_time(NOW)
def test_s1_calm_fastest_recommended_and_shape():
    r, sent = _post(lambda rid, cp: "LOW")
    assert r.status_code == 200, r.content
    d = r.json()
    assert len(d["routes"]) == 3
    assert [x["rank"] for x in d["routes"]] == [1, 2, 3]
    assert [x["recommended"] for x in d["routes"]] == [True, False, False]
    assert d["routes"][0]["id"] == "r0"  # the fastest
    assert d["recommendation"]["route_id"] == "r0"
    assert d["recommendation"]["decided_by"] == "duration_s"
    route = d["routes"][0]
    assert set(route) >= {"id", "rank", "recommended", "label", "distance_mi", "duration_s",
                          "arrival_time", "geometry", "checkpoints", "summary", "warnings"}
    cp = route["checkpoints"][0]
    assert set(cp) == {"id", "index", "mile", "lat", "lon", "eta", "forecast_hour", "weather", "risk"}
    assert cp["risk"]["level"] == "LOW" and cp["risk"]["score"] == 1
    assert route["summary"]["miles_by_level"]["LOW"] == pytest.approx(route["distance_mi"], abs=0.2)
    assert route["warnings"] == []
    # every checkpoint of every route went to Flask in one call, load as entered
    assert sent["load_weight_lb"] == 20000
    assert len(sent["checkpoints"]) == sum(len(x["checkpoints"]) for x in d["routes"])


@freeze_time(NOW)
def test_s2_storm_on_fastest_route_slower_clear_route_wins():
    # Storm over the fastest (r0) and the slowest (r2); only r1 is clear.
    r, _ = _post(lambda rid, cp: "SEVERE" if rid in ("r0", "r2") else "LOW")
    d = r.json()
    assert d["recommendation"]["route_id"] == "r1"
    assert d["recommendation"]["decided_by"] == "severe_mi"
    by_id = {x["id"]: x for x in d["routes"]}
    assert by_id["r0"]["summary"]["severe_mi"] > 0 and by_id["r0"]["rank"] == 2  # r0 faster than r2


@freeze_time(NOW)
def test_s3_no_travel_route_loses_on_no_travel_miles_with_warning():
    # r0 and r2 cross a No Travel point (0 Severe); r1 only has a Severe point.
    r, _ = _post(lambda rid, cp: "NO_TRAVEL" if rid in ("r0", "r2") and cp["id"].endswith("-c2") else
                 ("SEVERE" if rid == "r1" and cp["id"].endswith("-c1") else "LOW"))
    d = r.json()
    by_id = {x["id"]: x for x in d["routes"]}
    assert d["recommendation"]["route_id"] == "r1"
    assert d["recommendation"]["decided_by"] == "no_travel_mi"
    assert by_id["r0"]["warnings"] == ["NO_TRAVEL_CONDITIONS"]
    assert by_id["r0"]["summary"]["has_no_travel"] is True
    assert by_id["r0"]["summary"]["severe_mi"] == 0.0  # D3: kept separate


@freeze_time(NOW)
def test_s9_every_route_no_travel_still_recommends_with_warning():
    r, _ = _post(lambda rid, cp: "NO_TRAVEL" if cp["id"].endswith("-c0") else "LOW")
    d = r.json()
    assert d["routes"][0]["recommended"] is True
    assert all(x["warnings"] == ["NO_TRAVEL_CONDITIONS"] for x in d["routes"])


@freeze_time(NOW)
def test_beyond_horizon_from_flask_is_422():
    with respx.mock:
        respx.get(ROUTES_URL).mock(return_value=httpx.Response(200, json=_here()))
        respx.post(f"{RISK_URL}/v1/evaluate").mock(return_value=httpx.Response(
            422, json={"error": {"code": "BEYOND_FORECAST_HORIZON", "message": "Forecast ends."}}))
        r = APIClient().post("/api/analyze", _body(), format="json")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "BEYOND_FORECAST_HORIZON"


@freeze_time(NOW)
def test_flask_down_is_502_never_partial():
    with respx.mock:
        respx.get(ROUTES_URL).mock(return_value=httpx.Response(200, json=_here()))
        respx.post(f"{RISK_URL}/v1/evaluate").mock(side_effect=httpx.ConnectError("refused"))
        r = APIClient().post("/api/analyze", _body(), format="json")
    assert r.status_code == 502
    assert set(r.json()) == {"error"}


@freeze_time(NOW)
def test_validation_still_applies():
    r = APIClient().post("/api/analyze", _body(load_weight_lb=0), format="json")
    assert r.status_code == 400 and r.json()["error"]["details"] == {"field": "load_weight_lb"}


@freeze_time(NOW)
@pytest.mark.parametrize("origin", [123, ["Denver"], {"label": "x"}])
def test_malformed_place_is_a_400_not_a_crash(origin):
    r = APIClient().post("/api/analyze", _body(origin=origin), format="json")
    assert r.status_code == 400 and r.json()["error"]["details"] == {"field": "origin"}
    assert "{label, lat, lon}" in r.json()["error"]["message"]
