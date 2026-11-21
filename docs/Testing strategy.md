# Testing Strategy — Weather-Aware Truck Routing System

**Goal:** prove the logic is correct (40% of the grade) and the UI is smooth (40%), with fast, deterministic tests. **No test calls a live third-party API.**

---

## 0. Mandatory core coverage

Every core requirement has tests that must pass before any non-core work is tested or released.

| Core | Proved by |
|---|---|
| CORE-1 three routes | Route-selection unit tests (dedupe, top 3, via-point fallback); S1 |
| CORE-2 time-aware checkpoint weather | Sampling + ETA unit tests; S8 (weather taken at ETA hour, not departure) |
| CORE-3 risk/load rules | Edge tables in §2.1 (every boundary) + property tests |
| CORE-4 recommendation priorities | Ranking unit tests (§2.3) + S2–S7, S9, S10 |
| CORE-5 map visualization | E2E happy path: routes, checkpoint markers, risk labels, ETAs, summary cards visible |
| CORE-6 0–48 h heatmap slider | Heatmap unit test (49 frames, correct grid) + E2E slider test |

## 1. Test pyramid

| Layer | Tool | Scope | Count (approx.) | Runs |
|---|---|---|---|---|
| Unit (T1) | pytest, hypothesis, Vitest | Rules, sampling, ETA, scoring, ranking, unit conversion | 80–120 | Every push |
| Contract (T2) | pytest + respx + shared fixtures | Django ↔ Flask payloads | 10–15 | Every push |
| Scenario (T3) | pytest | Whole analysis with synthetic weather | 8–10 | Every push |
| E2E (T4) | Playwright (API mocked) | Browser happy path + error path | 3–4 | Before release |
| Performance (T5) | scripts + browser tooling | Latency, payload, slider frame time | Measured | Before release |
| Edge cases (T6) | pytest + manual checklist | Odd inputs and outages | 10–12 | Before release |

## 2. T1 — Unit tests

### 2.1 Risk rules (`risk_engine/tests/test_rules.py`)

Parametrised table tests at **every edge**: just below, exactly at, just above.

| Factor | Values tested → expected |
|---|---|
| Wind | 24.99 L · 25 M · 34.99 M · 35 H · 44.99 H · 45 S · 54.99 S · 55 NT |
| Rain | 0.099 L · 0.10 M · 0.249 M · 0.25 H · 0.499 H · 0.50 S · 1.00 S · 1.001 NT |
| Snow | 0.49 L · 0.5 M · 0.99 M · 1.0 H · 1.99 H · 2.0 S · 3.0 S · 3.001 NT |

Load rules:

| Wind | Load | Expected |
|---|---|---|
| 55 | 1,000 | NO_TRAVEL |
| 45 | 30,000 | SEVERE (not over 30,000) |
| 45 | 30,001 | NO_TRAVEL |
| 54.99 | 30,001 | NO_TRAVEL |
| 35 | 40,000 | HIGH (not over 40,000) |
| 35 | 40,001 | SEVERE |
| 44.99 | 40,001 | SEVERE |
| 34.99 | 80,000 | MODERATE (no override) |

Combination: `max()` of factors (e.g. rain HIGH + snow SEVERE → SEVERE). Negative or NaN inputs raise `ValueError`.

**Property tests (hypothesis):**

- Monotonic: raising any one input never lowers the level.
- Load monotonic: a heavier load never lowers the level.
- The result is always one of the five enum values.

### 2.2a Route selection (`backend/tests/test_routes.py`)

- 5 alternatives from HERE → exactly 3 kept, fastest distinct first.
- Two alternatives sharing > 90% of their length → one dropped as a near-duplicate.
- Only 1–2 distinct alternatives → via-point detours requested until 3 exist.
- Gross weight sent to HERE = load + `TRUCK_TARE_LB`; the load passed to the rules is unchanged.

### 2.2 Sampling & ETA (`backend/tests/test_sampling.py`)

