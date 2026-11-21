# Tech Stack — Weather-Aware Truck Routing System

Fixed by the brief: **React** (frontend) and **Django** (backend). Fixed by our choice: **Flask** as the internal risk-engine service (Architecture B).
Every choice below serves the mandatory core (`projects specification.md` §0): CORE-1 three routes · CORE-2 time-aware checkpoint weather · CORE-3 risk/load rules · CORE-4 recommendation priorities · CORE-5 map visualization · CORE-6 0–48 h heatmap slider.

Versions: latest stable release of each tool at project setup, pinned in `package.json` / `requirements.txt`. Minimum runtimes: **Node 20+**, **Python 3.11+**.

---

## 1. Frontend

| Concern | Choice | Why |
|---|---|---|
| Framework | **React** | Required by the spec |
| Build tool | **Vite** | Fast dev server and builds; no SSR needed |
| Language | **TypeScript** | Catches API-shape mistakes at compile time |
| Map | **MapLibre GL JS** via **react-map-gl** | CORE-5. WebGL rendering; draws 3 routes and many markers smoothly; open source, no vendor lock-in |
| Base map tiles | OpenFreeMap or MapTiler (free tier) style URL | Vector basemap for MapLibre; set by `VITE_MAP_STYLE_URL` |
| Heatmap | **deck.gl `BitmapLayer`** (MapboxOverlay on MapLibre) | CORE-6. Each preloaded frame is a tiny image (one pixel per grid cell) smoothed by GPU filtering; the slider swaps images instantly. Chosen over `HeatmapLayer`, which draws point density and rendered the corridor grid as dots (architecture ADR 010). |
| Server state | **TanStack Query** | Request caching, loading and error states |
| UI state | **Zustand** | Selected route, slider hour, units, saved trips; tiny and simple |
| Styling | **Tailwind CSS** | Fast, consistent, responsive layouts for the mobile requirement |
| Accessible primitives | **Radix UI** (Slider, Dialog, Toggle) | Keyboard and ARIA support out of the box |
| Dates | **date-fns** + **date-fns-tz** | ETA formatting in local time |
| Geo helpers | **Turf.js** (selected modules) | Bounding boxes and distances in the browser |
| Unit tests | **Vitest** + **React Testing Library** | Fast, Vite-native |
| E2E | **Playwright** + **@axe-core/playwright** | Browser tests with mocked API; accessibility scan |
| Lint/format | **ESLint** + **Prettier** | Code quality score |

## 2. Django service (public API / orchestrator)

| Concern | Choice | Why |
|---|---|---|
| Framework | **Django** | Required by the spec |
| API layer | **Django REST Framework** | Serializers validate input; clear views |
| API docs | **drf-spectacular** | Auto-generated OpenAPI docs at `/api/docs` |
| HTTP client | **httpx** | Timeouts, retries, connection pooling |
| Geometry | **Shapely** + **pyproj** | Accurate cutting of the route every N miles |
| HERE polyline | **flexpolyline** | Decodes HERE's flexible polyline format |
| Schemas | **Pydantic** (shared package) | Same models as Flask; contract safety |
| CORS | **django-cors-headers** | Allows only the frontend origin |
| Cache | Django **LocMemCache** | Geocode caching and rate-limit counters without Redis |
| Database | **PostgreSQL** (Render) via **dj-database-url** + **psycopg 3**; SQLite locally | Accounts and saved trips (ADR 012) |
| Auth | Django auth (custom email user) + DRF bearer-token class + DRF throttling | Optional sign-in, per-user authorization, rate limits (ADR 013, 014) |
| Server | **gunicorn** | Production WSGI server on Render |
| Config | **python-dotenv** / env vars | Secrets outside the code |

## 3. Flask service (internal risk engine)

| Concern | Choice | Why |
|---|---|---|
| Framework | **Flask** | Fixed technology; ideal for a small stateless service |
| Validation | **Pydantic** (shared package) | Strict request/response models |
| HTTP client | **httpx** | Batched Open-Meteo and NWS calls with timeouts |
| Cache | **cachetools** `TTLCache` | Forecast, heatmap and alert caching in memory |
| Server | **gunicorn** | Production WSGI server on Render |

## 4. Third-party APIs

| Need | Provider | Core | Why |
|---|---|---|---|
| Routing | **HERE Routing v8** (`transportMode=truck`) | CORE-1 | Truck-aware, takes gross weight, returns alternatives on long routes (we keep 3), free tier covers development |
| Geocoding | **HERE Geocoding & Search** | support | Same key as routing |
| Weather | **Open-Meteo** forecast API | CORE-2, CORE-6 | Free, keyless, hourly data up to 16 days, mph and inch units, multiple coordinates per request. In production the calls go through a Vercel Function relay (ADR 015) |
| Alerts | **NWS api.weather.gov** | non-core | Free official US alerts; informational only |

## 5. Testing & quality

| Tool | Use |
|---|---|
| **pytest** + **pytest-django** | Backend and risk-engine tests |
| **hypothesis** | Property tests on risk rules |
| **respx** | Mocks httpx calls in contract and client tests |
| **freezegun** | Frozen time for ETA tests |
| **pytest-cov** | Coverage for the logic modules |
| **ruff** | Lint + formatting for Python |
| **mypy** (light) | Type checks on core modules |
| **GitHub Actions** | CI: lint, type check, tests on every push |

## 6. Hosting & delivery

| Part | Platform | Notes |
|---|---|---|
| Frontend | **Vercel** | Static Vite build; `VITE_API_BASE_URL` points to Django |
| Django | **Render** web service | gunicorn; free tier sleeps when idle |
| Flask | **Render** web service | Private by token; free tier sleeps when idle |
| Source | **GitHub** | Monorepo with `frontend/`, `backend/`, `risk_engine/`, `shared/` |
| Walkthrough | **Loom** | 5–10 min video |

## 7. Deliberately not used

| Tool | Reason |
|---|---|
| Redis | In-memory caches are enough for this scope; one less service to deploy |
| Celery | Analysis fits within the latency target without background jobs |
| Docker | Not needed for Vercel/Render; services run directly |
| Next.js | No server-side rendering needed |
| Leaflet | Canvas heatmaps stutter when scrubbing 49 frames |
| OpenRouteService (public API) | Alternative routes limited to short trips |
| Google Maps / Mapbox routing | No truck profile |
