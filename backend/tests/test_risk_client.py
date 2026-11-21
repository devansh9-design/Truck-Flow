"""Django -> Flask client (T2 contract, Django side): shared fixtures via respx."""

import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import respx

from api.errors import BeyondForecastHorizon, UpstreamError, UpstreamTimeout
from clients import risk_engine
from truckrisk_schemas import CheckpointIn

RISK_URL = "http://risk.test"
SHARED = Path(__file__).resolve().parents[2] / "shared" / "fixtures"


@pytest.fixture(autouse=True)
def _settings(settings, monkeypatch):
    settings.RISK_ENGINE_URL = RISK_URL
    settings.RISK_ENGINE_TOKEN = "test-token"
    monkeypatch.setattr(risk_engine, "RETRY_BACKOFF_S", 0)


def _request_checkpoints():
    req = json.loads((SHARED / "evaluate_request.json").read_text())
    return req["load_weight_lb"], [
        CheckpointIn(id=c["id"], lat=c["lat"], lon=c["lon"], eta=datetime.fromisoformat(c["eta"]))
        for c in req["checkpoints"]
    ]


def _fixture_response():
    return httpx.Response(200, content=(SHARED / "evaluate_response.json").read_bytes(),
                          headers={"Content-Type": "application/json"})


@respx.mock
def test_parses_shared_fixture_and_sends_token():
    route = respx.post(f"{RISK_URL}/v1/evaluate").mock(return_value=_fixture_response())
    load, cps = _request_checkpoints()
    results = risk_engine.evaluate(load, cps)
    assert [r.id for r in results] == ["r0-c0", "r0-c1", "r0-c2"]
    assert results[1].risk.factors.load_override == "SEVERE"
    sent = route.calls[0].request
    assert sent.headers["X-Internal-Token"] == "test-token"
    assert json.loads(sent.content)["load_weight_lb"] == 42000


@respx.mock
def test_result_count_mismatch_raises():
    body = json.loads((SHARED / "evaluate_response.json").read_text())
    body["results"] = body["results"][:2]
    respx.post(f"{RISK_URL}/v1/evaluate").mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(UpstreamError):
        risk_engine.evaluate(*_request_checkpoints())


@respx.mock
def test_result_order_mismatch_raises():
    body = json.loads((SHARED / "evaluate_response.json").read_text())
    body["results"].reverse()
    respx.post(f"{RISK_URL}/v1/evaluate").mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(UpstreamError):
        risk_engine.evaluate(*_request_checkpoints())


@respx.mock
def test_malformed_response_raises():
    respx.post(f"{RISK_URL}/v1/evaluate").mock(return_value=httpx.Response(200, json={"results": "x"}))
    with pytest.raises(UpstreamError):
        risk_engine.evaluate(*_request_checkpoints())


@respx.mock
@pytest.mark.parametrize(
    "status,code,exc",
    [
        (422, "BEYOND_FORECAST_HORIZON", BeyondForecastHorizon),
        (504, "UPSTREAM_TIMEOUT", UpstreamTimeout),
        (502, "UPSTREAM_ERROR", UpstreamError),
        (401, "UNAUTHORIZED", UpstreamError),
        (400, "VALIDATION_ERROR", UpstreamError),
    ],
)
def test_error_codes_mapped(status, code, exc):
    route = respx.post(f"{RISK_URL}/v1/evaluate").mock(
        return_value=httpx.Response(status, json={"error": {"code": code, "message": "m"}})
    )
    with pytest.raises(exc):
        risk_engine.evaluate(*_request_checkpoints())
    assert route.call_count == 1  # Flask already retried its own upstream; we don't


@respx.mock
def test_flask_down_retried_once_then_502():
    route = respx.post(f"{RISK_URL}/v1/evaluate").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(UpstreamError):
        risk_engine.evaluate(*_request_checkpoints())
    assert route.call_count == 2


@respx.mock
def test_flask_500_retried_then_ok():
    route = respx.post(f"{RISK_URL}/v1/evaluate")
    route.side_effect = [httpx.Response(500), _fixture_response()]
    assert len(risk_engine.evaluate(*_request_checkpoints())) == 3


@respx.mock
def test_timeout_retried_then_504():
    respx.post(f"{RISK_URL}/v1/evaluate").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(UpstreamTimeout):
        risk_engine.evaluate(*_request_checkpoints())