- A straight synthetic 100 mi line at 25 mi → checkpoints at 0, 25, 50, 75, 100.
- A 103 mi line → the final checkpoint is at 103 (destination always included).
- A route shorter than the interval → origin + destination only.
- Constant speed → ETA proportional to distance.
- Two sections with different speeds → ETAs follow section durations.
- ETA rounding: :29 rounds down, :30 rounds up.
- Haversine distance within 0.5% of reference values.

### 2.3 Scoring & ranking (`backend/tests/test_scoring.py`)

- Segment level = worse endpoint.
- Miles per level sum to the route distance (±0.1 mi).
- `severe_mi` and `no_travel_mi` are separate: a No Travel segment adds to `no_travel_mi` only (D3).
- Distance-weighted average checked by hand-calculated example.
- Ranking uses **only** these keys, in this order: No Travel miles → Severe miles → High miles → avg risk → duration. A test asserts no other field affects order.
- A route with 5 No Travel miles and 0 Severe miles ranks below a route with 0 No Travel and 10 Severe miles.
- Ties within rounding (D6) fall through to the next key.
- `decided_by` names the key that separated rank 1 from rank 2.
- Any route with No Travel miles carries the `NO_TRAVEL_CONDITIONS` warning.

### 2.4 Frontend units (`frontend/tests/*.test.ts`)

- Unit conversion mi↔km, mph↔km/h, in/hr↔mm/hr (round trip within tolerance).
- Risk → colour + label + icon mapping is complete for all 5 levels.
- Saved-trips store: add, list, delete, cap at 20, survives JSON parse errors.

## 3. T2 — Contract tests

- Shared JSON fixtures in `shared/fixtures/` (`evaluate_request.json`, `evaluate_response.json`, `heatmap_response.json`).
- **Flask side:** posting each request fixture to the Flask test client returns a body that validates against the Pydantic response model.
- **Django side:** Django's `risk_engine` client, with the HTTP layer mocked by `respx` to return the response fixture, parses it without error and maps it into scoring inputs.
- Negative cases: missing token → 401; malformed body → 400 with the standard error shape; result count ≠ input count → client raises.

## 4. T3 — Scenario tests

Synthetic weather is injected by replacing the forecast provider with a fake that returns scripted values per (lat, lon, hour). Routes come from recorded HERE fixtures.

| # | Scenario | Expected |
|---|---|---|
| S1 | Calm everywhere | 3 routes returned; fastest recommended (`decided_by: duration_s`) |
| S2 | Storm (wind 47 mph) on the fastest route only, load 20,000 lb | Slower clear route wins on Severe miles |
| S3 | Same storm, load 35,000 lb | Storm segments become No Travel; the clear route wins on No Travel miles (`decided_by: no_travel_mi`); warning shown on the storm route |
| S4 | Wind 38 mph on route A, load 45,000 lb | Route A segments Severe via load rule |
| S5 | Equal Severe miles, different High miles | Fewer High miles wins |
| S6 | Equal Severe + High, different avg risk | Lower average wins |
| S7 | Everything equal | Shorter duration wins |
| S8 | Heavy snow moves in during the trip (ETA-dependent) | Risk uses the arrival hour, not the departure hour |
| S9 | All routes have No Travel | Fewest No Travel miles wins, then the spec's keys; rank 1 recommended with a prominent No Travel warning |
| S10 | Route A: 5 No Travel mi, 0 Severe mi; Route B: 0 No Travel mi, 10 Severe mi | Route B recommended |

## 5. T4 — Basic E2E (Playwright)

API calls are intercepted with `page.route()` and answered from fixtures, so tests are fast and never flaky.

1. **Happy path:** fill the form → submit → 3 route cards → recommended badge visible → click a checkpoint → popup shows ETA and risk.
2. **Heatmap:** the slider moves 0 → 48; no `/api/heatmap` request after the first.
3. **Error path:** analyze returns 502 → error banner with retry; no blank map.
4. **Saved trip:** save → reload page → trip is listed → reopen re-runs the analysis.

