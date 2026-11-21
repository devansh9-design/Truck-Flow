"""T3 scenarios S1-S10 through the whole stack with synthetic weather.

Django's /api/analyze runs for real (routing mocked from HERE-shaped payloads). Its call
to Flask is forwarded into the real Flask app, whose forecast provider is replaced by a
script of weather per (lat, lon, hour). So the real risk rules, load overrides, scoring
and ranking all run; only the outside world (HERE, Open-Meteo) is synthetic.

Geometry (helpers): three O->D routes, 107 mi west to east along 39 N:
    r0 straight (fastest, 100 min), r1 bows 30 mi north (117 min), r2 bows 30 mi south (125 min).
The "middle" zone (lon -99.3..-98.7) holds one checkpoint per route at a 25 mi interval
for the straight route; the bows are ~0.4 deg away, so each route can get its own weather.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from django.core.cache import cache
from freezegun import freeze_time
from rest_framework.test import APIClient

from truckrisk_schemas import Weather

from .helpers import bowed, here_route, straight_line

RISK_ENGINE_DIR = Path(__file__).resolve().parents[2] / "risk_engine"
if str(RISK_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(RISK_ENGINE_DIR))
flask_app = importlib.import_module("app")
weather_mod = importlib.import_module("weather")

ROUTES_URL = "https://router.test/v8/routes"
RISK_URL = "http://risk.test"
TOKEN = "scenario-token"
NOW = "2026-11-20T04:00:00Z"
DEPARTURE = datetime(2026, 11, 21, 13, tzinfo=UTC)  # 06:00 MST
CALM = Weather(wind_mph=5.0, rain_in_hr=0.0, snow_in_hr=0.0)

WeatherFn = Callable[[float, float, datetime], Weather]


class ScriptedForecast:
    """Forecast provider for the real Flask app: weather_fn(lat, lon, hour) per 0.1 deg cell."""

    def __init__(self, fn: WeatherFn, start=datetime(2026, 11, 20, tzinfo=UTC), hours=17 * 24):
        self.fn, self.start, self.hours = fn, start, hours

    def series(self, cells):
        out = {}
        for c in dict.fromkeys(cells):
            lat, lon = c[0] / 10, c[1] / 10
            ws = [self.fn(lat, lon, self.start + timedelta(hours=h)) for h in range(self.hours)]
            out[c] = weather_mod.Series(
                index={int((self.start + timedelta(hours=h)).timestamp()): h for h in range(self.hours)},
                wind_mph=[w.wind_mph for w in ws],
                rain_in_hr=[w.rain_in_hr for w in ws],
                snow_in_hr=[w.snow_in_hr for w in ws],
            )
        return out, {"cache_hits": 0, "fetched": len(out)}


def route_at(lat: float) -> str:
    return "north" if lat > 39.2 else "south" if lat < 38.8 else "straight"


def in_middle(lon: float) -> bool:
    return -99.3 <= lon <= -98.7


def storm(where: dict[str, Weather]) -> WeatherFn:
    """Weather in the middle zone of the named routes; calm everywhere else."""

    def fn(lat, lon, hour):
        if in_middle(lon):
            return where.get(route_at(lat), CALM)
        return CALM

    return fn


def wind(mph: float) -> Weather:
    return Weather(wind_mph=mph, rain_in_hr=0.0, snow_in_hr=0.0)


@pytest.fixture(autouse=True)
def _settings(settings, monkeypatch):
    settings.HERE_API_KEY = "test-key"
    settings.HERE_ROUTES_URL = ROUTES_URL
    settings.RISK_ENGINE_URL = RISK_URL
    settings.RISK_ENGINE_TOKEN = TOKEN
    monkeypatch.setattr("geo.http.RETRY_BACKOFF_S", 0)
    cache.clear()


def _here():
    return {"routes": [
        here_route(straight_line(107), rid="straight", duration_s=6000),
        here_route(bowed(107, 30), rid="north", duration_s=7000),
        here_route(bowed(107, -30), rid="south", duration_s=7500),
    ]}


def flask_forwarder(provider) -> Callable[[httpx.Request], httpx.Response]:
    """respx side effect: hand Django's internal request to the real Flask app."""
    flask = flask_app.create_app({"RISK_ENGINE_TOKEN": TOKEN, "FORECAST_PROVIDER": provider}).test_client()

    def forward(request: httpx.Request) -> httpx.Response:
        resp = flask.post(request.url.path, data=request.content,
                          headers={"X-Internal-Token": request.headers["X-Internal-Token"],
                                   "Content-Type": "application/json"})
        return httpx.Response(resp.status_code, content=resp.data,
                              headers={"Content-Type": "application/json"})

    return forward


