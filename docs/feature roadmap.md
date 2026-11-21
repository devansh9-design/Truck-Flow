# Feature Roadmap — Weather-Aware Truck Routing System

**Target:** ship in about **24 hours**, including the time you spend running, testing, deploying and recording.
**Roles:** Claude writes all code and tests. You run the code, report results, hold the API keys, deploy and record the Loom.
**Rule:** one chunk at a time → build → check → confirm → next.

---

## Mandatory core (fixed)

| ID | Core requirement | Chunk |
|---|---|---|
| CORE-1 | Three route options | 1 |
| CORE-2 | Time-aware checkpoint weather (10/25/50 mi, weather at each ETA) | 1 (checkpoints + ETA), 2 (weather) |
| CORE-3 | Specified risk and load rules | 2 |
| CORE-4 | Specified recommendation priorities: Severe mi → High mi → avg risk → time (preceded by our No Travel miles safety key) | 2 |
| CORE-5 | Map visualization: routes, checkpoints, risk levels, ETAs, route summaries | 3 |
| CORE-6 | Weather heatmap with 0–48 h forecast slider | 4 |

Core work is never cut, delayed or simplified in a way that changes its results. Everything else is **non-core** and is built only around the core. See `projects specification.md` §0 and §6 for the exact rules and interpretations.

---

## First working model: four chunks (≈ 14 h)

Each chunk ends with a **core check**: something you run that proves the core requirements it covers.

### Chunk 1 · Backend skeleton and three truck routes (≈ 3.5 h) — CORE-1, CORE-2 (checkpoints + ETA)

| # | Feature | What Claude builds | Core |
|---|---|---|---|
| 1 | Scaffolding | `frontend/`, `backend/`, `risk_engine/`, `shared/`; `.env.example`; requirements; `/health` on both services | — |
| 2 | Shared schemas | Pydantic models, risk-level enum, units contract (mi, mph, in/hr, lb, UTC) | — |
| 4 | Geocoding (support) | HERE geocode on submit; `GET /api/geocode` | — |
| 5 | Three routes | HERE v8 truck, up to 5 alternatives, gross weight = load + tare; drop near-duplicates; keep 3; via-point fallback if fewer | **CORE-1** |
| 6 | Checkpoints + ETA | Cut every 10/25/50 mi (origin and destination included); ETA from cumulative router durations; round to forecast hour | **CORE-2** |

**You:** create the Python environment, install requirements, put your HERE key in `backend/.env`, run Django and the tests.

**✓ Core check:** a debug call for a long trip (e.g. Denver → Salt Lake City) returns **exactly 3 distinct routes**, each with checkpoints at the chosen interval and an ETA on every checkpoint. Route-selection and sampling tests pass.

### Chunk 2 · Flask risk engine and the analysis API (≈ 3.5 h) — CORE-2 (weather), CORE-3, CORE-4

| # | Feature | What Claude builds | Core |
|---|---|---|---|
| 7 | Risk + load rules | `risk_engine/rules.py`: thresholds, load overrides, worst factor wins; edge-value tests for every boundary | **CORE-3** |
| 8 | Weather at ETA | Open-Meteo client; forecast for each checkpoint's ETA hour; unit normalisation; cache | **CORE-2** |
| 9 | Flask `/v1/evaluate` | Token-protected endpoint; Django client | CORE-2/3 |
| 10 | Scoring & ranking | Segments; miles per level (Severe and No Travel separate); distance-weighted average; sort on No Travel mi, then the four spec keys | **CORE-4** |
| 11 | Analyze API | `POST /api/analyze`: geocode → 3 routes → checkpoints → Flask → ranking | CORE-1–4 |

**You:** run Flask next to Django, run both test suites, send the `curl` command Claude provides.

**✓ Core check:** one `curl` returns 3 ranked routes; every checkpoint has its ETA-hour weather, risk level and reason; the recommendation names the deciding key. All rule-edge and ranking tests pass.

### Chunk 3 · Frontend: form, map and results (≈ 4 h) — CORE-5

| # | Feature | What Claude builds | Core |
|---|---|---|---|
| 3 | Trip input form | Origin, destination, departure, load (lb), interval (10/25/50) | supports all |
| 12 | Map + routes | MapLibre; all 3 routes drawn; recommended route highlighted; click to select | **CORE-5** |
| 13 | Checkpoints on the map | Markers coloured and labelled by risk level; popup with ETA, weather values, reason | **CORE-5** |
| 14 | Route summaries | One card per route: distance, time, Severe/High miles, avg risk, recommended badge + reason | **CORE-5** |
| 17 | Loading & errors | Progress state, error banner, empty states, health call to wake services | — |