## 6. T5 — Performance checks

| Metric | Target | How measured |
|---|---|---|
| Analyze, warm cache, ~1,000 mi, 25 mi interval | ≤ 8 s | Timed script against local stack (fake upstream latency 300 ms) |
| Analyze, 10 mi interval | ≤ 12 s | Same |
| Heatmap payload | ≤ 1.5 MB | Response size in DevTools |
| Slider frame swap | ≤ 16 ms (60 fps) | `performance.now()` around layer update; DevTools Performance panel |
| Network calls while scrubbing | 0 | DevTools Network panel / Playwright assertion |
| Lighthouse (desktop) | Performance ≥ 80, Accessibility ≥ 90 | Lighthouse in Chrome |

Results are recorded in `docs/performance-results.md`.

## 7. T6 — Edge-case checks

| Case | Expected |
|---|---|
| Unknown place | 404 `PLACE_NOT_FOUND`, inline form message |
| Same origin and destination | 400 validation message |
| Departure in the past (> 1 h) | 400 validation message |
| ETA beyond forecast horizon | 422 `BEYOND_FORECAST_HORIZON` with explanation |
| Very short trip (< interval) | Origin + destination only, still ranked |
| Very long trip (> 48 h) | Analysis works; heatmap still covers 0–48 h |
| Departure across a timezone/DST change | ETAs correct in UTC; display in local time |
| Router returns < 3 distinct routes | Via-point fallback produces 3; fewer only if no third road exists, with a note |
| Open-Meteo timeout | 504 with retry message |
| Flask down | 502 with message; `/api/health` shows `risk_engine: "down"` |
| Load 0 or > 100,000 | 400 validation message |
| Non-US trip (alerts) | Alerts panel says "not available for this region" |

## 8. Accessibility checks (I4)

- `@axe-core/playwright` scan of the main screen: no serious or critical violations.
- Keyboard only: form → submit → route cards → slider (arrow keys move 1 h, Page Up/Down 6 h).
- Every input has a label; the slider has `aria-valuetext` (e.g. "+12 h, Fri 01:00").
- Risk shown as text + icon + colour; palette checked for colour-blind safety.

## 9. Fixtures & determinism

- Real HERE and Open-Meteo responses are recorded once (keys removed) and stored in `tests/fixtures/`.
- Time is frozen in tests (`freezegun` / Vitest fake timers).
- No test depends on the network, the current weather or the current date.

## 10. Commands

```bash
# backend + risk engine
cd backend && pytest -q
cd risk_engine && pytest -q

# frontend
cd frontend && npm test             # Vitest
cd frontend && npx playwright test  # E2E

# quality
ruff check . && mypy backend risk_engine
cd frontend && npm run lint
```

## 11. Exit criteria for Phase 2

- [x] Every CORE-1 to CORE-6 test in §0 passes.
- [x] All T1–T3 tests pass (locally; CI runs them on every push): backend 160, risk engine 173, shared 4, frontend 40. Logic coverage: backend 96%, risk engine 99%.
- [x] T4 E2E passes locally: 7 Playwright tests (`frontend/e2e/`), API and map mocked from recorded fixtures.
- [x] T5 numbers recorded in `docs/performance-results.md`; all targets met.
- [x] Every T6 case behaves as listed (`backend/tests/test_edge_cases.py` + existing tests), except weather alerts, which are built in Upgrade 2 (P3-3).
- [x] axe scan clean of serious/critical issues (start and results screens).
- [ ] CI (I5) green on `main`: `.github/workflows/ci.yml` added; green once pushed.

Notes from this pass:
- T3 scenarios (`backend/tests/test_scenarios.py`) run Django and the **real Flask app** together with scripted weather, so the actual rules and load overrides decide every outcome.
- Saved-trips and unit-conversion tests (§2.4, §5 item 4) wait for those Upgrade 2 features.
