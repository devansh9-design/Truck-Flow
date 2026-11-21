"""Open-Meteo client: parsing a recorded real response, unit conversion, batching, cache, errors."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
import weather
from weather import OPEN_METEO_URL, OpenMeteoProvider, WeatherUpstreamError, cell_of, parse_location

RECORDED = Path(__file__).parent / "fixtures" / "open_meteo_two_points.json"


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(weather, "RETRY_BACKOFF_S", 0)


def _loc(times, wind, rain, showers, snow, units=None):
    return {
        "hourly_units": units
        or {"time": "unixtime", "wind_speed_10m": "mp/h", "rain": "inch", "showers": "inch",
            "snowfall": "inch"},
        "hourly": {"time": times, "wind_speed_10m": wind, "rain": rain, "showers": showers,
                   "snowfall": snow},
    }


T0 = int(datetime(2026, 11, 21, 13, tzinfo=UTC).timestamp())


def test_recorded_response_parses():
    body = json.loads(RECORDED.read_text())
    assert isinstance(body, list) and len(body) == 2
    s = parse_location(body[0])
    assert len(s.index) == 17 * 24
    hour = datetime.fromtimestamp(body[0]["hourly"]["time"][30], UTC)
    w = s.at(hour)
    assert w is not None
    assert w.wind_mph == body[0]["hourly"]["wind_speed_10m"][30]
    h = body[0]["hourly"]
    assert w.rain_in_hr == pytest.approx(h["rain"][30] + h["showers"][30])
    assert w.snow_in_hr == h["snowfall"][30]


def test_rain_is_rain_plus_showers_and_wind_is_sustained():
    s = parse_location(_loc([T0], [30.0], [0.2], [0.15], [0.0]))
    w = s.at(datetime.fromtimestamp(T0, UTC))
    assert (w.wind_mph, w.rain_in_hr, w.snow_in_hr) == (30.0, pytest.approx(0.35), 0.0)


def test_metric_units_converted_explicitly():
    units = {"time": "unixtime", "wind_speed_10m": "km/h", "rain": "mm", "showers": "mm",
             "snowfall": "cm"}
    s = parse_location(_loc([T0], [100.0], [25.4], [0.0], [2.54], units))
    w = s.at(datetime.fromtimestamp(T0, UTC))
    assert w.wind_mph == pytest.approx(62.137, rel=1e-4)
    assert w.rain_in_hr == pytest.approx(1.0)
    assert w.snow_in_hr == pytest.approx(1.0)


def test_unknown_unit_rejected():
    units = {"time": "unixtime", "wind_speed_10m": "furlongs", "rain": "inch", "showers": "inch",
             "snowfall": "inch"}
    with pytest.raises(WeatherUpstreamError):
        parse_location(_loc([T0], [1.0], [0.0], [0.0], [0.0], units))


def test_hour_outside_series_or_null_is_none():
    s = parse_location(_loc([T0, T0 + 3600], [5.0, None], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]))
    assert s.at(datetime.fromtimestamp(T0 + 3600, UTC)) is None  # null value
    assert s.at(datetime.fromtimestamp(T0 + 7200, UTC)) is None  # past the end


def _body_for(request):
    lats = request.url.params["latitude"].split(",")
    objs = [_loc([T0], [float(i)], [0.0], [0.0], [0.0]) for i, _ in enumerate(lats)]
    return httpx.Response(200, json=objs if len(objs) > 1 else objs[0])


@respx.mock
def test_dedupes_cells_batches_and_caches():
    route = respx.get(OPEN_METEO_URL).mock(side_effect=_body_for)
    p = OpenMeteoProvider()
    cells = [cell_of(39.0 + i * 0.1, -100.0) for i in range(120)] + [cell_of(39.01, -100.02)]
    out, meta = p.series(cells)
    assert len(out) == 120 and meta == {"cache_hits": 0, "fetched": 120}
    assert route.call_count == 3  # 50 + 50 + 20
    q = route.calls[0].request.url.params
    assert q["hourly"] == "wind_speed_10m,rain,showers,snowfall"
    assert (q["wind_speed_unit"], q["precipitation_unit"]) == ("mph", "inch")
    assert (q["forecast_days"], q["past_days"], q["timeformat"]) == ("16", "1", "unixtime")
    _, meta2 = p.series(cells[:10])
    assert meta2 == {"cache_hits": 10, "fetched": 0}
    assert route.call_count == 3


@respx.mock
def test_single_location_object_response():
    respx.get(OPEN_METEO_URL).mock(side_effect=_body_for)
    out, _ = OpenMeteoProvider().series([cell_of(39.0, -100.0)])
    assert len(out) == 1


@respx.mock
def test_overloaded_error_body_retried_then_502():
    route = respx.get(OPEN_METEO_URL).mock(
        return_value=httpx.Response(429, json={"error": True, "reason": "The service is overloaded"})
    )
    with pytest.raises(WeatherUpstreamError) as exc:
        OpenMeteoProvider().series([cell_of(39.0, -100.0)])
    assert route.call_count == 2 and not exc.value.timeout


@respx.mock
def test_400_not_retried():
    route = respx.get(OPEN_METEO_URL).mock(
        return_value=httpx.Response(400, json={"error": True, "reason": "bad latitude"})
    )
    with pytest.raises(WeatherUpstreamError, match="bad latitude"):
        OpenMeteoProvider().series([cell_of(39.0, -100.0)])
    assert route.call_count == 1


@respx.mock
def test_timeout_retried_then_timeout_error():
    route = respx.get(OPEN_METEO_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(WeatherUpstreamError) as exc:
        OpenMeteoProvider().series([cell_of(39.0, -100.0)])
    assert route.call_count == 2 and exc.value.timeout


@respx.mock
def test_recovers_on_retry():
    route = respx.get(OPEN_METEO_URL)
    route.side_effect = [httpx.Response(503), _body_for]
    out, _ = OpenMeteoProvider().series([cell_of(39.0, -100.0)])
    assert len(out) == 1