def post_analyze(fn: WeatherFn | None = None, *, provider=None, here: dict | None = None,
                 load_lb: float = 20000, interval: int = 25, departure: str | None = None):
    """POST /api/analyze through Django and the real Flask app; returns the response."""
    with respx.mock:
        respx.get(ROUTES_URL).mock(return_value=httpx.Response(200, json=here or _here()))
        respx.post(f"{RISK_URL}/v1/evaluate").mock(
            side_effect=flask_forwarder(provider or ScriptedForecast(fn or storm({})))
        )
        return APIClient().post("/api/analyze", {
            "origin": {"label": "O", "lat": 39.0, "lon": -100.0},
            "destination": {"label": "D", "lat": 39.0, "lon": -98.0},
            "departure_time": departure or DEPARTURE.isoformat(),
            "load_weight_lb": load_lb,
            "interval_mi": interval,
        }, format="json")


def analyze(fn: WeatherFn, load_lb: float = 20000, interval: int = 25) -> dict:
    r = post_analyze(fn, load_lb=load_lb, interval=interval)
    assert r.status_code == 200, r.content
    return r.json()


def by_id(d: dict) -> dict[str, dict]:
    return {r["id"]: r for r in d["routes"]}


def middle_checkpoints(route: dict) -> list[dict]:
    return [c for c in route["checkpoints"] if in_middle(round(c["lon"], 1))]


# r0 = straight, r1 = north, r2 = south (router order, fastest first)


@freeze_time(NOW)
def test_s1_calm_everywhere_three_routes_fastest_recommended():
    d = analyze(storm({}))
    assert len(d["routes"]) == 3
    assert d["recommendation"] == {**d["recommendation"], "route_id": "r0", "decided_by": "duration_s"}
    for r in d["routes"]:
        assert {c["risk"]["level"] for c in r["checkpoints"]} == {"LOW"}


@freeze_time(NOW)
def test_s2_storm_on_fastest_route_slower_clear_route_wins_on_severe_miles():
    # Storm over the fastest (and the slowest) route; only the north route is clear, so
    # rank 1 vs rank 2 is clear vs stormy and decided_by names the storm key.
    d = analyze(storm({"straight": wind(47), "south": wind(47)}), load_lb=20000)
    r = by_id(d)
    assert {c["risk"]["level"] for c in middle_checkpoints(r["r0"])} == {"SEVERE"}
    assert r["r0"]["summary"]["severe_mi"] > 0
    assert d["recommendation"]["route_id"] == "r1"
    assert d["recommendation"]["decided_by"] == "severe_mi"


@freeze_time(NOW)
def test_s3_same_storm_heavier_load_becomes_no_travel():
    d = analyze(storm({"straight": wind(47), "south": wind(47)}), load_lb=35000)
    r = by_id(d)
    mid = middle_checkpoints(r["r0"])
    assert {c["risk"]["level"] for c in mid} == {"NO_TRAVEL"}
    assert {c["risk"]["factors"]["load_override"] for c in mid} == {"NO_TRAVEL"}
    assert r["r0"]["summary"]["no_travel_mi"] > 0 and r["r0"]["summary"]["severe_mi"] == 0  # D3
    assert r["r0"]["warnings"] == ["NO_TRAVEL_CONDITIONS"]
    assert d["recommendation"]["route_id"] == "r1"
    assert d["recommendation"]["decided_by"] == "no_travel_mi"


@freeze_time(NOW)
def test_s4_wind_38_with_45000_lb_is_severe_by_load_rule():
    d = analyze(storm({"straight": wind(38)}), load_lb=45000)
    mid = middle_checkpoints(by_id(d)["r0"])
    assert {c["risk"]["level"] for c in mid} == {"SEVERE"}
    assert {c["risk"]["factors"]["wind"] for c in mid} == {"HIGH"}  # wind alone is High
    assert {c["risk"]["factors"]["load_override"] for c in mid} == {"SEVERE"}
    # Same wind at exactly 40,000 lb is not "over 40,000": stays High.
    d40 = analyze(storm({"straight": wind(38)}), load_lb=40000)
    assert {c["risk"]["level"] for c in middle_checkpoints(by_id(d40)["r0"])} == {"HIGH"}


