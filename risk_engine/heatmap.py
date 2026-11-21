"""Corridor heatmap: a grid over the trip corridor x 49 hourly frames (CORE-6, B3).

Architecture C technique: the whole 0-48 h block is computed once per corridor
and returned in one response, so the browser's slider only swaps preloaded
frames and never calls the network while scrubbing (NFR-2).

* Corridor  = the request bbox (all routes) buffered by CORRIDOR_BUFFER_MI.
* Grid      = at most `max_cells` cells, shaped so cells are roughly square in
              miles; values are sampled at each cell centre.
* Time base = hour 0 is `start` rounded down to the hour (D14); 49 frames.
* Weather   = the same Open-Meteo provider and cache as /v1/evaluate.
* Risk      = the same rules as checkpoints (rules.evaluate), as the 1-5 score.
* Missing   = a cell/hour without usable data is null, never zero or Low.
"""

from __future__ import annotations

import json
import math
import threading
from datetime import UTC, datetime, timedelta

from cachetools import TTLCache
from weather import BeyondForecast, ForecastProvider, IncompleteWeather, cell_of

from rules import evaluate as classify
from truckrisk_schemas import HEATMAP_HOURS, HeatmapRequest, HeatmapResponse, iso_z

CORRIDOR_BUFFER_MI = 25.0
MI_PER_DEG_LAT = 69.0
CACHE_TTL_S = 30 * 60

_cache: TTLCache[tuple, HeatmapResponse] = TTLCache(maxsize=64, ttl=CACHE_TTL_S)
_lock = threading.Lock()


def buffered_bbox(bbox: list[float], buffer_mi: float = CORRIDOR_BUFFER_MI) -> list[float]:
    min_lon, min_lat, max_lon, max_lat = bbox
    mid = math.radians((min_lat + max_lat) / 2)
    dlat = buffer_mi / MI_PER_DEG_LAT
    dlon = buffer_mi / (MI_PER_DEG_LAT * max(math.cos(mid), 0.05))
    return [
        max(min_lon - dlon, -180.0),
        max(min_lat - dlat, -85.0),
        min(max_lon + dlon, 180.0),
        min(max_lat + dlat, 85.0),
    ]


def grid_shape(bbox: list[float], max_cells: int) -> tuple[int, int]:
    """(rows, cols) with rows * cols <= max_cells and cells roughly square in miles."""
    min_lon, min_lat, max_lon, max_lat = bbox
    mid = math.radians((min_lat + max_lat) / 2)
    width = (max_lon - min_lon) * MI_PER_DEG_LAT * max(math.cos(mid), 0.05)
    height = (max_lat - min_lat) * MI_PER_DEG_LAT
    aspect = width / height if height > 0 else 1.0
    cols = max(2, min(max_cells // 2, round(math.sqrt(max_cells * aspect))))
    rows = max(2, min(max_cells // cols, round(cols / aspect)))
    return rows, cols


def centres(lo: float, hi: float, n: int) -> list[float]:
    step = (hi - lo) / n
    return [round(lo + (i + 0.5) * step, 4) for i in range(n)]


def _round(v: float | None, digits: int) -> float | None:
    return None if v is None else round(v, digits)


def build_heatmap(req: HeatmapRequest, provider: ForecastProvider) -> HeatmapResponse:
    start = req.start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    key = (tuple(round(b, 2) for b in req.bbox), start, req.load_weight_lb, req.max_cells)
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit

    box = buffered_bbox(req.bbox)
    rows, cols = grid_shape(box, req.max_cells)
    lats = centres(box[1], box[3], rows)
    lons = centres(box[0], box[2], cols)
    points = [(lat, lon) for lat in lats for lon in lons]  # row-major, south-west first
    cells = [cell_of(lat, lon) for lat, lon in points]
    series, _meta = provider.series(cells)

    times = [start + timedelta(hours=h) for h in range(HEATMAP_HOURS)]
    risk: list[list[float | None]] = []
    wind: list[list[float | None]] = []
    rain: list[list[float | None]] = []
    snow: list[list[float | None]] = []
    for hour in times:
        fr: list[float | None] = []
        fw: list[float | None] = []
        fra: list[float | None] = []
        fs: list[float | None] = []
        for cell in cells:
            try:
                w = series[cell].at(hour)
            except (BeyondForecast, IncompleteWeather):
                fr.append(None)
                fw.append(None)
                fra.append(None)
                fs.append(None)
                continue
            fr.append(classify(w, req.load_weight_lb).score)
            fw.append(_round(w.wind_mph, 1))
            fra.append(_round(w.rain_in_hr, 2))
            fs.append(_round(w.snow_in_hr, 2))
        risk.append(fr)
        wind.append(fw)
        rain.append(fra)
        snow.append(fs)

    resp = HeatmapResponse(
        grid={"rows": rows, "cols": cols, "lats": lats, "lons": lons},
        times=times,
        hours=HEATMAP_HOURS,
        variables={"risk": risk, "wind_mph": wind, "rain_in_hr": rain, "snow_in_hr": snow},
        source="open-meteo",
        generated_at=datetime.now(UTC).replace(microsecond=0),
    )
    with _lock:
        _cache[key] = resp
    return resp


def to_json(resp: HeatmapResponse) -> str:
    """Compact JSON with UTC 'Z' times (keeps the payload small, NFR-3)."""
    data = resp.model_dump()
    data["times"] = [iso_z(t) for t in resp.times]
    data["generated_at"] = iso_z(resp.generated_at)
    return json.dumps(data, separators=(",", ":"))
