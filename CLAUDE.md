# CLAUDE.md — Weather-Aware Truck Routing System

Context for Claude Code. Planning is finished in a previous chat; this repo is where we build. Read the docs in `docs/` before writing code. They are the source of truth.

## Docs (read in this order)

1. `docs/projects specification.md`: mandatory core, rules, interpretation decisions (§0, §5, §6)
2. `docs/architecture.md`: Architecture B + C heatmap technique, repo layout, flows
3. `docs/API contracts.md`: every endpoint and payload
4. `docs/feature roadmap.md`: the four build chunks + upgrades
5. `docs/Testing strategy.md`: required tests, scenarios S1–S10
6. `docs/tech stack.md`: libraries and providers
7. `docs/AI development tools.md`: how we work together

## Mandatory core (fixed; never change, cut or reorder)

- **CORE-1** Three route options (HERE Routing v8 truck mode; up to 5 alternatives → dedupe → keep 3; via-point fallback)
- **CORE-2** Time-aware checkpoint weather: checkpoints every 10/25/50 mi, weather at each checkpoint's ETA hour
- **CORE-3** Risk + load rules exactly as in spec §5 (half-open intervals; rain 1.00 and snow 3.00 stay Severe)
- **CORE-4** Ranking key: `(no_travel_mi, severe_mi, high_mi, avg_risk, duration_s)`. No Travel and Severe miles are **separate**; the No Travel key is our agreed safety rule (D4), the other four are the spec's, in order.
- **CORE-5** Map: all routes, checkpoints, risk levels, ETAs, route summaries
- **CORE-6** Heatmap along the corridor with a 0–48 h slider (hour 0 = departure); all 49 frames preloaded, no network calls while scrubbing

Non-core features (alerts, unit toggle, saved trips, mobile) must never change a core result.

## Architecture

- `frontend/`: React + Vite + TypeScript, MapLibre (react-map-gl), deck.gl HeatmapLayer, TanStack Query, Zustand, Tailwind, Radix
- `backend/`: Django + DRF, the **only public API** (`/api/*`): geocode, routing, sampling, ETA, scoring, ranking
- `risk_engine/`: Flask, **internal** (`/v1/*`, `X-Internal-Token`): rules, Open-Meteo weather, heatmap frames, NWS alerts
- `shared/`: Pydantic schemas used by both Python services
- No Redis, Postgres, Celery or Docker. In-memory caches only.
- Wire units are always imperial (mi, mph, in/hr, lb); times are UTC ISO 8601.
- Router gets gross weight = load + `TRUCK_TARE_LB` (default 35,000); the rules use the load as entered.

## Working rules

- Build **one chunk at a time** (see roadmap). Finish each with its core check before starting the next.
- Write tests alongside logic. Rule tests cover every threshold edge.
- Never invent third-party API fields; confirm against provider docs or a recorded response.
- Secrets only in `.env` (git-ignored); commit `.env.example` only. Never print or log API keys.
- The HERE API key will be provided by the developer only when routing work needs it.
- Small, focused commits; no unrelated refactors.

## Status

- Planning docs: done
- Chunk 1 done: scaffolding, shared schemas, geocoding, three truck routes, checkpoints + ETAs. Debug endpoint `POST /api/debug/routes` (DEBUG only); core check `backend/scripts/core_check_chunk1.py`.
- Chunk 1 core check passed live (Denver → SLC: 3 distinct routes, 21–23 checkpoints each, ETAs ok). Real HERE fixtures recorded in `backend/tests/fixtures/`.
- HERE `spans=length,duration` returns ONE span per section; we request `spans=length,duration,speedLimit` so spans split at speed-limit changes (per-zone durations for D7 ETAs).
- Chunk 2 done: `risk_engine/rules.py` (CORE-3), Open-Meteo client `risk_engine/weather.py` (multi-location list response, `{"error": true, "reason"}` bodies, explicit unit conversion), token-protected `/v1/evaluate`, scoring + ranking (`backend/scoring/`), `POST /api/analyze`. Core check `backend/scripts/core_check_chunk2.py` passed live (Denver → SLC, 3 ranked routes, ~4 s).
- `decided_by` also returns `only_route` when a single route exists (documented in API contracts).
- Chunks 1 and 2 are committed.
- Chunk 3 done: trip form (with trip time-zone picker: departure is read in it and every time is shown in it), MapLibre map (all routes; selected route drawn as risk-coloured segments between checkpoints; recommended route blue-dashed when not selected; alternate checkpoints as clickable GPU circles), checkpoint popups (ETA, forecast hour, weather, per-factor levels, reason), route cards, checkpoint list, health pill, loading and error states. Vitest suite in `frontend/tests/` (`npm test`). Core check passed live in the browser (Denver → SLC: 3 routes, all checkpoints with risk + ETA, cards with the recommended route marked).
- MapLibre 6 needs its worker URL set explicitly under Vite: see `frontend/src/map/maplibre.ts`.
- `risk_engine/.env` must contain `RISK_ENGINE_TOKEN` matching `backend/.env`, or `/v1/evaluate` returns 401.
- Local run configs: `.claude/launch.json` (risk-engine :5001, backend :8000, frontend :5173). `frontend/.env.local` copied from `.env.example`.
- **Next: Chunk 4** (heatmap frames, deck.gl heatmap + 0–48 h slider, deployment).
- One venv at repo root (`.venv`); run backend tests from `backend/`, risk engine tests from `risk_engine/`.
