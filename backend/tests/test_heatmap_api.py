"""GET /api/heatmap (A4, CORE-6): validation, pass-through of the shared fixture, errors."""

import json
from pathlib import Path

import httpx
import pytest
import respx
from freezegun import freeze_time
from rest_framework.test import APIClient

from clients import risk_engine

RISK_URL = "http://risk.test"
SHARED = Path(__file__).resolve().parents[2] / "shared" / "fixtures"
NOW = "2026-11-20T12:00:00Z"
PARAMS = {"bbox": "-111.9,39.7,-104.99,40.8", "start": "2026-11-21T13:00:00Z",
          "load_weight_lb": "42000"}


@pytest.fixture(autouse=True)
def _settings(settings, monkeypatch):
    settings.RISK_ENGINE_URL = RISK_URL
    settings.RISK_ENGINE_TOKEN = "test-token"
    monkeypatch.setattr(risk_engine, "RETRY_BACKOFF_S", 0)


def _get(**overrides):
    return APIClient().get("/api/heatmap", {**PARAMS, **overrides})


def _fixture():
    return httpx.Response(200, content=(SHARED / "heatmap_response.json").read_bytes(),
                          headers={"Content-Type": "application/json"})


@freeze_time(NOW)
@respx.mock
def test_passes_fixture_through_with_49_frames_and_sends_request():
    route = respx.post(f"{RISK_URL}/v1/heatmap").mock(return_value=_fixture())
    r = _get()
    assert r.status_code == 200
    body = r.json()
    assert body["hours"] == 49 and len(body["times"]) == 49
    assert len(body["variables"]["risk"]) == 49
    sent = json.loads(route.calls[0].request.content)
    assert sent["bbox"] == [-111.9, 39.7, -104.99, 40.8]
    assert sent["load_weight_lb"] == 42000 and sent["hours"] == 49 and sent["max_cells"] == 256
    assert sent["start"].startswith("2026-11-21T13:00:00")
    assert route.calls[0].request.headers["X-Internal-Token"] == "test-token"


@freeze_time(NOW)
@pytest.mark.parametrize(
    "patch, field",
    [
        ({"bbox": "1,2,3"}, "bbox"),
        ({"bbox": "-104,39,-112,41"}, "bbox"),  # min > max
        ({"bbox": "a,b,c,d"}, "bbox"),
        ({"bbox": "-130,20,-60,49"}, "bbox"),  # 70 deg wide
        ({"start": "2026-11-21T13:00:00"}, "start"),  # no offset
        ({"start": "2026-11-20T09:00:00Z"}, "start"),  # 3 h in the past
        ({"start": "2026-12-30T00:00:00Z"}, "start"),  # past the horizon
        ({"load_weight_lb": "0"}, "load_weight_lb"),
    ],
)
def test_validation_errors(patch, field):
    r = _get(**patch)
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR" and err["details"]["field"] == field


@freeze_time(NOW)
@respx.mock
def test_risk_engine_errors_map_to_502_and_504():
    respx.post(f"{RISK_URL}/v1/heatmap").mock(
        return_value=httpx.Response(502, json={"error": {"code": "UPSTREAM_ERROR", "message": "x"}})
    )
    assert _get().json()["error"]["code"] == "UPSTREAM_ERROR"
    respx.post(f"{RISK_URL}/v1/heatmap").mock(
        return_value=httpx.Response(504, json={"error": {"code": "UPSTREAM_TIMEOUT", "message": "x"}})
    )
    r = _get()
    assert r.status_code == 504 and r.json()["error"]["code"] == "UPSTREAM_TIMEOUT"


@freeze_time(NOW)
@respx.mock
def test_malformed_heatmap_from_risk_engine_is_rejected():
    bad = json.loads((SHARED / "heatmap_response.json").read_text())
    bad["variables"]["risk"] = bad["variables"]["risk"][:10]  # not 49 frames
    respx.post(f"{RISK_URL}/v1/heatmap").mock(return_value=httpx.Response(200, json=bad))
    r = _get()
    assert r.status_code == 502 and r.json()["error"]["code"] == "UPSTREAM_ERROR"


@freeze_time(NOW)
@respx.mock
def test_large_json_responses_are_gzipped_when_the_client_accepts_it():
    respx.post(f"{RISK_URL}/v1/heatmap").mock(return_value=_fixture())
    r = APIClient().get("/api/heatmap", PARAMS, HTTP_ACCEPT_ENCODING="gzip")
    assert r.status_code == 200
    assert r["Content-Encoding"] == "gzip"
    assert len(r.content) < len((SHARED / "heatmap_response.json").read_bytes())
