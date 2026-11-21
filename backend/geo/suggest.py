"""Place suggestions while typing (A10): HERE Autocomplete + Lookup.

Confirmed from recorded responses (tests/fixtures/here_autocomplete_*.json, here_lookup_*.json;
scripts/probe_here_suggest.py):
* Autocomplete `GET /v1/autocomplete?q=&limit=&lang=&in=countryCode:ESP&at=lat,lng` returns
  `items[]` with `id`, `title`, `resultType`, `address.label`, `address.countryCode`
  (ISO alpha-3) and **no position**. It ranks prefixes well ("Barc" -> Barcelona first).
  An unknown country code gives `{"items": []}`. A one-letter query can return whole
  countries (`resultType: administrativeArea`), which are dropped here.
* Lookup `GET /v1/lookup?id=` returns the place with `position.lat/lng` and `address.label`;
  an unknown id is 404 `{"title": "Unknown Location ID"}`.

Autocomplete was chosen over Autosuggest (mixes in nearby streets and businesses) and
Geocode (poor on partial words: "Barc" -> "Barca").
"""

from __future__ import annotations

import hashlib
import re

from django.conf import settings
from django.core.cache import cache

from accounts.countries import ALPHA2, ALPHA3
from api.errors import PlaceNotFound, UpstreamError
from truckrisk_schemas import Place

from .geocode import _require_key
from .http import get_json

PROVIDER = "HERE place search"
MAX_SUGGESTIONS = 5
FETCH_LIMIT = 8  # some results are dropped (whole countries/regions)
CACHE_TTL_S = 24 * 3600
# Places a truck can be routed to; "administrativeArea" (a country or state) is not one.
ROUTABLE = {"locality", "street", "houseNumber", "intersection", "place", "postalCodePoint",
            "addressBlock"}
PLACE_ID = re.compile(r"^here:[A-Za-z0-9:_\-.=]{1,300}$")


def _key(*parts: object) -> str:
    raw = "|".join(str(p) for p in parts).lower()
    return "suggest:" + hashlib.sha256(raw.encode()).hexdigest()


def suggest(query: str, country: str | None = None,
            near: tuple[float, float] | None = None) -> list[dict]:
    """Up to 5 suggestions `{id, label, country}` (country = ISO alpha-2 or "")."""
    q = " ".join(query.split())
    near_r = (round(near[0], 1), round(near[1], 1)) if near else None
    key = _key("v1", q, country or "", near_r or "")
    cached = cache.get(key)
    if cached is not None:
        return cached

    params: list[tuple[str, str]] = [("q", q), ("limit", str(FETCH_LIMIT)), ("lang", "en"),
                                     ("apiKey", _require_key())]
    if country:
        params.append(("in", f"countryCode:{ALPHA3[country]}"))
    if near_r:
        params.append(("at", f"{near_r[0]},{near_r[1]}"))
    status, payload = get_json(settings.HERE_AUTOCOMPLETE_URL, params, provider=PROVIDER)
    if status in (401, 403):
        raise UpstreamError("HERE rejected the API key.")
    if status >= 400:
        raise UpstreamError(f"{PROVIDER} rejected the request.")

    out: list[dict] = []
    for item in payload.get("items", []) if isinstance(payload, dict) else []:
        address = item.get("address") or {}
        label = address.get("label") or item.get("title")
        if item.get("resultType") not in ROUTABLE or not item.get("id") or not label:
            continue
        out.append({"id": item["id"], "label": label,
                    "country": ALPHA2.get(address.get("countryCode", ""), "")})
        if len(out) == MAX_SUGGESTIONS:
            break
    cache.set(key, out, CACHE_TTL_S)
    return out


def lookup(place_id: str) -> Place:
    """Exact coordinates for a suggestion id (cached 24 h)."""
    key = _key("lookup", place_id)
    cached = cache.get(key)
    if cached is not None:
        return Place.model_validate(cached)
    status, payload = get_json(settings.HERE_LOOKUP_URL, [("id", place_id), ("lang", "en"),
                                                          ("apiKey", _require_key())],
                               provider=PROVIDER)
    if status == 404:
        raise PlaceNotFound("That place could not be found. Please search again.")
    if status in (401, 403):
        raise UpstreamError("HERE rejected the API key.")
    if status >= 400:
        raise UpstreamError(f"{PROVIDER} rejected the request.")
    pos = payload.get("position") or {}
    if "lat" not in pos or "lng" not in pos:
        raise UpstreamError(f"{PROVIDER} returned a place without a position.")
    label = (payload.get("address") or {}).get("label") or payload.get("title") or ""
    place = Place(label=label, lat=pos["lat"], lon=pos["lng"])
    cache.set(key, place.model_dump(), CACHE_TTL_S)
    return place
