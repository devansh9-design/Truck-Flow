"""POST /api/alerts (A5, non-core): validation, pass-through of the shared fixture, errors."""

import json
from pathlib import Path

import httpx
import pytest
import respx
from rest_framework.test import APIClient

from clients import risk_engine

RISK_URL = "http://risk.test"
SHARED = Path(__file__).resolve().parents[2] / "shared" / "fixtures"


@pytest.fixture(autouse=True)
def _settings(settings, monkeypatch):
    settings.RISK_ENGINE_URL = RISK_URL
    settings.RISK_ENGINE_TOKEN = "test-token"
    monkeypatch.setattr(risk_engine, "RETRY_BACKOFF_S", 0)


def _post(body):
    return APIClient().post("/api/alerts", body, format="json")


def _request():
    return json.loads((SHARED / "alerts_request.json").read_text())


@respx.mock
def test_passes_fixture_through():
    route = respx.post(f"{RISK_URL}/v1/alerts").mock(return_value=httpx.Response(
        200, content=(SHARED / "alerts_response.json").read_bytes()))
    r = _post(_request())
    assert r.status_code == 200
    body = r.json()
    assert body["coverage"] == "US"
    assert body["alerts"][0]["event"] == "High Wind Warning" and body["alerts"][0]["point_index"] == 1
    sent = json.loads(route.calls[0].request.content)
    assert sent == _request()
    assert route.calls[0].request.headers["X-Internal-Token"] == "test-token"


@respx.mock
def test_unsupported_region_passes_through():
    respx.post(f"{RISK_URL}/v1/alerts").mock(return_value=httpx.Response(
        200, json={"alerts": [], "coverage": "unsupported_region"}))
    r = _post({"points": [{"lat": 43.65, "lon": -79.38}]})
    assert r.json() == {"alerts": [], "coverage": "unsupported_region"}


@pytest.mark.parametrize("body", [
    {},
    {"points": []},
    {"points": [{"lat": 91, "lon": 0}]},
    {"points": [{"lat": 0, "lon": 181}]},
    {"points": [{"lat": "x", "lon": 0}]},
    {"points": [{"lat": 1, "lon": 1}] * 101},
])
def test_validation(body):
    r = _post(body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.parametrize(("upstream", "status", "code"), [
    (httpx.Response(504, json={"error": {"code": "UPSTREAM_TIMEOUT", "message": "x"}}),
     504, "UPSTREAM_TIMEOUT"),
    (httpx.Response(502, json={"error": {"code": "UPSTREAM_ERROR", "message": "x"}}),
     502, "UPSTREAM_ERROR"),
    (httpx.Response(200, json={"alerts": "nope"}), 502, "UPSTREAM_ERROR"),
])
def test_upstream_errors(upstream, status, code):
    respx.post(f"{RISK_URL}/v1/alerts").mock(return_value=upstream)
    r = _post(_request())
    assert r.status_code == status and r.json()["error"]["code"] == code


@respx.mock
def test_alerts_do_not_touch_analysis():
    """Alerts are informational: the endpoint never calls /v1/evaluate."""
    ev = respx.post(f"{RISK_URL}/v1/evaluate")
    respx.post(f"{RISK_URL}/v1/alerts").mock(return_value=httpx.Response(
        200, content=(SHARED / "alerts_response.json").read_bytes()))
    _post(_request())
    assert ev.call_count == 0
