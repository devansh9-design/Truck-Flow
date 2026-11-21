"""Client for the internal Flask risk engine. Chunk 1: health only; /v1/evaluate lands in Chunk 2."""

from __future__ import annotations

import httpx
from django.conf import settings

HEALTH_TIMEOUT = httpx.Timeout(3.0)


def health() -> str:
    """'ok' if the risk engine answers /health, else 'down'. Never raises."""
    try:
        resp = httpx.get(f"{settings.RISK_ENGINE_URL}/health", timeout=HEALTH_TIMEOUT)
        if resp.status_code == 200 and resp.json().get("status") == "ok":
            return "ok"
    except (httpx.HTTPError, ValueError):
        pass
    return "down"