**You:** `npm install`, `npm run dev`, try 2–3 real trips, report anything wrong.

**✓ Core check:** in the browser, one submit shows **all 3 routes, every checkpoint with its risk level and ETA, and the summary cards** with the recommended route marked.

### Chunk 4 · Heatmap, slider and deployment (≈ 3 h) — CORE-6

| # | Feature | What Claude builds | Core |
|---|---|---|---|
| 15 | Heatmap data | Flask `/v1/heatmap`: grid over the trip corridor × 49 hourly frames (hour 0 = departure), risk frames using the same rules; cached | **CORE-6** |
| 16 | Heatmap + slider | deck.gl heatmap layer; slider 0–48 h; variable picker (risk, wind, rain, snow); all frames preloaded so scrubbing makes no network calls | **CORE-6** |
| 18 | Deployment | Render (Django, Flask), Vercel (frontend), env vars, CORS, step-by-step guide | — |

**You:** check the slider locally, push to GitHub, deploy following the guide.

**✓ Core check:** on the live URL, a full analysis works and the **heatmap covers the corridor with a slider from 0 to 48 h**.

**After Chunk 4, all six core requirements are working and deployed.**

---

## Upgrade 1 — Phase 2: testing & improvements (≈ 6 h)

Core tests run first; non-core items follow.

| # | Item | Scope | ✓ Done when |
|---|---|---|---|
| T1 | Unit tests | All rule edges + property tests, route selection, sampling, ETA, scoring, ranking | Logic coverage ≥ 90%; every CORE test passes |
| T2 | Contract tests | Django ↔ Flask with shared fixtures; HTTP mocked with `respx` | Both sides pass the same fixtures |
| T3 | Scenario tests | S1–S10 synthetic-weather scenarios | Expected route wins each scenario |
| T4 | Basic E2E | Playwright with mocked API: core map elements visible, slider 0–48, error path | Green locally |
| T5 | Performance checks | Analyze latency, heatmap payload, slider frame time, Lighthouse | Numbers recorded against targets |
| T6 | Edge-case checks | Short/long trips, past departure, timezones, unknown place, outages | Each handled with a clear message |
| I1 | Basic resilience | Timeouts, one retry, graceful errors | Simulated outage shows a clear message |
| I4 | Basic accessibility | Labels, keyboard slider, focus states, contrast, risk as text + colour | axe scan clean of serious issues |
| I5 | Code quality | ruff, mypy (light), ESLint, Prettier, GitHub Actions CI | CI green on `main` |

## Upgrade 2 — Phase 3: non-core enhancements (≈ 3 h)

None of these may change routes, checkpoint weather, risk levels or ranking.

| # | Feature | Scope | ✓ Done when |
|---|---|---|---|
| P3-1 | Mobile responsiveness | Panel becomes a bottom sheet under 768 px; touch-friendly slider | Usable at 360 px wide |
| P3-2 | Unit toggle | Metric/imperial display only; rules still evaluated in imperial | Numbers switch; risk and ranking identical |
| P3-3 | Weather alerts | NWS alerts along routes; informational list + map badges | Shown for US trips; graceful elsewhere |
| P3-4 | Saved trips | localStorage: save, list, reopen (re-runs analysis), delete; max 20 | Survives a page reload |

## Release (≈ 1 h)

README (setup, architecture, interpretation decisions, core compliance table), final deploy, Loom script → your recording.

---

## Timeline (24 h)

| Hours | Claude | You |
|---|---|---|
| 0–3.5 | **Chunk 1** | HERE key; accounts; Node 20+, Python 3.11+; run backend + tests |
| 3.5–7 | **Chunk 2** | Run Flask + tests; send the `curl` result |
| 7–11 | **Chunk 3** | Run frontend; try real trips |
| 11–14 | **Chunk 4** | Check slider; deploy |
| 14–20 | Upgrade 1 (T1–T6, I1, I4, I5) + fixes | Run suites; report failures |
| 20–23 | Upgrade 2 (P3-1 to P3-4) | Test on phone and desktop |
| 23–24 | README + Loom script | Final check; record and submit |

## If time runs short (cut in this order — non-core only)

1. P3-3 Weather alerts
2. T4 E2E beyond one core happy-path test
3. T5 Lighthouse run (keep latency + payload numbers)
4. P3-4 Saved trips
5. Heatmap variable picker (keep the composite risk layer, which satisfies CORE-6)

**Never cut:** CORE-1 to CORE-6, their tests, deployment, README, Loom.
