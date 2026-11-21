"""CORE-6 heatmap frames: grid, 49 hours from departure, same rules, nulls, cache, payload."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import heatmap
import pytest
from heatmap import buffered_bbox, build_heatmap, grid_shape

from app import create_app
from truckrisk_schemas import HeatmapRequest, HeatmapResponse, Weather

from .conftest import CALM, FakeProvider

TOKEN = "test-token"
H = {"X-Internal-Token": TOKEN}
BBOX = [-112.0, 39.5, -105.0, 41.0]  # roughly Denver -> Salt Lake City
START = "2026-11-21T13:20:00Z"
SHARED = Path(__file__).resolve().parents[2] / "shared" / "fixtures"
SHARED_FIXTURE = SHARED / "heatmap_response.json"
SHARED_REQUEST = SHARED / "heatmap_request.json"


@pytest.fixture(autouse=True)
def _fresh_cache():
    heatmap._cache.clear()
    yield
    heatmap._cache.clear()


def _req(**kw):
    body = {"bbox": BBOX, "start": START, "load_weight_lb": 42000, **kw}
    return HeatmapRequest.model_validate(body)


def test_49_hourly_frames_starting_at_departure_hour():
    r = build_heatmap(_req(), FakeProvider())
    assert r.hours == 49 and len(r.times) == 49
    assert r.times[0] == datetime(2026, 11, 21, 13, tzinfo=UTC)  # 13:20 rounded down (D14)
    assert r.times[48] - r.times[0] == timedelta(hours=48)
    for frames in r.variables.values():
        assert len(frames) == 49
        assert all(len(f) == r.grid.rows * r.grid.cols for f in frames)


def test_grid_within_cell_budget_and_roughly_square():
    for budget in (16, 100, 256, 400):
        rows, cols = grid_shape(buffered_bbox(BBOX), budget)
        assert rows * cols <= budget and rows >= 2 and cols >= 2
    rows, cols = grid_shape(buffered_bbox(BBOX), 256)
    assert cols > rows  # this corridor is wider than tall


def test_grid_covers_the_buffered_corridor():
    r = build_heatmap(_req(), FakeProvider())
    box = buffered_bbox(BBOX)
    assert box[0] < BBOX[0] and box[2] > BBOX[2] and box[1] < BBOX[1] and box[3] > BBOX[3]
    assert box[1] < r.grid.lats[0] < r.grid.lats[-1] < box[3]
    assert box[0] < r.grid.lons[0] < r.grid.lons[-1] < box[2]
    assert r.grid.lats == sorted(r.grid.lats) and r.grid.lons == sorted(r.grid.lons)


def test_frames_are_row_major_south_west_first():
    # Wind grows with latitude, snow with longitude: each value must sit at its own cell.
    def fn(lat, lon, hour):
        return Weather(wind_mph=round(lat, 1), rain_in_hr=0.0, snow_in_hr=round(lon + 200, 1))

    r = build_heatmap(_req(), FakeProvider(fn))
    cols = r.grid.cols
    frame_w, frame_s = r.variables["wind_mph"][0], r.variables["snow_in_hr"][0]
    for row in (0, r.grid.rows - 1):
        for col in (0, cols - 1):
            i = row * cols + col
            assert frame_w[i] == pytest.approx(r.grid.lats[row], abs=0.06)
            assert frame_s[i] == pytest.approx(r.grid.lons[col] + 200, abs=0.06)


def test_each_hour_uses_that_hours_weather():
    first = datetime(2026, 11, 21, 13, tzinfo=UTC)

    def fn(lat, lon, hour):
        h = int((hour - first).total_seconds() // 3600)
        return Weather(wind_mph=float(max(h, 0)), rain_in_hr=0.0, snow_in_hr=0.0)

    r = build_heatmap(_req(), FakeProvider(fn))
    assert [r.variables["wind_mph"][h][0] for h in (0, 1, 24, 48)] == [0.0, 1.0, 24.0, 48.0]


def test_risk_frames_use_the_checkpoint_rules_including_load():
    def fn(lat, lon, hour):
        return Weather(wind_mph=46.0, rain_in_hr=0.0, snow_in_hr=0.0)

    light = build_heatmap(_req(load_weight_lb=30000), FakeProvider(fn))
    heavy = build_heatmap(_req(load_weight_lb=30001), FakeProvider(fn))
    assert set(light.variables["risk"][0]) == {4}  # Severe wind
    assert set(heavy.variables["risk"][0]) == {5}  # load override -> No Travel


def test_values_rounded_for_payload():
    def fn(lat, lon, hour):
        return Weather(wind_mph=12.3456, rain_in_hr=0.123456, snow_in_hr=0.98765)

    r = build_heatmap(_req(), FakeProvider(fn))
    assert r.variables["wind_mph"][0][0] == 12.3
    assert r.variables["rain_in_hr"][0][0] == 0.12
    assert r.variables["snow_in_hr"][0][0] == 0.99


def test_hours_past_the_forecast_are_null_not_zero_or_low():
    # Forecast ends 10 h after the departure hour.
    p = FakeProvider(start=datetime(2026, 11, 21, 0, tzinfo=UTC), hours=24)
    r = build_heatmap(_req(), p)
    assert all(v is not None for v in r.variables["risk"][10])
    for name in ("risk", "wind_mph", "rain_in_hr", "snow_in_hr"):
        assert all(v is None for v in r.variables[name][11])
        assert all(v is None for v in r.variables[name][48])


def test_cached_per_corridor_start_and_load():
    p = FakeProvider()
    build_heatmap(_req(), p)
    n = len(p.requested)
    build_heatmap(_req(start="2026-11-21T13:55:00Z"), p)  # same departure hour
    assert len(p.requested) == n
    build_heatmap(_req(load_weight_lb=1000), p)
    assert len(p.requested) > n


def test_payload_under_1_5_mb_at_full_grid():
    def fn(lat, lon, hour):
        return Weather(wind_mph=33.3, rain_in_hr=0.33, snow_in_hr=1.11)

    app = create_app({"RISK_ENGINE_TOKEN": TOKEN, "FORECAST_PROVIDER": FakeProvider(fn)})
    r = app.test_client().post(
        "/v1/heatmap", json={"bbox": BBOX, "start": START, "load_weight_lb": 1, "max_cells": 400},
        headers=H,
    )
    assert r.status_code == 200
    assert len(r.data) < 1_500_000


# --- endpoint --------------------------------------------------------------------


def _client(provider=None):
    return create_app(
        {"RISK_ENGINE_TOKEN": TOKEN, "FORECAST_PROVIDER": provider or FakeProvider()}
    ).test_client()


def test_endpoint_returns_valid_response_with_z_times():
    r = _client().post("/v1/heatmap", json={"bbox": BBOX, "start": START, "load_weight_lb": 42000},
                       headers=H)
    assert r.status_code == 200
    body = r.get_json()
    HeatmapResponse.model_validate(body)
    assert body["times"][0] == "2026-11-21T13:00:00Z"
    assert body["source"] == "open-meteo"


def test_endpoint_requires_token():
    r = _client().post("/v1/heatmap", json={"bbox": BBOX, "start": START, "load_weight_lb": 1})
    assert r.status_code == 401


@pytest.mark.parametrize(
    "patch",
    [
        {"bbox": [-105.0, 39.5, -112.0, 41.0]},  # min > max
        {"bbox": [1, 2, 3]},
        {"start": "2026-11-21T13:00:00"},  # no offset
        {"hours": 24},
        {"load_weight_lb": 0},
        {"max_cells": 10_000},
    ],
)
def test_endpoint_validates_input(patch):
    body = {"bbox": BBOX, "start": START, "load_weight_lb": 1, **patch}
    r = _client().post("/v1/heatmap", json=body, headers=H)
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_endpoint_maps_weather_failures():
    from weather import WeatherUpstreamError

    class Broken:
        def __init__(self, timeout):
            self.timeout = timeout

        def series(self, cells):
            raise WeatherUpstreamError("down", timeout=self.timeout)

    body = {"bbox": BBOX, "start": START, "load_weight_lb": 1}
    assert _client(Broken(False)).post("/v1/heatmap", json=body, headers=H).status_code == 502
    assert _client(Broken(True)).post("/v1/heatmap", json=body, headers=H).status_code == 504


def test_shared_contract_fixture_validates_and_matches_builder_output():
    body = json.loads(SHARED_FIXTURE.read_text())
    HeatmapResponse.model_validate(body)
    # Produced by this builder from heatmap_request.json with _fixture_weather.
    req = json.loads(SHARED_REQUEST.read_text())
    built = json.loads(heatmap.to_json(build_heatmap(
        HeatmapRequest.model_validate(req), FakeProvider(_fixture_weather)
    )))
    for k in ("grid", "times", "hours", "variables", "source"):
        assert built[k] == body[k]


def _fixture_weather(lat, lon, hour):
    if lon > -108.5 and hour.hour % 6 == 0:
        return Weather(wind_mph=38.0, rain_in_hr=0.0, snow_in_hr=0.6)
    return CALM
