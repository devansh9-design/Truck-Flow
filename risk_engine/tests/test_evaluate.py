"""/v1/evaluate (B2) and the shared contract fixtures (T2, Flask side)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import create_app
from truckrisk_schemas import EvaluateResponse, Weather

from .conftest import CALM, FakeProvider

TOKEN = "test-token"
H = {"X-Internal-Token": TOKEN}
SHARED_FIXTURES = Path(__file__).resolve().parents[2] / "shared" / "fixtures"


def _client(provider):
    return create_app({"RISK_ENGINE_TOKEN": TOKEN, "FORECAST_PROVIDER": provider}).test_client()


def _cp(i, eta, lat=39.0, lon=-100.0):
    return {"id": f"r0-c{i}", "lat": lat, "lon": lon, "eta": eta}


def test_one_result_per_checkpoint_in_order(fake_provider):
    cps = [_cp(i, f"2026-11-21T{13 + i}:10:00Z", lat=39 + i * 0.3) for i in range(5)]
    r = _client(fake_provider).post("/v1/evaluate", json={"load_weight_lb": 42000, "checkpoints": cps},
                                    headers=H)
    assert r.status_code == 200, r.get_json()
    body = EvaluateResponse.model_validate(r.get_json())
    assert [x.id for x in body.results] == [c["id"] for c in cps]
    assert body.results[0].risk.reason == "All conditions below Moderate thresholds."
    assert r.get_json()["results"][0]["forecast_hour"] == "2026-11-21T13:00:00Z"
    assert body.meta["source"] == "open-meteo"


def test_eta_offset_rounded_in_utc(fake_provider):
    cps = [_cp(0, "2026-11-21T06:30:00-07:00")]  # 13:30Z -> 14:00Z
    r = _client(fake_provider).post("/v1/evaluate", json={"load_weight_lb": 1, "checkpoints": cps},
                                    headers=H)
    assert r.get_json()["results"][0]["forecast_hour"] == "2026-11-21T14:00:00Z"


def test_s8_weather_taken_at_eta_hour_not_departure():
    """Heavy snow arrives at 18:00Z; a checkpoint reached at 18:10 must see it."""

    def fn(lat, lon, hour):
        if hour >= datetime(2026, 11, 21, 18, tzinfo=UTC):
            return Weather(wind_mph=5, rain_in_hr=0, snow_in_hr=2.5)
        return CALM

    cps = [_cp(0, "2026-11-21T13:00:00Z"), _cp(1, "2026-11-21T18:10:00Z", lat=39.5)]
    r = _client(FakeProvider(fn)).post("/v1/evaluate", json={"load_weight_lb": 20000, "checkpoints": cps},
                                       headers=H)
    levels = [x["risk"]["level"] for x in r.get_json()["results"]]
    assert levels == ["LOW", "SEVERE"]


def test_load_used_as_entered():
    fn = lambda lat, lon, hour: Weather(wind_mph=46, rain_in_hr=0, snow_in_hr=0)  # noqa: E731
    cps = [_cp(0, "2026-11-21T13:00:00Z")]
    c = _client(FakeProvider(fn))
    light = c.post("/v1/evaluate", json={"load_weight_lb": 30000, "checkpoints": cps}, headers=H)
    heavy = c.post("/v1/evaluate", json={"load_weight_lb": 30001, "checkpoints": cps}, headers=H)
    assert light.get_json()["results"][0]["risk"]["level"] == "SEVERE"
    assert heavy.get_json()["results"][0]["risk"]["level"] == "NO_TRAVEL"


def test_beyond_horizon_is_422(fake_provider):
    cps = [_cp(0, "2026-11-21T13:00:00Z"), _cp(1, "2026-12-30T13:00:00Z")]
    r = _client(fake_provider).post("/v1/evaluate", json={"load_weight_lb": 1, "checkpoints": cps},
                                    headers=H)
    assert r.status_code == 422
    err = r.get_json()["error"]
    assert err["code"] == "BEYOND_FORECAST_HORIZON"
    assert err["details"] == {"checkpoint_ids": ["r0-c1"], "count": 1}


def _series_with_null(start, hours, null_hour):
    from weather import Series

    idx = {int(start.timestamp()) + 3600 * h: h for h in range(hours)}
    wind = [5.0] * hours
    wind[null_hour] = None
    return Series(index=idx, wind_mph=wind, rain_in_hr=[0.0] * hours, snow_in_hr=[0.0] * hours)


class NullAtHour:
    """Every cell has a null wind value at one hour inside the forecast range."""

    def __init__(self, null_hour):
        self.start = datetime(2026, 11, 21, 0, tzinfo=UTC)
        self.null_hour = null_hour

    def series(self, cells):
        return ({c: _series_with_null(self.start, 48, self.null_hour) for c in cells},
                {"cache_hits": 0, "fetched": 1})


def test_null_weather_inside_forecast_is_502_not_horizon():
    cps = [_cp(0, "2026-11-21T10:00:00Z"), _cp(1, "2026-11-21T13:00:00Z")]
    r = _client(NullAtHour(13)).post("/v1/evaluate", json={"load_weight_lb": 1, "checkpoints": cps},
                                     headers=H)
    assert r.status_code == 502
    err = r.get_json()["error"]
    assert err["code"] == "UPSTREAM_ERROR"
    assert "wind" in err["message"]
    assert "results" not in r.get_json()  # all or nothing: no partial analysis


def test_null_at_an_hour_no_checkpoint_needs_is_ignored():
    cps = [_cp(0, "2026-11-21T10:00:00Z")]
    r = _client(NullAtHour(13)).post("/v1/evaluate", json={"load_weight_lb": 1, "checkpoints": cps},
                                     headers=H)
    assert r.status_code == 200


def test_horizon_wins_over_incomplete_when_both_happen():
    cps = [_cp(0, "2026-11-21T13:00:00Z"), _cp(1, "2026-11-25T13:00:00Z")]
    r = _client(NullAtHour(13)).post("/v1/evaluate", json={"load_weight_lb": 1, "checkpoints": cps},
                                     headers=H)
    assert r.status_code == 422
    assert r.get_json()["error"]["code"] == "BEYOND_FORECAST_HORIZON"


def test_upstream_errors_map_to_502_504():
    from weather import WeatherUpstreamError

    class Broken:
        def __init__(self, timeout):
            self.timeout = timeout

        def series(self, cells):
            raise WeatherUpstreamError("down", timeout=self.timeout)

    body = {"load_weight_lb": 1, "checkpoints": [_cp(0, "2026-11-21T13:00:00Z")]}
    assert _client(Broken(False)).post("/v1/evaluate", json=body, headers=H).status_code == 502
    r = _client(Broken(True)).post("/v1/evaluate", json=body, headers=H)
    assert r.status_code == 504 and r.get_json()["error"]["code"] == "UPSTREAM_TIMEOUT"


def test_missing_token_401(fake_provider):
    r = _client(fake_provider).post("/v1/evaluate", json={"load_weight_lb": 1, "checkpoints": []})
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize(
    "body",
    [
        None,
        {"checkpoints": []},
        {"load_weight_lb": 0, "checkpoints": []},
        {"load_weight_lb": 1,
         "checkpoints": [{"id": "c", "lat": 1, "lon": 1, "eta": "2026-11-21T13:00:00"}]},
        {"load_weight_lb": 1,
         "checkpoints": [{"id": "c", "lat": 91, "lon": 1, "eta": "2026-11-21T13:00:00Z"}]},
    ],
)
def test_malformed_body_400_with_error_shape(fake_provider, body):
    c = _client(fake_provider)
    r = (c.post("/v1/evaluate", data="not json", headers={**H, "Content-Type": "application/json"})
         if body is None else c.post("/v1/evaluate", json=body, headers=H))
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_contract_fixture_request_produces_valid_response(fake_provider):
    req = json.loads((SHARED_FIXTURES / "evaluate_request.json").read_text())
    r = _client(fake_provider).post("/v1/evaluate", json=req, headers=H)
    assert r.status_code == 200
    body = EvaluateResponse.model_validate(r.get_json())
    assert [x.id for x in body.results] == [c["id"] for c in req["checkpoints"]]


def test_contract_fixture_response_validates():
    EvaluateResponse.model_validate_json((SHARED_FIXTURES / "evaluate_response.json").read_text())