@freeze_time(NOW)
def test_s5_equal_severe_miles_fewer_high_miles_wins():
    # r0 High, r1 clear, r2 Severe: r1 vs r0 tie on Severe (0) and split on High.
    d = analyze(storm({"straight": wind(40), "south": wind(50)}))
    r = by_id(d)
    assert r["r0"]["summary"]["severe_mi"] == r["r1"]["summary"]["severe_mi"] == 0
    assert r["r0"]["summary"]["high_mi"] > 0 == r["r1"]["summary"]["high_mi"]
    assert [x["id"] for x in d["routes"]] == ["r1", "r0", "r2"]
    assert d["recommendation"]["decided_by"] == "high_mi"


@freeze_time(NOW)
def test_s6_equal_severe_and_high_lower_average_risk_wins():
    # r0 Moderate, r1 clear, r2 Severe: r1 vs r0 tie on Severe and High, split on average.
    d = analyze(storm({"straight": wind(30), "south": wind(50)}))
    r = by_id(d)
    assert r["r0"]["summary"]["high_mi"] == r["r1"]["summary"]["high_mi"] == 0
    assert r["r0"]["summary"]["avg_risk"] > r["r1"]["summary"]["avg_risk"]
    assert [x["id"] for x in d["routes"]][:2] == ["r1", "r0"]
    assert d["recommendation"]["decided_by"] == "avg_risk"


@freeze_time(NOW)
def test_s7_everything_equal_shorter_duration_wins():
    # The same Moderate wind everywhere: every risk key ties, so time decides.
    d = analyze(lambda lat, lon, hour: wind(30))
    assert [x["id"] for x in d["routes"]] == ["r0", "r1", "r2"]
    assert d["recommendation"]["decided_by"] == "duration_s"
    assert len({x["summary"]["avg_risk"] for x in d["routes"]}) == 1


@freeze_time(NOW)
def test_s8_snow_moving_in_uses_each_checkpoints_arrival_hour():
    snow_from = DEPARTURE + timedelta(hours=1)

    def fn(lat, lon, hour):
        return Weather(wind_mph=5.0, rain_in_hr=0.0, snow_in_hr=2.5) if hour >= snow_from else CALM

    d = analyze(fn)
    r0 = by_id(d)["r0"]
    for c in r0["checkpoints"]:
        due = datetime.fromisoformat(c["forecast_hour"])
        assert c["risk"]["level"] == ("SEVERE" if due >= snow_from else "LOW"), c
    levels = {c["risk"]["level"] for c in r0["checkpoints"]}
    assert levels == {"LOW", "SEVERE"}  # at departure it is calm; later checkpoints meet the snow


@freeze_time(NOW)
def test_s9_every_route_has_no_travel_fewest_wins_with_warning():
    d = analyze(storm({"straight": wind(60), "north": wind(60), "south": wind(60)}))
    assert all(x["warnings"] == ["NO_TRAVEL_CONDITIONS"] for x in d["routes"])
    nts = [x["summary"]["no_travel_mi"] for x in d["routes"]]
    assert nts == sorted(nts)  # ranked by No Travel miles first
    assert d["routes"][0]["recommended"] is True


@freeze_time(NOW)
def test_s10_no_travel_ranks_below_severe_only():
    # r0: No Travel (0 Severe). r1: Severe only. r2: No Travel as well.
    d = analyze(storm({"straight": wind(60), "north": wind(50), "south": wind(60)}))
    r = by_id(d)
    assert r["r0"]["summary"]["severe_mi"] == 0 and r["r0"]["summary"]["no_travel_mi"] > 0
    assert r["r1"]["summary"]["no_travel_mi"] == 0 and r["r1"]["summary"]["severe_mi"] > 0
    assert d["recommendation"]["route_id"] == "r1"
    assert d["recommendation"]["decided_by"] == "no_travel_mi"
    assert r["r1"]["rank"] < r["r0"]["rank"]


def test_scenario_weather_is_scripted_not_live(monkeypatch):
    # Guard: these tests must never reach Open-Meteo.
    def boom(*a, **k):
        raise AssertionError("live Open-Meteo call")

    monkeypatch.setattr(weather_mod.OpenMeteoProvider, "_get", boom)
    with freeze_time(NOW):
        analyze(storm({}))
