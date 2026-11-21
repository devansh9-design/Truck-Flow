"""A10 place suggestions: HERE Autocomplete + Lookup, against recorded responses."""

import json
from pathlib import Path

import httpx
import pytest
import respx
from django.conf import settings
from django.core.cache import cache
from rest_framework.test import APIClient

from geo import http as geo_http

FIX = Path(__file__).parent / "fixtures"


def recorded(name: str) -> httpx.Response:
    d = json.loads((FIX / f"here_{name}.json").read_text(encoding="utf-8"))
    return httpx.Response(d["status"], json=d["body"])


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    cache.clear()
    monkeypatch.setattr(geo_http, "RETRY_BACKOFF_S", 0)
    yield
    cache.clear()


def get(path, **params):
    return APIClient().get(path, params)


@respx.mock
def test_suggestions_from_recorded_autocomplete_with_country_filter():
    route = respx.get(settings.HERE_AUTOCOMPLETE_URL).mock(return_value=recorded("autocomplete_barc_esp"))
    r = get("/api/places/suggest", q="Barc", country="es")
    assert r.status_code == 200
    s = r.json()["suggestions"]
    assert s[0]["label"].startswith("Barcelona") and s[0]["country"] == "ES"
    assert s[0]["id"].startswith("here:") and len(s) <= 5
    sent = route.calls[0].request.url.params
    assert sent["in"] == "countryCode:ESP" and sent["q"] == "Barc" and sent["lang"] == "en"
    assert "at" not in sent


@respx.mock
def test_any_country_and_position_bias():
    route = respx.get(settings.HERE_AUTOCOMPLETE_URL).mock(
        return_value=recorded("autocomplete_spring_usa_at"))
    r = get("/api/places/suggest", q="Spring", near="39.7392,-104.9903")
    assert r.status_code == 200
    sent = route.calls[0].request.url.params
    assert "in" not in sent and sent["at"] == "39.7,-105.0"  # rounded for cache hits
    assert r.json()["suggestions"][1]["label"] == "Springfield, CO, United States"


@respx.mock
def test_whole_countries_are_not_suggested():
    """A one-letter query can return a country ("Bharat"): not a place to route to."""
    respx.get(settings.HERE_AUTOCOMPLETE_URL).mock(return_value=recorded("autocomplete_b"))
    labels = [s["label"] for s in get("/api/places/suggest", q="B").json()["suggestions"]]
    assert "Bharat" not in labels


@respx.mock
def test_suggestions_are_cached():
    route = respx.get(settings.HERE_AUTOCOMPLETE_URL).mock(return_value=recorded("autocomplete_barc_en"))
    get("/api/places/suggest", q="Barc")
    get("/api/places/suggest", q="  barc ")
    assert route.call_count == 1


@respx.mock
def test_unknown_country_gives_no_suggestions_upstream():
    respx.get(settings.HERE_AUTOCOMPLETE_URL).mock(return_value=recorded("autocomplete_zz_bad_country"))
    # Our own validation rejects it before HERE is asked.
    r = get("/api/places/suggest", q="Barc", country="ZZ")
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "country"


@pytest.mark.parametrize("params, field", [
    ({"q": ""}, "q"),
    ({"q": "x" * 121}, "q"),
    ({"q": "Barc", "near": "abc"}, "near"),
    ({"q": "Barc", "near": "91,0"}, "near"),
])
def test_suggest_validation(params, field):
    r = get("/api/places/suggest", **params)
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == field


@respx.mock
def test_lookup_returns_exact_place():
    first_id = json.loads((FIX / "here_autocomplete_barc_esp.json").read_text(encoding="utf-8"))[
        "body"]["items"][0]["id"]
    route = respx.get(settings.HERE_LOOKUP_URL).mock(return_value=recorded("lookup_first"))
    r = get("/api/places/lookup", id=first_id)
    assert r.status_code == 200
    assert r.json() == {"label": "Barcelona, Catalonia, Spain", "lat": 41.38804, "lon": 2.17001}
    assert route.calls[0].request.url.params["id"] == first_id
    get("/api/places/lookup", id=first_id)
    assert route.call_count == 1  # cached


@respx.mock
def test_lookup_unknown_id_is_place_not_found():
    respx.get(settings.HERE_LOOKUP_URL).mock(return_value=recorded("lookup_bad_id"))
    r = get("/api/places/lookup", id="here:cm:namedplace:000")
    assert r.status_code == 404 and r.json()["error"]["code"] == "PLACE_NOT_FOUND"


@pytest.mark.parametrize("bad", ["", "abc", "here:", "here:<script>", "x" * 400])
def test_lookup_rejects_malformed_ids(bad):
    r = get("/api/places/lookup", id=bad)
    assert r.status_code == 400


@respx.mock
def test_upstream_failures():
    respx.get(settings.HERE_AUTOCOMPLETE_URL).mock(return_value=httpx.Response(401, json={}))
    assert get("/api/places/suggest", q="Barc").json()["error"]["code"] == "UPSTREAM_ERROR"
    respx.get(settings.HERE_LOOKUP_URL).mock(return_value=httpx.Response(200, json={"title": "x"}))
    r = get("/api/places/lookup", id="here:cm:namedplace:1")
    assert r.status_code == 502


def test_key_never_in_error_messages(monkeypatch):
    """Errors name the provider only, never the request URL (which carries the key)."""
    with respx.mock:
        respx.get(settings.HERE_AUTOCOMPLETE_URL).mock(side_effect=httpx.ConnectError("boom"))
        body = get("/api/places/suggest", q="Barc").content.decode()
    assert settings.HERE_API_KEY not in body
