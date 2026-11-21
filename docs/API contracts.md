# API Contracts — Weather-Aware Truck Routing System

Two APIs:

- **Public API (Django)** — called by the React app. Base path `/api`.
- **Internal API (Flask risk engine)** — called only by Django. Base path `/v1`. Requires header `X-Internal-Token`.

Conventions for both:

| Item | Rule |
|---|---|
| Format | JSON, UTF-8 |
| Units | **Always imperial**: miles, mph, inches/hour, pounds. Durations in seconds. |
| Time | ISO 8601 with offset; the server responds in UTC (`Z`) |
| Coordinates | `{ "lat": number, "lon": number }`; route geometry is GeoJSON `[lon, lat]` |
| Risk level enum | `LOW` · `MODERATE` · `HIGH` · `SEVERE` · `NO_TRAVEL` |
| Risk score | LOW 1 · MODERATE 2 · HIGH 3 · SEVERE 4 · NO_TRAVEL 5 |
| IDs | Strings |

### Error shape (both APIs)

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Load weight must be between 1 and 100,000 lb.",
    "details": { "field": "load_weight_lb" }
  }
}
```

| HTTP | `code` | When |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Bad or missing input |
| 401 | `UNAUTHORIZED` | Internal token missing or wrong (Flask only) |
| 401 | `NOT_AUTHENTICATED` | A signed-in-only endpoint was called without `Authorization: Bearer …` |
| 401 | `TOKEN_INVALID` | The bearer token is unknown, expired or revoked (the app then signs out locally and retries as a guest) |
| 401 | `INVALID_CREDENTIALS` | Wrong email or password (same message for both); wrong password when deleting an account |
| 403 | `FORBIDDEN` | Signed in but not allowed (e.g. `/api/admin/stats` without staff) |
| 429 | `RATE_LIMITED` | Too many requests; `details.retry_after_s` and a `Retry-After` header say when to retry |
| 404 | `PLACE_NOT_FOUND` | Origin or destination can't be geocoded |
| 422 | `NO_ROUTE` | Router reports no truck route (HERE `noRouteFound`); never used for router errors |
| 422 | `BEYOND_FORECAST_HORIZON` | A checkpoint ETA is later than the last available forecast hour |
| 502 | `UPSTREAM_ERROR` | HERE, Open-Meteo, NWS or Flask returned an error, rate-limited us (429, not retried), rejected our request, or sent malformed or incomplete data (e.g. a null value at a needed forecast hour) |
| 504 | `UPSTREAM_TIMEOUT` | An upstream call timed out after retry |
| 500 | `INTERNAL_ERROR` | Unexpected server error (details logged, not returned) |

---

## Part A — Public API (Django)

### A1. `GET /api/health`

Wakes Django and, through it, Flask.

```json
{ "status": "ok", "risk_engine": "ok", "time": "2026-11-20T04:00:00Z" }
```

### A2. `GET /api/geocode?q=<text>`

| Param | Required | Notes |
|---|---|---|
| `q` | yes | 2–200 characters |

```json
{
  "results": [
    { "label": "Denver, CO, United States", "lat": 39.7392, "lon": -104.9903 }
  ]
}
```

At most 5 results. Empty list → the form shows "No match".

### A3. `POST /api/analyze`

**Request**

```json
{
  "origin": "Denver, CO",
  "destination": "Salt Lake City, UT",
  "departure_time": "2026-11-21T06:00:00-07:00",
  "load_weight_lb": 42000,
  "interval_mi": 25
}
```

| Field | Type | Rules |
|---|---|---|
| `origin`, `destination` | string **or** `{label, lat, lon}` | String is geocoded server-side; must differ |
| `departure_time` | ISO 8601 with offset | ≥ now − 1 h |
| `load_weight_lb` | number | 1–100,000 (used as entered by the load rules) |
| `interval_mi` | integer | One of 10, 25, 50 |

**Response 200**

```json
{
  "trip": {
    "origin": { "label": "Denver, CO, United States", "lat": 39.7392, "lon": -104.9903 },
    "destination": { "label": "Salt Lake City, UT, United States", "lat": 40.7608, "lon": -111.8910 },
    "departure_time": "2026-11-21T13:00:00Z",
    "load_weight_lb": 42000,
    "interval_mi": 25
  },
  "routes": [
    {
      "id": "r0",
      "rank": 1,
      "recommended": true,
      "label": "Route A via I-80",
      "distance_mi": 521.4,
      "duration_s": 30240,
      "arrival_time": "2026-11-21T21:24:00Z",
      "geometry": { "type": "LineString", "coordinates": [[-104.9903, 39.7392], [-105.01, 39.75]] },
      "checkpoints": [
        {
          "id": "r0-c0",
          "index": 0,
          "mile": 0.0,
          "lat": 39.7392,
          "lon": -104.9903,
          "eta": "2026-11-21T13:00:00Z",
          "forecast_hour": "2026-11-21T13:00:00Z",
          "weather": { "wind_mph": 18.2, "rain_in_hr": 0.0, "snow_in_hr": 0.12 },
          "risk": {
            "level": "LOW",
            "score": 1,
            "factors": { "wind": "LOW", "rain": "LOW", "snow": "LOW", "load_override": null },
            "reason": "All conditions below Moderate thresholds."
          }
        }
      ],
      "summary": {
        "miles_by_level": { "LOW": 410.2, "MODERATE": 80.0, "HIGH": 31.2, "SEVERE": 0.0, "NO_TRAVEL": 0.0 },
        "severe_mi": 0.0,
        "high_mi": 31.2,
        "no_travel_mi": 0.0,
        "has_no_travel": false,
        "avg_risk": 1.3,
        "max_level": "HIGH"
      },
      "warnings": []
    }
  ],
  "recommendation": {
    "route_id": "r0",
    "decided_by": "high_mi",
    "reason": "Tied on Severe miles (0.0); fewest High miles (31.2 vs 58.0)."
  },
  "corridor": { "bbox": [-112.4, 39.3, -104.5, 41.4] },
  "notes": ["Router returned 3 routes."]
}
```

Rules guaranteed by this endpoint (mandatory core):

- **CORE-1:** `routes` has 3 entries. Fewer only when HERE returned no third distinct route from its alternatives or up to 6 via-point detours; `notes` records the attempts and outcome and never claims that no road exists.
- **CORE-2:** checkpoints are spaced `interval_mi` apart along the route; checkpoint 0 is the origin and the last is the destination. Each checkpoint's `weather` is the forecast for its `forecast_hour` (its ETA rounded to the hour).
- **CORE-3:** `risk` follows the thresholds and load rules in `projects specification.md` §5 exactly. `factors.load_override` is `null`, `"SEVERE"` or `"NO_TRAVEL"`.
- **CORE-4:** `routes` is sorted by `rank` using `no_travel_mi` (our safety key, D4) → `severe_mi` → `high_mi` → `avg_risk` → `duration_s`. `severe_mi` counts Severe miles only; `no_travel_mi` counts No Travel miles only (D3). Rank 1 has `recommended: true`; `decided_by` names the key that separated it from rank 2 (`no_travel_mi`, `severe_mi`, `high_mi`, `avg_risk`, `duration_s` or `tie`; `only_route` when a single route exists).
- `warnings` contains `"NO_TRAVEL_CONDITIONS"` when a route has any No Travel miles, including the recommended route when every option has them.

### A4. `GET /api/heatmap`

| Param | Required | Notes |
|---|---|---|
| `bbox` | yes | `minLon,minLat,maxLon,maxLat` (from `corridor.bbox`) |
| `start` | yes | The trip's departure time, rounded down to the hour = slider hour 0 (CORE-6) |
| `load_weight_lb` | yes | Needed for load-adjusted risk |

**Response 200** (frames are flat arrays, row-major, `rows × cols` values per hour)

```json
{
  "grid": { "rows": 14, "cols": 14, "lats": [39.3, 39.45], "lons": [-112.4, -111.83] },
  "times": ["2026-11-21T13:00:00Z", "2026-11-21T14:00:00Z"],
  "hours": 49,
  "variables": {
    "risk":       [[1, 1, 2]],
    "wind_mph":   [[12.1, 14.0, 26.3]],
    "rain_in_hr": [[0.0, 0.02, 0.11]],
    "snow_in_hr": [[0.0, 0.0, 0.4]]
  },
  "source": "open-meteo",
  "generated_at": "2026-11-20T04:00:05Z"
}
```

`variables.<name>[h]` holds hour `h` (0–48): exactly 49 frames, always (CORE-6). The `risk` frames use the same rules as checkpoints (CORE-3), as the 1–5 score. Each frame has `rows × cols` values, row-major from the south-west cell; `grid.lats` / `grid.lons` are cell-centre coordinates (south → north, west → east) over the corridor bbox buffered by 25 mi, with at most 256 cells. A value is `null` where the forecast has no usable data for that cell and hour (e.g. past the forecast end); it is never replaced by zero or Low. Values are rounded (wind 0.1, rain/snow 0.01) to keep the payload under 1.5 MB (Denver → Salt Lake City: ~200 KB).

Errors: 400 `VALIDATION_ERROR` (bad `bbox`, a bbox wider than 60° or taller than 30°, `start` without offset or outside now − 2 h … forecast horizon, bad load); 502/504 when the weather service fails.

### A5. `POST /api/alerts`

The frontend sends points sampled along the analysed routes (about every 50 mi, max 100 points).

```json
// request
{ "points": [ { "lat": 39.74, "lon": -104.99 }, { "lat": 40.76, "lon": -111.89 } ] }

