"""Chunk 2 core check (CORE-2 weather, CORE-3, CORE-4) against the running local stack.

Needs Flask (risk_engine) and Django running, with the same RISK_ENGINE_TOKEN.
Usage (from backend/):
    python scripts/core_check_chunk2.py
    python scripts/core_check_chunk2.py --origin "Chicago, IL" --destination "Denver, CO" --load 45000
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

import httpx

RANK_KEYS = ("no_travel_mi", "severe_mi", "high_mi", "avg_risk", "duration_s")
LEVELS = ("LOW", "MODERATE", "HIGH", "SEVERE", "NO_TRAVEL")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--origin", default="Denver, CO")
    ap.add_argument("--destination", default="Salt Lake City, UT")
    ap.add_argument("--load", type=float, default=42000)
    ap.add_argument("--interval", type=int, default=25, choices=(10, 25, 50))
    args = ap.parse_args()

    departure = (datetime.now(UTC) + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    body = {
        "origin": args.origin,
        "destination": args.destination,
        "departure_time": departure.isoformat(),
        "load_weight_lb": args.load,
        "interval_mi": args.interval,
    }
    t0 = datetime.now(UTC)
    r = httpx.post(f"{args.base}/api/analyze", json=body, timeout=120)
    took = (datetime.now(UTC) - t0).total_seconds()
    d = r.json()
    if r.status_code != 200:
        print(f"FAIL HTTP {r.status_code}: {d}")
        return 1

    print(f"{d['trip']['origin']['label']} -> {d['trip']['destination']['label']}, "
          f"load {d['trip']['load_weight_lb']:,.0f} lb, depart {d['trip']['departure_time']} ({took:.1f} s)")
    ok = len(d["routes"]) == 3
    for rt in d["routes"]:
        s = rt["summary"]
        cps = rt["checkpoints"]
        complete = all("weather" in c and "risk" in c and c["risk"]["reason"] for c in cps)
        hour_ok = all(abs(datetime.fromisoformat(c["forecast_hour"]) - datetime.fromisoformat(c["eta"]))
                      <= timedelta(minutes=30) for c in cps)
        ok &= complete and hour_ok
        counts = {lv: sum(c["risk"]["level"] == lv for c in cps) for lv in LEVELS}
        print(f"  #{rt['rank']} {rt['id']} {rt['label']}{'  <- RECOMMENDED' if rt['recommended'] else ''}")
        print(f"     {rt['distance_mi']} mi, {rt['duration_s'] / 3600:.2f} h | NT {s['no_travel_mi']} "
              f"| Severe {s['severe_mi']} | High {s['high_mi']} | avg {s['avg_risk']} | max {s['max_level']}"
              f" | warnings {rt['warnings']}")
        print(f"     {len(cps)} checkpoints, levels {counts}, weather+risk {'ok' if complete else 'MISSING'},"
              f" forecast hour {'ok' if hour_ok else 'BAD'}")
        worst = max(cps, key=lambda c: c["risk"]["score"])
        print(f"     worst: mile {worst['mile']} @ {worst['forecast_hour']} {worst['weather']} -> "
              f"{worst['risk']['reason']}")

    keys = [tuple(round(rt["summary"][k], 2) if k != "duration_s" else rt["duration_s"]
                  for k in RANK_KEYS) for rt in d["routes"]]
    sorted_ok = keys == sorted(keys)
    ok &= sorted_ok and d["routes"][0]["recommended"]
    rec = d["recommendation"]
    print(f"  recommendation: {rec['route_id']} decided_by={rec['decided_by']} - {rec['reason']}")
    print(f"  ranking order follows (no_travel, severe, high, avg, duration): {sorted_ok}")
    for n in d["notes"]:
        print(f"  note: {n}")
    print(f"\n{'PASS' if ok else 'FAIL'}: 3 ranked routes, ETA-hour weather + risk + reason on every checkpoint")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
