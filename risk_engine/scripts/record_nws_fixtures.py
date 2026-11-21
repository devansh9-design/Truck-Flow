"""Record real NWS /alerts/active responses into risk_engine/tests/fixtures/.

Usage (from risk_engine/):  python scripts/record_nws_fixtures.py LAT,LON [LAT,LON ...]
Saves nws_point_<n>.json for each point plus nws_out_of_bounds.json (a point in
Canada). Long free-text fields (description, instruction) are trimmed to keep
fixtures small; every other field is kept exactly as NWS sent it.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

URL = "https://api.weather.gov/alerts/active"
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
HEADERS = {
    "User-Agent": os.environ.get("NWS_USER_AGENT") or "truckrisk-fixture-recorder",
    "Accept": "application/geo+json",
}


def record(point: str, name: str) -> None:
    resp = httpx.get(URL, params={"point": point}, headers=HEADERS, timeout=20)
    body = resp.json()
    for f in body.get("features", []):
        p = f.get("properties", {})
        for key in ("description", "instruction"):
            if isinstance(p.get(key), str):
                p[key] = p[key][:200]
    (OUT / name).write_text(json.dumps({"status": resp.status_code, "body": body}, indent=1))
    print(f"{name}: HTTP {resp.status_code}, {len(body.get('features', []))} alerts")


if __name__ == "__main__":
    for i, pt in enumerate(sys.argv[1:], 1):
        record(pt, f"nws_point_{i}.json")
    record("43.65,-79.38", "nws_out_of_bounds.json")
