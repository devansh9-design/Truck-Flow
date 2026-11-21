"""Upstream HTTP helper: timeouts, one retry with backoff, and key-safe errors.

httpx exception messages include the full request URL, and HERE takes its key
as the `apiKey` query parameter. So we never let an httpx exception text reach
logs or responses: every failure is re-raised as our own error with a message
that names only the provider.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from api.errors import UpstreamError, UpstreamTimeout

log = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)
RETRY_BACKOFF_S = 0.5


def get_json(
    url: str,
    params: list[tuple[str, str]] | dict[str, Any],
    *,
    provider: str,
    client: httpx.Client | None = None,
) -> tuple[int, Any]:
    """GET `url` and return (status, parsed JSON).

    Retries once on a timeout, connection error or 5xx. Returns 4xx responses
    to the caller (they carry meaning, e.g. HERE's 400 for bad input) and
    raises UpstreamError / UpstreamTimeout for everything else.
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=TIMEOUT)
    try:
        last_exc: Exception | None = None
        for attempt in range(2):
            if attempt:
                time.sleep(RETRY_BACKOFF_S)
            try:
                resp = client.get(url, params=params)
            except httpx.TimeoutException as exc:
                last_exc = exc
                log.warning("%s timed out (attempt %d)", provider, attempt + 1)
                continue
            except httpx.TransportError as exc:
                last_exc = exc
                log.warning("%s connection failed (attempt %d): %s", provider, attempt + 1,
                            type(exc).__name__)
                continue
            if resp.status_code >= 500:
                last_exc = None
                log.warning("%s returned %d (attempt %d)", provider, resp.status_code, attempt + 1)
                continue
            try:
                return resp.status_code, resp.json()
            except ValueError:
                raise UpstreamError(f"{provider} returned an unreadable response.") from None
        if isinstance(last_exc, httpx.TimeoutException):
            raise UpstreamTimeout(f"{provider} did not respond in time. Please try again.")
        raise UpstreamError(f"{provider} is unavailable right now. Please try again.")
    finally:
        if owns_client:
            client.close()
