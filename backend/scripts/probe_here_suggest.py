"""Record HERE search-as-you-type responses to choose the autocomplete source.

HERE's documentation site refuses automated fetches, so shapes are confirmed from real
responses. Candidates for a partial query ("Barc"), with and without a country filter:
  * Autocomplete  /v1/autocomplete  (address completion)
  * Autosuggest   /v1/autosuggest   (needs a position bias: `at`)
  * Geocode       /v1/geocode       (what the app already uses for full queries)

Usage (from backend/): python scripts/probe_here_suggest.py [--save]
The bad-id and one-letter fixtures (here_lookup_bad_id.json, here_autocomplete_b.json) were
recorded the same way.
Reads HERE_API_KEY from backend/.env and never prints or saves it.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
KEY = os.environ.get("HERE_API_KEY", "")
FIXTURES = ROOT / "tests" / "fixtures"

CALLS = {
    "autocomplete_barc": ("https://autocomplete.search.hereapi.com/v1/autocomplete",
                          [("q", "Barc"), ("limit", "5")]),
    "autocomplete_barc_esp": ("https://autocomplete.search.hereapi.com/v1/autocomplete",
                              [("q", "Barc"), ("limit", "5"), ("in", "countryCode:ESP")]),
    "autosuggest_barc_esp": ("https://autosuggest.search.hereapi.com/v1/autosuggest",
                             [("q", "Barc"), ("limit", "5"), ("at", "40.4,-3.7"),
                              ("in", "countryCode:ESP")]),
    "geocode_barc_esp": ("https://geocode.search.hereapi.com/v1/geocode",
                         [("q", "Barc"), ("limit", "5"), ("in", "countryCode:ESP")]),
    "autocomplete_barc_en": ("https://autocomplete.search.hereapi.com/v1/autocomplete",
                             [("q", "Barc"), ("limit", "5"), ("lang", "en")]),
    "autocomplete_spring_usa_at": ("https://autocomplete.search.hereapi.com/v1/autocomplete",
                                   [("q", "Spring"), ("limit", "5"), ("lang", "en"),
                                    ("in", "countryCode:USA"), ("at", "39.74,-104.99")]),
    "autocomplete_zz_bad_country": ("https://autocomplete.search.hereapi.com/v1/autocomplete",
                                    [("q", "Barc"), ("in", "countryCode:ZZZ")]),
}


def call(url: str, params: list[tuple[str, str]]) -> tuple[int, object]:
    resp = httpx.get(url, params=[*params, ("apiKey", KEY)], timeout=20)
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, resp.text[:300]


def summary(body: object) -> list[str]:
    if not isinstance(body, dict):
        return [str(body)[:200]]
    out = []
    for it in body.get("items", [])[:5]:
        out.append(
            f"  {it.get('resultType')}: {it.get('title')!r} | label={it.get('address', {}).get('label')!r}"
            f" | countryCode={it.get('address', {}).get('countryCode')} | position={it.get('position')}"
            f" | id={'yes' if it.get('id') else 'no'} | keys={sorted(it)}"
        )
    return out or [f"  (no items) keys={sorted(body)} {json.dumps(body)[:200]}"]


if __name__ == "__main__":
    if not KEY:
        sys.exit("HERE_API_KEY missing in backend/.env")
    results = {}
    for name, (url, params) in CALLS.items():
        if not url:
            continue
        status, body = call(url, params)
        results[name] = {"status": status, "body": body}
        print(f"{name}: HTTP {status}")
        print("\n".join(summary(body)))
    # Lookup by id (Autocomplete returns ids but maybe no coordinates).
    ac = results.get("autocomplete_barc_esp", {}).get("body", {})
    first = (ac.get("items") or [{}])[0] if isinstance(ac, dict) else {}
    if first.get("id"):
        status, body = call("https://lookup.search.hereapi.com/v1/lookup",
                            [("id", first["id"]), ("lang", "en")])
        results["lookup_first"] = {"status": status, "body": body}
        position = body.get("position") if isinstance(body, dict) else None
        print(f"lookup_first: HTTP {status} position={position}")
    if "--save" in sys.argv:
        for name, data in results.items():
            (FIXTURES / f"here_{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False),
                                                       encoding="utf-8")
        print("saved")
