"""Record how HERE Routing v8 reports "no route" and invalid requests (review item C1).

HERE's documentation site refuses automated fetches, so the response shapes are
confirmed from real responses instead. Two calls:
  1. a truck trip with no road connection (Honolulu -> Los Angeles)
  2. a deliberately invalid request (transportMode=spaceship)

Usage (from backend/): python scripts/probe_here_errors.py [--save]
Reads HERE_API_KEY from backend/.env and never prints it. With --save, writes the
bodies to tests/fixtures/here_no_route.json and here_bad_request.json; the request
URL (which carries the key) is never written.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
KEY = os.environ.get("HERE_API_KEY", "")
URL = "https://router.hereapi.com/v8/routes"
FIXTURES = ROOT / "tests" / "fixtures"


def call(params: list[tuple[str, str]]) -> tuple[int, object]:
    resp = httpx.get(URL, params=[*params, ("apiKey", KEY)], timeout=20)
    try:
        body = resp.json()
    except ValueError:
        body = resp.text[:500]
    return resp.status_code, body


def scrub(body: object) -> object:
    """Belt and braces: drop any string that happens to contain the key."""
    text = json.dumps(body)
    if KEY and KEY in text:
        raise SystemExit("Response echoed the API key; refusing to print or save it.")
    return body


def main() -> None:
    if not KEY:
        raise SystemExit("Set HERE_API_KEY in backend/.env first.")
    save = "--save" in sys.argv
    departure = (datetime.now(UTC) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    base = [
        ("departureTime", departure.isoformat()),
        ("return", "polyline,summary"),
        ("vehicle[grossWeight]", "34473"),
    ]
    cases = {
        "here_no_route.json": [("transportMode", "truck"), ("origin", "21.3069,-157.8583"),
                               ("destination", "34.0522,-118.2437"), *base],
        "here_bad_request.json": [("transportMode", "spaceship"), ("origin", "39.7392,-104.9903"),
                                  ("destination", "40.7608,-111.8910"), *base],
    }
    for name, params in cases.items():
        status, body = call(params)
        body = scrub(body)
        print(f"== {name}: HTTP {status}")
        print(json.dumps(body, indent=2)[:1500])
        if save:
            (FIXTURES / name).write_text(
                json.dumps({"status": status, "body": body}, indent=2) + "\n", encoding="utf-8"
            )


if __name__ == "__main__":
    main()
