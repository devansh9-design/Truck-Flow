"""HERE Geocoding & Search v7 (`GET /v1/geocode`).

Request params used: `q`, `limit`, `apiKey`.
Response fields read: `items[].title`, `items[].address.label`,
`items[].position.lat`, `items[].position.lng`.
"""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.core.cache import cache

from api.errors import PlaceNotFound, UpstreamError
from truckrisk_schemas import Place

from .http import get_json

PROVIDER = "HERE geocoding"
MAX_RESULTS = 5
CACHE_TTL_S = 24 * 3600


def _cache_key(query: str) -> str:
    norm = " ".join(query.lower().split())
    return "geocode:" + hashlib.sha256(norm.encode()).hexdigest()


def _require_key() -> str:
    if not settings.HERE_API_KEY:
        raise UpstreamError("HERE_API_KEY is not configured on the server.")
    return settings.HERE_API_KEY


def parse_items(payload: dict) -> list[Place]:
    places: list[Place] = []
    for item in payload.get("items", []):
        pos = item.get("position") or {}
        if "lat" not in pos or "lng" not in pos:
            continue
        label = (item.get("address") or {}).get("label") or item.get("title") or ""
        places.append(Place(label=label, lat=pos["lat"], lon=pos["lng"]))
    return places[:MAX_RESULTS]


def geocode(query: str) -> list[Place]:
    """Return up to 5 candidate places (cached 24 h)."""
    key = _cache_key(query)
    cached = cache.get(key)
    if cached is not None:
        return [Place.model_validate(p) for p in cached]

    status, payload = get_json(
        settings.HERE_GEOCODE_URL,
        {"q": query, "limit": MAX_RESULTS, "apiKey": _require_key()},
        provider=PROVIDER,
    )
    if status in (401, 403):
        raise UpstreamError("HERE rejected the API key.")
    if status >= 400:
        raise UpstreamError(f"{PROVIDER} rejected the request.")

    places = parse_items(payload)
    cache.set(key, [p.model_dump() for p in places], CACHE_TTL_S)
    return places


def resolve_place(value: str | dict, field: str) -> Place:
    """Turn a form value (free text or {label, lat, lon}) into one Place."""
    if isinstance(value, dict):
        return Place.model_validate(value)
    results = geocode(value)
    if not results:
        raise PlaceNotFound(f'Could not find "{value}".', {"field": field})
    return results[0]
