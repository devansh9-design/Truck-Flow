"""P3-3 NWS alerts: client against recorded responses, collection, and /v1/alerts."""

from __future__ import annotations

import json
from pathlib import Path

import alerts as alerts_mod
import httpx
import pytest
import respx
from alerts import NWS_URL, AlertsUpstreamError, NwsClient, OutOfBounds, collect_alerts

from app import create_app
from truckrisk_schemas import AlertsRequest, AlertsResponse

FIX = Path(__file__).parent / "fixtures"
TOKEN = "test-token"
HEADERS = {"X-Internal-Token": TOKEN}


def recorded(name: str) -> httpx.Response:
    d = json.loads((FIX / name).read_text())
    return httpx.Response(d["status"], json=d["body"])


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(alerts_mod, "RETRY_BACKOFF_S", 0)


# ---- NwsClient against recorded responses -------------------------------------------------


@respx.mock
def test_client_parses_recorded_warning():
    respx.get(NWS_URL).mock(return_value=recorded("nws_high_wind_warning.json"))
    props = NwsClient().active((41.25, -105.45))
    assert len(props) == 1
    assert props[0]["event"] == "High Wind Warning" and props[0]["severity"] == "Severe"


@respx.mock
def test_client_sends_user_agent_and_point():
    route = respx.get(NWS_URL).mock(return_value=recorded("nws_no_alerts.json"))
    assert NwsClient(user_agent="ua-test").active((39.74, -104.99)) == []
    req = route.calls[0].request
    assert req.headers["User-Agent"] == "ua-test"
    assert req.url.params["point"] == "39.74,-104.99"


@respx.mock
def test_client_out_of_bounds_is_cached():
    route = respx.get(NWS_URL).mock(return_value=recorded("nws_out_of_bounds.json"))
    c = NwsClient()
    for _ in range(2):
        with pytest.raises(OutOfBounds):
            c.active((43.65, -79.38))
    assert route.call_count == 1


@respx.mock
def test_client_caches_answers():
    route = respx.get(NWS_URL).mock(return_value=recorded("nws_no_alerts.json"))
    c = NwsClient()
    c.active((1.0, 2.0))
    c.active((1.0, 2.0))
    assert route.call_count == 1


