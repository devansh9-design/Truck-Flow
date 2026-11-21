"""T6 edge cases through Django and the real Flask app (synthetic weather, mocked HERE).

Cases already covered elsewhere: unknown place / same place / bad load (test_api.py),
fewer than 3 routes (test_routes.py), Flask down and health "down" (test_api.py,
test_analyze.py), beyond the forecast horizon (test_analyze.py, risk_engine tests).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import respx
from freezegun import freeze_time
from rest_framework.test import APIClient

from .helpers import here_route, straight_line
from .test_scenarios import (  # noqa: F401  (_settings is the autouse settings fixture)
    NOW,
    RISK_URL,
    ScriptedForecast,
    _settings,
    flask_forwarder,
    post_analyze,
    storm,
    weather_mod,
)


def _routes(miles: float, hours: float) -> dict:
    """Three HERE routes over the same straight road (distinct ids, near-identical)."""
    secs = hours * 3600
    return {"routes": [here_route(straight_line(miles), rid=f"r{i}", duration_s=secs + 60 * i)
                       for i in range(3)]}


@freeze_time(NOW)
def test_very_short_trip_has_origin_and_destination_only_and_is_still_ranked():
    r = post_analyze(here={"routes": [here_route(straight_line(10), rid="short", duration_s=900)]})
    assert r.status_code == 200, r.content
    d = r.json()
    route = d["routes"][0]
    assert [c["index"] for c in route["checkpoints"]] == [0, 1]
    assert route["checkpoints"][1]["mile"] == route["distance_mi"]
    assert route["recommended"] is True and route["rank"] == 1
    assert d["recommendation"]["decided_by"] == "only_route"
    assert all("risk" in c for c in route["checkpoints"])


@freeze_time(NOW)
def test_trip_longer_than_48_hours_analyses_and_heatmap_still_covers_0_to_48():
    r = post_analyze(here=_routes(2000, 55), interval=50)
    assert r.status_code == 200, r.content
    d = r.json()
    route = d["routes"][0]
    dep = datetime.fromisoformat(d["trip"]["departure_time"])
    last = datetime.fromisoformat(route["checkpoints"][-1]["eta"])
    assert last - dep > timedelta(hours=48)  # ETAs run past the slider window

    hour0 = dep.replace(minute=0)
    with respx.mock:
        respx.post(f"{RISK_URL}/v1/heatmap").mock(
            side_effect=flask_forwarder(ScriptedForecast(storm({})))
        )
        h = APIClient().get("/api/heatmap", {
            "bbox": ",".join(str(b) for b in d["corridor"]["bbox"]),
            "start": hour0.isoformat().replace("+00:00", "Z"),
            "load_weight_lb": 20000,
        })
    assert h.status_code == 200, h.content
    hm = h.json()
    assert hm["hours"] == 49 and len(hm["times"]) == 49
    span = datetime.fromisoformat(hm["times"][-1]) - datetime.fromisoformat(hm["times"][0])
    assert span == timedelta(hours=48)


@freeze_time("2026-10-31T12:00:00Z")
def test_departure_on_dst_change_day_converts_to_utc_correctly():
    # 01:30 MDT (-06:00) on 2026-11-01, half an hour before US clocks fall back.
    forecast = ScriptedForecast(storm({}), start=datetime(2026, 10, 30, tzinfo=UTC))
    r = post_analyze(here={"routes": [here_route(straight_line(107), rid="a", duration_s=7200)]},
                     provider=forecast, departure="2026-11-01T01:30:00-06:00")
    assert r.status_code == 200, r.content
    d = r.json()
    assert d["trip"]["departure_time"] == "2026-11-01T07:30:00Z"
    cps = d["routes"][0]["checkpoints"]
    assert cps[0]["eta"] == "2026-11-01T07:30:00Z"
    assert cps[-1]["eta"] == "2026-11-01T09:30:00Z"  # + 2 h of driving, in UTC
    for c in cps:  # each forecast hour is a whole UTC hour within 30 min of the ETA
        eta, hour = datetime.fromisoformat(c["eta"]), datetime.fromisoformat(c["forecast_hour"])
        assert hour.minute == 0 and abs(eta - hour) <= timedelta(minutes=30)


@freeze_time(NOW)
def test_departure_more_than_an_hour_in_the_past_is_400():
    past = (datetime.fromisoformat(NOW) - timedelta(hours=2)).astimezone(UTC).isoformat()
    r = post_analyze(departure=past)
    assert r.status_code == 400
    assert r.json()["error"]["details"] == {"field": "departure_time"}


@freeze_time(NOW)
def test_open_meteo_timeout_is_504_and_never_partial():
    class TimingOut:
        def series(self, cells):
            raise weather_mod.WeatherUpstreamError("Open-Meteo did not respond in time.", timeout=True)

    r = post_analyze(provider=TimingOut())
    assert r.status_code == 504
    body = r.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert "in time" in body["error"]["message"]


@freeze_time(NOW)
def test_incomplete_open_meteo_data_is_502_not_beyond_horizon():
    class Holey(ScriptedForecast):
        def series(self, cells):
            out, meta = super().series(cells)
            for s in out.values():
                s.wind_mph[:] = [None] * len(s.wind_mph)
            return out, meta

    r = post_analyze(provider=Holey(storm({})))
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "UPSTREAM_ERROR"