// response
{
  "alerts": [
    {
      "id": "urn:oid:2.49.0.1.840.0.abc",
      "event": "Winter Storm Warning",
      "severity": "Severe",
      "headline": "Winter Storm Warning until 6 PM MST",
      "areas": "Summit County",
      "onset": "2026-11-21T15:00:00Z",
      "ends": "2026-11-22T01:00:00Z",
      "point_index": 4
    }
  ],
  "coverage": "US"
}
```

Outside the US, `alerts` is empty and `coverage` is `"unsupported_region"`. Alerts are non-core and informational: they never change a risk level or the ranking.

Details (confirmed against recorded NWS responses in `risk_engine/tests/fixtures/nws_*.json`):

- One NWS call per distinct point (rounded to 2 decimals, ~1 km), cached 10 minutes. NWS answers 400 `"out of bounds"` for points it does not cover (e.g. Canada); those points are skipped. `coverage` is `"unsupported_region"` only when **every** point is out of bounds; a US ↔ Canada trip gets `"US"` with alerts for its US points.
- Alerts are deduplicated by NWS `id`; `point_index` is the first request point where an alert was found (the map badge sits there). Order: most severe first (`Extreme`, `Severe`, `Moderate`, `Minor`, `Unknown`), then by `point_index`.
- `onset` falls back to NWS `effective`; `ends` is `null` when NWS gives no end time ("until further notice"). Times are UTC. `headline` may be `null`.
- Errors: 400 `VALIDATION_ERROR` (no points, more than 100, bad lat/lon); 502 when NWS fails or rejects the request (429 is not retried); 504 on timeout after one retry. The frontend shows "alerts unavailable" and leaves the results untouched.

### A6. Accounts — `/api/auth/*` (optional sign-in, D15)

Every other endpoint works for guests. Send `Authorization: Bearer <token>` to act as a user.

| Method + path | Body | Success |
|---|---|---|
| `POST /api/auth/signup` | `{name, email, password, country}` (ISO 3166-1 alpha-2) | 201 session |
| `POST /api/auth/login` | `{email, password}` | 200 session |
| `POST /api/auth/logout` | none (signed in) | 204; this token is revoked |
| `GET /api/auth/me` | none (signed in) | `{user}` |
| `PATCH /api/auth/me` | `{name?, country?}` | `{user}` (email and staff flag cannot be changed here) |
| `DELETE /api/auth/me` | `{password}` | 204; deletes the account, its tokens and trips |
| `POST /api/auth/password` | `{current_password, new_password}` | 204; other devices are signed out |

```json
// session
{ "token": "<43 random characters>", "expires_at": "2026-12-20T12:00:00Z",
  "user": { "id": 1, "email": "ana@example.com", "name": "Ana Ruiz", "country": "ES",
            "country_name": "Spain", "continent": "Europe", "is_staff": false,
            "date_joined": "2026-11-20T12:00:00Z" } }
```

Emails are case-insensitive. Passwords: at least 8 characters, not common, not all digits, not similar to the email or name (400 `VALIDATION_ERROR`, `details.field = "password"`). Tokens expire 30 days after last use.

### A7. Saved trips — `/api/trips` (signed in)

| Method + path | Body | Success |
|---|---|---|
| `GET /api/trips` | none | `{trips: [trip…]}`, newest first, max 20 |
| `POST /api/trips` | trip without `id` / `saved_at` | 201 `{trip}`; an identical trip is replaced; the oldest beyond 20 are dropped |
| `POST /api/trips/import` | `{trips: [...]}` (≤ 20, newest first) | `{trips}`; moves trips saved in the browser into the account |
| `DELETE /api/trips/<id>` | none | 204; 404 if the trip is not the caller's |

A trip has the same shape as the browser's saved trip: `{id, saved_at, origin: {label, lat, lon}, destination, departure_time, load_weight_lb, interval_mi, time_zone, summary: {recommended_label, max_level, distance_mi}}`. Places must be resolved (`{label, lat, lon}`), never free text.

### A8. `GET /api/countries`

`{continents: [7 names], countries: [{code, name, continent}]}`: all 249 ISO 3166-1 entries (`backend/accounts/countries.py`).

### A9. `GET /api/admin/stats` (staff only)

`{users_total, signups_last_7_days, saved_trips_total, by_continent: {name: count}, by_country: [{code, name, users}]}`. 401 for guests, 403 for non-staff. Create a staff account with `python manage.py createsuperuser`.

### Rate limits (D16)

| Endpoints | Guest (per IP) | Signed in (per account) |
|---|---|---|
| `POST /api/analyze` | 30 / hour | 120 / hour |
| `GET /api/heatmap`, `POST /api/alerts` | 60 / hour | 240 / hour |
| `GET /api/geocode` | 60 / min | 120 / min |
| `/api/auth/signup`, `login`, `password` | 10 / min | 10 / min |
| `/api/trips*` | n/a | 60 / min |

---

## Part B — Internal API (Flask risk engine)

All endpoints except `/health` require `X-Internal-Token: <RISK_ENGINE_TOKEN>`.

### B1. `GET /health`

```json
{ "status": "ok" }
```

### B2. `POST /v1/evaluate`

**Request**

```json
{
  "load_weight_lb": 42000,
  "checkpoints": [
    { "id": "r0-c0", "lat": 39.7392, "lon": -104.9903, "eta": "2026-11-21T13:00:00Z" }
  ]
}
```

Up to 1,000 checkpoints per call. Flask deduplicates by (lat/lon rounded to 0.1°, forecast hour) before calling Open-Meteo.

**Response 200**

```json
{
  "results": [
    {
      "id": "r0-c0",
      "forecast_hour": "2026-11-21T13:00:00Z",
      "weather": { "wind_mph": 18.2, "rain_in_hr": 0.0, "snow_in_hr": 0.12 },
      "risk": {
        "level": "LOW",
        "score": 1,
        "factors": { "wind": "LOW", "rain": "LOW", "snow": "LOW", "load_override": null },
        "reason": "All conditions below Moderate thresholds."
      }
    }
  ],
  "meta": { "source": "open-meteo", "cache_hits": 12, "fetched": 30 }
}
```

Guarantee: `results` contains exactly one entry per input `id`, in the same order.

### B3. `POST /v1/heatmap`

```json
{
  "bbox": [-112.4, 39.3, -104.5, 41.4],
  "start": "2026-11-21T13:00:00Z",
  "hours": 49,
  "load_weight_lb": 42000,
  "max_cells": 256
}
```

Response: identical to **A4** (Django passes it through).

### B4. `POST /v1/alerts`

Request and response identical to **A5**.

---

## Part C — Shared schema (Pydantic, `shared/truckrisk_schemas`)

```python
class RiskLevel(str, Enum):
    LOW = "LOW"; MODERATE = "MODERATE"; HIGH = "HIGH"; SEVERE = "SEVERE"; NO_TRAVEL = "NO_TRAVEL"

class Weather(BaseModel):
    wind_mph: float; rain_in_hr: float; snow_in_hr: float

class RiskFactors(BaseModel):
    wind: RiskLevel; rain: RiskLevel; snow: RiskLevel
    load_override: Literal["SEVERE", "NO_TRAVEL"] | None

class Risk(BaseModel):
    level: RiskLevel; score: int; factors: RiskFactors; reason: str

class CheckpointIn(BaseModel):
    id: str; lat: float; lon: float; eta: datetime

class EvaluateRequest(BaseModel):
    load_weight_lb: float; checkpoints: list[CheckpointIn]

class CheckpointResult(BaseModel):
    id: str; forecast_hour: datetime; weather: Weather; risk: Risk

class EvaluateResponse(BaseModel):
    results: list[CheckpointResult]; meta: dict
```

Contract tests (see `Testing strategy.md`) validate both services against these models using shared JSON fixtures.

---

## Part D — Third-party APIs used

| Provider | Endpoint | Used for | Key |
|---|---|---|---|
| HERE | Geocoding & Search v7 (`/geocode`) | Place → coordinates | `HERE_API_KEY` |
| HERE | Routing v8 (`/routes`, `transportMode=truck`, `alternatives=5`, gross weight = load + `TRUCK_TARE_LB`, `return=polyline,summary`, `spans=length,duration,speedLimit`; speedLimit makes HERE split spans at each speed-limit change, which gives per-zone durations for ETAs) | Truck routes (CORE-1) | `HERE_API_KEY` |
| Open-Meteo | `/v1/forecast` with `hourly=wind_speed_10m,rain,showers,snowfall`, `wind_speed_unit=mph`, `precipitation_unit=inch`, `forecast_days=16`, multiple coordinates per call | Forecasts (CORE-2, CORE-6) | none |
| NWS | `api.weather.gov/alerts/active?point=lat,lon` (`User-Agent` header required) | Alerts (US) | none |

Exact request parameters are confirmed against each provider's current documentation, using a recorded real response, before each client is finalised.
