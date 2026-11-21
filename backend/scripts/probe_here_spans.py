"""Which `spans` setting gives per-segment durations? Prints span counts and payload size only.

Usage (from backend/): python scripts/probe_here_spans.py
Reads HERE_API_KEY from backend/.env; never prints it or saves anything.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
KEY = os.environ.get("HERE_API_KEY", "")

VARIANTS = [
    "length,duration",
    "length,duration,speedLimit",
    "length,duration,maxSpeed",
    "length,duration,dynamicSpeedInfo",
    "length,duration,segmentRef",
]


def main() -> None:
    if not KEY:
        raise SystemExit("Set HERE_API_KEY in backend/.env first.")
    departure = (datetime.now(UTC) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    for spans in VARIANTS:
        params = [
            ("transportMode", "truck"),
            ("origin", "39.7392,-104.9903"),
            ("destination", "40.7608,-111.8910"),
            ("departureTime", departure.isoformat()),
            ("alternatives", "0"),
            ("return", "polyline,summary"),
            ("spans", spans),
            ("vehicle[grossWeight]", "34927"),
            ("apiKey", KEY),
        ]
        r = httpx.get("https://router.hereapi.com/v8/routes", params=params, timeout=30)
        if r.status_code != 200:
            title = r.json().get("title", "") if r.headers.get("content-type", "").startswith(
                "application/json") else ""
            print(f"{spans:40s} HTTP {r.status_code} {title}")
            continue
        sec = r.json()["routes"][0]["sections"][0]
        spans_list = sec.get("spans") or []
        durs = [s.get("duration") for s in spans_list]
        lens = [s.get("length") for s in spans_list]
        speeds = sorted({round(ln / d * 2.23694) for ln, d in zip(lens, durs, strict=False)
                         if ln and d})
        print(f"{spans:40s} spans={len(spans_list):6d} bytes={len(r.content):9,d} "
              f"speeds_mph={speeds[:6]}...{speeds[-3:]}")


if __name__ == "__main__":
    main()
