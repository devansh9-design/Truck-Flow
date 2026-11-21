"""T5 performance check against a running stack (live HERE + Open-Meteo).

Times /api/analyze for a ~1,000 mi trip at 25 mi and 10 mi intervals, cold (first run)
and warm (forecast cache filled), then the heatmap for the same corridor.
Targets (docs/Testing strategy.md §6): analyze 25 mi <= 8 s, 10 mi <= 12 s, heatmap <= 1.5 MB.

Usage (from backend/):  python scripts/perf_check.py [--base URL] [--origin ...] [--destination ...]
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime, timedelta

import httpx


def timed(fn):
    t0 = time.perf_counter()
    r = fn()
    return r, time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--origin", default="Chicago, IL")
    ap.add_argument("--destination", default="Denver, CO")
    args = ap.parse_args()
    dep = (datetime.now(UTC) + timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)

    def analyze(interval: int):
        return httpx.post(f"{args.base}/api/analyze", timeout=180, json={
            "origin": args.origin, "destination": args.destination, "departure_time": dep.isoformat(),
            "load_weight_lb": 42000, "interval_mi": interval,
        })

    rows = []
    ok = True
    for interval, target in ((25, 8.0), (10, 12.0)):
        for label in ("cold", "warm"):
            r, s = timed(lambda iv=interval: analyze(iv))
            if r.status_code != 200:
                print(f"FAIL: analyze {interval} mi returned {r.status_code}: {r.text[:200]}")
                return 1
            d = r.json()
            miles = round(max(x["distance_mi"] for x in d["routes"]))
            cps = sum(len(x["checkpoints"]) for x in d["routes"])
            met = s <= target
            ok &= met or label == "cold"  # the target is for a warm cache
            kb = len(r.content) / 1024
            detail = f"{len(d['routes'])} routes, {cps} checkpoints, ~{miles} mi, {kb:.0f} KB"
            rows.append((f"analyze {interval} mi, {label}", f"{s:.2f} s", f"<= {target:.0f} s (warm)",
                         "ok" if met else ("over" if label == "warm" else "info"), detail))

    h, s = timed(lambda: httpx.get(f"{args.base}/api/heatmap", timeout=180, params={
        "bbox": ",".join(str(b) for b in d["corridor"]["bbox"]),
        "start": d["trip"]["departure_time"], "load_weight_lb": 42000,
    }))
    size = len(h.content)
    hm = h.json()
    ok &= h.status_code == 200 and size <= 1_500_000
    rows.append(("heatmap (after analyze)", f"{s:.2f} s", "-", "info",
                 f"{hm['grid']['rows']}x{hm['grid']['cols']} cells x 49 h"))
    rows.append(("heatmap payload", f"{size / 1024:.0f} KB", "<= 1,500 KB",
                 "ok" if size <= 1_500_000 else "over", ""))

    w = [max(len(str(r[i])) for r in rows) for i in range(5)]
    print(f"{args.origin} -> {args.destination}, departure {dep.isoformat()}")
    for r in rows:
        print("  " + "  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)))
    print(f"\n{'PASS' if ok else 'FAIL'}: performance targets")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
