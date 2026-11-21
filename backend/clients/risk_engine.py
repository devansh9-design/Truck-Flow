"""Client for the internal Flask risk engine (`X-Internal-Token`)."""

from __future__ import annotations

import logging
import time

import httpx
from django.conf import settings
from pydantic import ValidationError

from api.errors import BeyondForecastHorizon, UpstreamError, UpstreamTimeout
from truckrisk_schemas import CheckpointIn, CheckpointResult, EvaluateRequest, EvaluateResponse

log = logging.getLogger(__name__)

HEALTH_TIMEOUT = httpx.Timeout(3.0)
# Flask itself may make several Open-Meteo calls (each up to 15 s, retried once).
EVALUATE_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=15.0, pool=5.0)
RETRY_BACKOFF_S = 0.5
MAX_CHECKPOINTS = 1000
PROVIDER = "The weather service"


def health() -> str:
    """'ok' if the risk engine answers /health, else 'down'. Never raises."""
    try:
        resp = httpx.get(f"{settings.RISK_ENGINE_URL}/health", timeout=HEALTH_TIMEOUT)
        if resp.status_code == 200 and resp.json().get("status") == "ok":
            return "ok"
    except (httpx.HTTPError, ValueError):
        pass
    return "down"


def _post(path: str, body: str) -> httpx.Response:
    headers = {"X-Internal-Token": settings.RISK_ENGINE_TOKEN, "Content-Type": "application/json"}
    timed_out = False
    for attempt in range(2):
        if attempt:
            time.sleep(RETRY_BACKOFF_S)
        try:
            resp = httpx.post(f"{settings.RISK_ENGINE_URL}{path}", content=body, headers=headers,
                              timeout=EVALUATE_TIMEOUT)
        except httpx.TimeoutException:
            timed_out = True
            log.warning("risk engine timed out (attempt %d)", attempt + 1)
            continue
        except httpx.TransportError as exc:
            timed_out = False
            log.warning("risk engine unreachable (attempt %d): %s", attempt + 1, type(exc).__name__)
            continue
        if resp.status_code >= 500 and resp.status_code not in (502, 504):
            timed_out = False
            log.warning("risk engine returned %d (attempt %d)", resp.status_code, attempt + 1)
            continue
        return resp
    if timed_out:
        raise UpstreamTimeout(f"{PROVIDER} did not respond in time. Please try again.")
    raise UpstreamError(f"{PROVIDER} is unavailable right now. Please try again.")


def _error_of(resp: httpx.Response) -> dict:
    try:
        return resp.json().get("error") or {}
    except (ValueError, AttributeError):
        return {}


def evaluate(load_weight_lb: float, checkpoints: list[CheckpointIn]) -> list[CheckpointResult]:
    """Weather + risk for every checkpoint, same order. Raises on any mismatch (never partial)."""
    results: list[CheckpointResult] = []
    for i in range(0, len(checkpoints), MAX_CHECKPOINTS):
        chunk = checkpoints[i : i + MAX_CHECKPOINTS]
        req = EvaluateRequest(load_weight_lb=load_weight_lb, checkpoints=chunk)
        resp = _post("/v1/evaluate", req.model_dump_json())
        if resp.status_code != 200:
            err = _error_of(resp)
            code, message = err.get("code"), err.get("message")
            if code == "BEYOND_FORECAST_HORIZON":
                raise BeyondForecastHorizon(message or "Part of this trip is beyond the forecast.")
            if code == "UPSTREAM_TIMEOUT":
                raise UpstreamTimeout("The weather forecast service did not respond in time.")
            if resp.status_code == 401:
                log.error("risk engine rejected the internal token")
            raise UpstreamError(f"{PROVIDER} returned an error.")
        try:
            body = EvaluateResponse.model_validate_json(resp.content)
        except ValidationError:
            raise UpstreamError(f"{PROVIDER} returned an unreadable response.") from None
        if [r.id for r in body.results] != [c.id for c in chunk]:
            raise UpstreamError(f"{PROVIDER} returned results that do not match the request.")
        results.extend(body.results)
    return results