@respx.mock
def test_client_retries_5xx_once_then_fails():
    route = respx.get(NWS_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(AlertsUpstreamError) as exc:
        NwsClient().active((1.0, 2.0))
    assert route.call_count == 2 and not exc.value.timeout


@respx.mock
def test_client_does_not_retry_429():
    route = respx.get(NWS_URL).mock(return_value=httpx.Response(429))
    with pytest.raises(AlertsUpstreamError):
        NwsClient().active((1.0, 2.0))
    assert route.call_count == 1


@respx.mock
def test_client_timeout_is_flagged():
    respx.get(NWS_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(AlertsUpstreamError) as exc:
        NwsClient().active((1.0, 2.0))
    assert exc.value.timeout


# ---- collect_alerts ----------------------------------------------------------------------


def _props(i: str, severity: str = "Moderate", **kw):
    base = {"id": i, "event": f"Event {i}", "severity": severity, "headline": f"H {i}",
            "areaDesc": "Somewhere", "onset": "2026-11-20T08:00:00-07:00",
            "ends": "2026-11-20T17:00:00-07:00"}
    base.update(kw)
    return base


class FakeSource:
    def __init__(self, table):
        self.table, self.calls = table, []

    def active(self, point):
        self.calls.append(point)
        v = self.table.get(point, [])
        if v is None:
            raise OutOfBounds
        return v


def req(*pts):
    return AlertsRequest.model_validate({"points": [{"lat": a, "lon": b} for a, b in pts]})


def test_dedupes_by_id_keeps_first_point_and_sorts_by_severity():
    src = FakeSource({
        (40.0, -105.0): [_props("a", "Minor")],
        (41.0, -106.0): [_props("a", "Minor"), _props("b", "Severe")],
        (42.0, -107.0): [_props("c", "Extreme")],
    })
    out = collect_alerts(req((40, -105), (41, -106), (42, -107)), src)
    assert out.coverage == "US"
    assert [(a.id, a.point_index) for a in out.alerts] == [("c", 2), ("b", 1), ("a", 0)]


def test_times_are_utc_and_missing_end_is_none():
    src = FakeSource({(40.0, -105.0): [_props("a", ends=None)]})
    a = collect_alerts(req((40, -105)), src).alerts[0]
    assert a.onset.isoformat() == "2026-11-20T15:00:00+00:00"
    assert a.ends is None


def test_unknown_severity_and_bad_items_are_tolerated():
    src = FakeSource({(40.0, -105.0): [_props("a", "Weird"), {"id": 5}, {}]})
    out = collect_alerts(req((40, -105)), src)
    assert [(a.id, a.severity) for a in out.alerts] == [("a", "Unknown")]


def test_points_are_rounded_and_fetched_once():
    src = FakeSource({})
    collect_alerts(req((40.001, -105.001), (40.0012, -105.0004), (40.5, -105.5)), src)
    assert sorted(src.calls) == [(40.0, -105.0), (40.5, -105.5)]


def test_all_points_out_of_bounds_is_unsupported_region():
    src = FakeSource({(43.65, -79.38): None, (45.5, -73.57): None})
    out = collect_alerts(req((43.65, -79.38), (45.5, -73.57)), src)
    assert out.coverage == "unsupported_region" and out.alerts == []


def test_mixed_region_checks_us_points_only():
    src = FakeSource({(43.65, -79.38): None, (42.9, -78.9): [_props("buf")]})
    out = collect_alerts(req((43.65, -79.38), (42.9, -78.9)), src)
    assert out.coverage == "US" and [a.point_index for a in out.alerts] == [1]


def test_recorded_feature_maps_to_contract():
    props = [f["properties"] for f in
             json.loads((FIX / "nws_high_wind_warning.json").read_text())["body"]["features"]]
    out = collect_alerts(req((41.25, -105.45)), FakeSource({(41.25, -105.45): props}))
    AlertsResponse.model_validate_json(out.model_dump_json())
    a = out.alerts[0]
    assert a.event == "High Wind Warning" and a.severity == "Severe" and a.id.startswith("urn:oid:")
    assert a.onset is not None and a.onset.utcoffset().total_seconds() == 0


# ---- /v1/alerts ---------------------------------------------------------------------------


@pytest.fixture
def client():
    src = FakeSource({(41.25, -105.45): [_props("w", "Severe")], (43.65, -79.38): None})
    return create_app({"RISK_ENGINE_TOKEN": TOKEN, "TESTING": True,
                       "ALERT_SOURCE": src}).test_client()


def test_endpoint_needs_token(client):
    assert client.post("/v1/alerts", json={"points": [{"lat": 1, "lon": 1}]}).status_code == 401


def test_endpoint_returns_contract(client):
    r = client.post("/v1/alerts", headers=HEADERS,
                    json={"points": [{"lat": 41.25, "lon": -105.45}]})
    assert r.status_code == 200
    body = AlertsResponse.model_validate(r.get_json())
    assert body.coverage == "US" and body.alerts[0].id == "w"


def test_endpoint_unsupported_region(client):
    r = client.post("/v1/alerts", headers=HEADERS,
                    json={"points": [{"lat": 43.65, "lon": -79.38}]})
    assert r.get_json() == {"alerts": [], "coverage": "unsupported_region"}


@pytest.mark.parametrize("body", [
    {"points": []},
    {"points": [{"lat": 91, "lon": 0}]},
    {"points": [{"lat": 1, "lon": 1}] * 101},
    {"points": [{"lat": 1, "lon": 1}], "x": 1},
])
def test_endpoint_validates(client, body):
    r = client.post("/v1/alerts", headers=HEADERS, json=body)
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(("timeout", "status", "code"),
                         [(True, 504, "UPSTREAM_TIMEOUT"), (False, 502, "UPSTREAM_ERROR")])
def test_endpoint_upstream_errors(timeout, status, code):
    class Broken:
        def active(self, point):
            raise AlertsUpstreamError("nope", timeout=timeout)

    c = create_app({"RISK_ENGINE_TOKEN": TOKEN, "TESTING": True,
                    "ALERT_SOURCE": Broken()}).test_client()
    r = c.post("/v1/alerts", headers=HEADERS, json={"points": [{"lat": 1, "lon": 1}]})
    assert r.status_code == status and r.get_json()["error"]["code"] == code
