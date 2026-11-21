"""Chunk 4 core check (CORE-6) against a running stack: heatmap over the corridor, 0-48 h.

(There is no chunk 3 script: Chunk 3 is the frontend, checked in the browser and by the E2E suite.)

Runs one analysis, then fetches the heatmap exactly as the browser does, and checks:
  * 49 hourly frames; hour 0 = the departure hour (D14)
  * every frame has rows x cols values for each variable
  * the grid covers every route point (the corridor)
  * risk values are 1-5 scores (same rules as checkpoints) or null
  * payload under 1.5 MB (NFR-3)

Usage (from backend/):
    python scripts/core_check_chunk4.py
    python scripts/core_check_chunk4.py --base https://your-api.onrender.com
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

import httpx

VARIABLES = ("risk", "wind_mph", "rain_in_hr", "snow_in_hr")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--origin", default="Denver, CO")
    ap.add_argument("--destination", default="Salt Lake City, UT")
    ap.add_argument("--load", type=float, default=42000)
    args = ap.parse_args()

    departure = (datetime.now(UTC) + timedelta(hours=2)).replace(minute=30, second=0, microsecond=0)
    r = httpx.post(f"{args.base}/api/analyze", timeout=120, json={
        "origin": args.origin, "destination": args.destination,
        "departure_time": departure.isoformat(), "load_weight_lb": args.load, "interval_mi": 25,
    })
    if r.status_code != 200:
        print(f"FAIL: analyze returned {r.status_code}: {r.text[:300]}")
        return 1
    d = r.json()
    hour0 = datetime.fromisoformat(d["trip"]["departure_time"]).replace(minute=0, second=0)
    bbox = d["corridor"]["bbox"]

    t0 = datetime.now(UTC)
    h = httpx.get(f"{args.base}/api/heatmap", timeout=120, params={
        "bbox": ",".join(str(b) for b in bbox),
        "start": hour0.isoformat().replace("+00:00", "Z"),
        "load_weight_lb": args.load,
    })
    took = (datetime.now(UTC) - t0).total_seconds()
    if h.status_code != 200:
        print(f"FAIL: heatmap returned {h.status_code}: {h.text[:300]}")
        return 1
    hm = h.json()
    g = hm["grid"]
    n = g["rows"] * g["cols"]
    size = len(h.content)

    checks: dict[str, bool] = {}
    checks["49 hourly frames"] = hm["hours"] == 49 and len(hm["times"]) == 49
    times = [datetime.fromisoformat(t) for t in hm["times"]]
    checks["hour 0 = departure hour"] = times[0] == hour0
    checks["frames 1 h apart, 0-48 h"] = all(
        b - a == timedelta(hours=1) for a, b in zip(times, times[1:], strict=False)
    ) and times[-1] - times[0] == timedelta(hours=48)
    checks["every frame rows x cols"] = all(
        len(hm["variables"][v]) == 49 and all(len(f) == n for f in hm["variables"][v]) for v in VARIABLES
    )
    lat_lo = g["lats"][0] - (g["lats"][1] - g["lats"][0]) / 2
    lat_hi = g["lats"][-1] + (g["lats"][1] - g["lats"][0]) / 2
    lon_lo = g["lons"][0] - (g["lons"][1] - g["lons"][0]) / 2
    lon_hi = g["lons"][-1] + (g["lons"][1] - g["lons"][0]) / 2
    pts = [p for rt in d["routes"] for p in rt["geometry"]["coordinates"]]
    checks["grid covers every route point"] = all(
        lon_lo <= lon <= lon_hi and lat_lo <= lat <= lat_hi for lon, lat in pts
    )
    risk_vals = {v for f in hm["variables"]["risk"] for v in f}
    checks["risk values are 1-5 or null"] = risk_vals <= {1, 2, 3, 4, 5, None}
    checks["payload <= 1.5 MB"] = size <= 1_500_000

    nulls = sum(v is None for f in hm["variables"]["risk"] for v in f)
    print(f"{d['trip']['origin']['label']} -> {d['trip']['destination']['label']}")
    print(f"  grid {g['rows']} x {g['cols']} = {n} cells, lat {lat_lo:.2f}..{lat_hi:.2f}, "
          f"lon {lon_lo:.2f}..{lon_hi:.2f}")
    print(f"  hours {hm['times'][0]} .. {hm['times'][-1]}, payload {size / 1024:.0f} KB, {took:.1f} s")
    print(f"  risk scores seen: {sorted(v for v in risk_vals if v is not None)}, null cell-hours: {nulls}")
    for name, ok in checks.items():
        print(f"  [{'ok' if ok else 'FAIL'}] {name}")
    ok = all(checks.values())
    print(f"\n{'PASS' if ok else 'FAIL'}: heatmap covers the corridor with 49 frames (0-48 h)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
