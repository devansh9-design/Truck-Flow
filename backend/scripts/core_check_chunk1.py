"""Chunk 1 core check (CORE-1, CORE-2 checkpoints + ETA) against the running local Django.

Usage (from backend/, with `python manage.py runserver` running and DJANGO_DEBUG=true):
    python scripts/core_check_chunk1.py
    python scripts/core_check_chunk1.py --origin "Chicago, IL" --destination "Denver, CO" --interval 50
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from routing.overlap import shared_fraction  # noqa: E402
from routing.track import SectionInput, build_track, haversine_mi  # noqa: E402


def _track(coords_lonlat):
    coords = [(lat, lon) for lon, lat in coords_lonlat]
    length = sum(haversine_mi(coords[i - 1], coords[i]) for i in range(1, len(coords)))
    return build_track([SectionInput(coords=coords, length_mi=length, duration_s=1)])


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
    r = httpx.post(f"{args.base}/api/debug/routes", json=body, timeout=60)
    data = r.json()
    if r.status_code != 200:
        print(f"FAIL HTTP {r.status_code}: {data}")
        return 1

    trip = data["trip"]
    print(f"{trip['origin']['label']} -> {trip['destination']['label']}, depart {trip['departure_time']}")
    for note in data["notes"]:
        print(f"  note: {note}")

    ok = True
    routes = data["routes"]
    tracks = [_track(rt["geometry"]["coordinates"]) for rt in routes]
    for rt in routes:
        cps = rt["checkpoints"]
        gaps = [round(b["mile"] - a["mile"], 1) for a, b in zip(cps, cps[1:], strict=False)]
        spacing_ok = all(g == args.interval for g in gaps[:-1]) and 0 < gaps[-1] <= args.interval
        eta_ok = all(c.get("eta") and c.get("forecast_hour") for c in cps)
        ends_ok = cps[0]["mile"] == 0 and abs(cps[-1]["mile"] - rt["distance_mi"]) <= 0.1
        ok &= spacing_ok and eta_ok and ends_ok
        print(
            f"  {rt['id']} {rt['label']} [{rt['source']}]: {rt['distance_mi']} mi, "
            f"{rt['duration_s'] / 3600:.2f} h, arrive {rt['arrival_time']}, "
            f"{len(cps)} checkpoints (spacing {'ok' if spacing_ok else gaps}, "
            f"ETAs {'ok' if eta_ok else 'MISSING'}, ends {'ok' if ends_ok else 'BAD'})"
        )
        print(f"     first ETAs: {[c['eta'][11:16] for c in cps[:4]]} ... last {cps[-1]['eta']}")

    for i in range(len(tracks)):
        for j in range(i + 1, len(tracks)):
            share = shared_fraction(tracks[i], tracks[j])
            ok &= share <= 0.9
            print(f"  shared length {routes[i]['id']}~{routes[j]['id']}: {share:.0%}")

    three = len(routes) == 3
    print(f"\n{'PASS' if ok and three else 'FAIL'}: {len(routes)} distinct routes; checkpoints + ETAs "
          f"{'ok' if ok else 'have problems'}")
    return 0 if ok and three else 1


if __name__ == "__main__":
    raise SystemExit(main())
