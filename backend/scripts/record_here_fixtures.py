"""Record real HERE responses once, for fixture-based tests (Testing strategy §9).

Reads HERE_API_KEY from backend/.env. Writes JSON to backend/tests/fixtures/.
The key is never printed, and the script refuses to save any file containing it.

Usage (from backend/):
    python scripts/record_here_fixtures.py
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
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from truckrisk_schemas import lb_to_kg  # noqa: E402

OUT = ROOT / "tests" / "fixtures"
KEY = os.environ.get("HERE_API_KEY", "")
TARE = float(os.environ.get("TRUCK_TARE_LB", "35000"))


def save(name: str, payload: dict) -> None:
    text = json.dumps(payload, indent=1)
    if KEY and KEY in text:
        raise SystemExit(f"Refusing to save {name}: it contains the API key.")
    (OUT / name).write_text(text, encoding="utf-8")
    print(f"saved tests/fixtures/{name} ({len(text):,} bytes)")


def get(url: str, params) -> dict:
    r = httpx.get(url, params=params, timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"HERE returned HTTP {r.status_code} for {url}: {r.text[:300]}")
    return r.json()


def main() -> None:
    if not KEY:
        raise SystemExit("Set HERE_API_KEY in backend/.env first.")
    OUT.mkdir(parents=True, exist_ok=True)

    geo = get("https://geocode.search.hereapi.com/v1/geocode",
              {"q": "Denver, CO", "limit": 5, "apiKey": KEY})
    save("here_geocode_denver.json", geo)

    departure = (datetime.now(UTC) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    params = [
        ("transportMode", "truck"),
        ("origin", "39.7392,-104.9903"),
        ("destination", "40.7608,-111.8910"),
        ("departureTime", departure.isoformat()),
        ("alternatives", "5"),
        ("return", "polyline,summary"),
        ("spans", "length,duration,speedLimit"),
        ("vehicle[grossWeight]", str(round(lb_to_kg(42000 + TARE)))),
        ("apiKey", KEY),
    ]
    routes = get("https://router.hereapi.com/v8/routes", params)
    save("here_routes_denver_slc.json", routes)
    print(f"routes returned: {len(routes.get('routes', []))}")


if __name__ == "__main__":
    main()
