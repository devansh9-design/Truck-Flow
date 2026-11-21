# Weather-Aware Truck Routing

Plan a truck trip and see which route is safest in the weather the truck will actually drive into.

Enter an origin, destination, departure time and load. The app finds three truck routes, places checkpoints along each one, and looks up the forecast for the hour the truck reaches each checkpoint. It rates every checkpoint Low, Moderate, High, Severe or No Travel, then ranks the routes, safest first. A heatmap with a 0–48 h slider shows how the weather moves along the corridor after departure.

**Live app:** _not deployed yet; see [Deploy](#deploy)._

## Features

**Core**

- **Three truck routes:** HERE Routing v8 in truck mode, using the gross weight (load + tare).
- **Checkpoints with ETAs:** every 10, 25 or 50 mi. Each one gets the forecast for its arrival hour from Open-Meteo.
- **Risk rules:** wind, rain and snow thresholds, plus a load rule: strong wind combined with a heavy load raises the level (spec §5).
- **Ranking:** routes are ordered by No Travel miles, then Severe miles, High miles, average risk and duration. The recommendation states which of these decided it.
- **Map:** shows every route, with the selected one coloured by risk. Clicking a checkpoint shows its weather and the reason for its rating.
- **Corridor heatmap:** a slider covers 0–48 h after departure. All 49 frames load up front, so moving the slider makes no network calls.

**Extras** (informational only; none of them changes a risk score or the ranking)

- **Place suggestions while typing,** with an optional country filter for each field.
- **Metric/imperial toggle** for every number on screen, including the trip form.
- **NWS weather alerts** along US routes.
- **Saved trips,** kept in the browser, or on the server when signed in.
- **Optional accounts:** name and country, with saved trips stored per user.
- **Mobile layout** with a bottom sheet and a touch-friendly slider.
- **Driving mode:**
  - follows the phone's GPS;
  - re-checks the road ahead every 15 min, or sooner after 25 mi driven;
  - warns on screen and by voice when weather makes another route safer.

## Architecture

```
React (Vite)  ──►  Django + DRF  /api/*  ──►  Flask risk engine  /v1/*  (internal, token)
                    │  HERE geocoding, routing, autocomplete       │  risk rules, Open-Meteo,
                    │  checkpoints, ETAs, scoring, ranking         │  heatmap frames, NWS alerts
                    │  accounts + saved trips (Postgres/SQLite)
```

| Folder | What it is |
| --- | --- |
| `frontend/` | React 19, TypeScript, Vite, MapLibre, deck.gl, TanStack Query, Zustand, Tailwind |
| `backend/` | Django 6 + DRF: the only public API, plus the `accounts` app |
| `risk_engine/` | Flask: internal service called only by Django (requires the `X-Internal-Token` header) |
| `shared/` | Pydantic schemas used by both Python services |
| `docs/` | Specification, architecture, API contracts, testing strategy, deployment |

Data sent between services always uses imperial units (mi, mph, in/hr, lb) and UTC ISO 8601 times. The metric toggle only changes what is shown on screen.

## Run locally

You need Python 3.14, Node 24 and a [HERE](https://platform.here.com/) API key with access to Routing v8, Geocoding & Search v7 and Autocomplete.

### 1. Install

```bash
# from the repo root: one virtual environment for both Python services
python -m venv .venv
.venv\Scripts\activate            # Windows (macOS/Linux: source .venv/bin/activate)

cd backend && pip install -r requirements-dev.txt && cd ..
cd risk_engine && pip install -r requirements-dev.txt && cd ..
cd frontend && npm ci && cd ..
```

The requirements install `shared/` in editable mode, so both services pick up schema changes immediately.

### 2. Configure

Copy each example file to the name shown, then fill it in:

| Copy | To | Set |
| --- | --- | --- |
| `backend/.env.example` | `backend/.env` | `HERE_API_KEY`, and `RISK_ENGINE_TOKEN` (any long random string) |
| `risk_engine/.env.example` | `risk_engine/.env` | the **same** `RISK_ENGINE_TOKEN`, and `NWS_USER_AGENT` (app name + a contact) |
| `frontend/.env.example` | `frontend/.env.local` | nothing; the defaults point at the local backend |

Keep `.env` files out of git; only the `.env.example` files are committed. If the two tokens differ, analysis fails with 401 from the risk engine.

Other backend settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DJANGO_DEBUG` | `false` | Set to `true` locally to use SQLite and a development secret key |
| `DATABASE_URL` | unset | Postgres URL; required when `DJANGO_DEBUG` is false |
| `DJANGO_SECRET_KEY` | none | Required when `DJANGO_DEBUG` is false |
| `TRUCK_TARE_LB` | `35000` | Added to the load to get the gross weight sent to the router |
| `NUM_PROXIES` | | Proxy hops in front of Django, used to find the client IP for rate limits |

### 3. Create the database

```bash
cd backend && python manage.py migrate && cd ..
```

Locally this creates `backend/db.sqlite3` (git-ignored). Optionally, run `python manage.py createsuperuser` to get a staff account that can see `/api/admin/stats`.

### 4. Start the three services

Use three terminals, all started from the repo root with the virtual environment active:

```bash
python risk_engine/app.py                               # risk engine on :5001
python backend/manage.py runserver 127.0.0.1:8000       # API on :8000
npm --prefix frontend run dev                           # app on http://localhost:5173
```

Open http://localhost:5173 and try **Denver, CO → Salt Lake City, UT** with a 40,000 lb load. The status pill in the header reads "Services ready" once the API and risk engine are both reachable.

## Tests and checks

```bash
cd shared && pytest -q
cd risk_engine && pytest -q
cd backend && pytest -q          # includes full-stack scenarios S1–S10 against a real Flask app
ruff check .                     # from the repo root

cd frontend
npm test                         # Vitest
npm run e2e                      # Playwright + axe (API and map mocked; first run: npx playwright install chromium)
npm run lint && npm run typecheck && npm run format:check
```

None of these call HERE, Open-Meteo or NWS: tests replay recorded provider responses (`backend/tests/fixtures/`, `risk_engine/tests/fixtures/`, `shared/fixtures/`). CI (`.github/workflows/ci.yml`) runs all of them on every push. Live checks against the real providers are in `backend/scripts/core_check_chunk*.py` and `backend/scripts/perf_check.py`, and need the API key.

## Deploy

- **Backend:** the API, the risk engine and Postgres deploy to Render from [`render.yaml`](render.yaml). Django runs its migrations on start.
- **Frontend:** deploys to Vercel with the project root set to `frontend`.

Follow [docs/deployment.md](docs/deployment.md) step by step: secrets, CORS, the staff account, checking `NUM_PROXIES`, and the live core checks.

Free-tier notes:

- Render services sleep after 15 minutes idle; the first request wakes them.
- Render's free Postgres expires after a limited time.

## API

All public endpoints are under `/api/`. The main ones:

| Endpoint | Purpose |
| --- | --- |
| `POST /api/analyze` | Ranked routes with checkpoints and risk |
| `GET /api/heatmap` | 49 hourly heatmap frames for the corridor |
| `POST /api/alerts` | NWS alerts along the route |
| `GET /api/places/suggest`, `/lookup` | Place suggestions while typing |
| `/api/auth/*`, `/api/trips` | Accounts and saved trips |
| `GET /api/health` | Health of the API and the risk engine |

Full request and response shapes, error codes and rate limits are in [docs/API contracts.md](docs/API%20contracts.md). A running backend also serves an OpenAPI schema at `/api/schema`, with Swagger UI at `/api/docs`.

## Documentation

- [Specification](docs/projects%20specification.md): requirements, risk rules, interpretation decisions
- [Architecture](docs/architecture.md): design, data flow, ADRs
- [Testing strategy](docs/Testing%20strategy.md): what is tested and why
- [Tech stack](docs/tech%20stack.md) and [performance results](docs/performance-results.md)

## Data sources

- Routing, geocoding and place suggestions: [HERE](https://www.here.com/)
- Forecasts: [Open-Meteo](https://open-meteo.com/)
- US weather alerts: [National Weather Service](https://www.weather.gov/documentation/services-web-api)
- Map tiles: [OpenFreeMap](https://openfreemap.org/), © OpenStreetMap contributors
