# Project Specification — Weather-Aware Truck Routing System

> Source: *fs-assessment-spotter.pdf* (Weather-Aware Truck Routing specification, pp. 1–2), plus the scope agreed for this build.
> Guiding constraint from the brief: **prioritize correctness and clarity over extra features.**

---

## 0. Mandatory core (fixed — cannot be changed, cut or overridden)

| ID | Core requirement | Spec source | Built in |
|---|---|---|---|
| **CORE-1** | **Three route options** from a routing API | §3A | Chunk 1 |
| **CORE-2** | **Time-aware checkpoint weather**: sampled every 10, 25 or 50 mi, at the truck's ETA at each checkpoint | §3B | Chunks 1–2 |
| **CORE-3** | **Specified risk and load rules**, exactly as tabled in §5.1–5.3 | §4, §5 | Chunk 2 |
| **CORE-4** | **Specified recommendation priorities**: Severe miles → High miles → average risk → travel time, in that order. One documented safety key (fewest No Travel miles, D4) runs before them; the spec's four keys are never reordered or removed. | §6 | Chunk 2 |
| **CORE-5** | **Map visualization** of all routes, checkpoints, risk levels, ETAs and route summaries | §3E | Chunk 3 |
| **CORE-6** | **Weather heatmap** along the trip corridor with a **0–48 hour forecast slider** | §3F | Chunk 4 |

Rules for everything else in this project:

- Every other feature is **non-core**. It may be simplified, delayed or cut, and it must **never change** a core result (routes, checkpoint weather, risk levels, ranking or recommendation).
- Where the spec is ambiguous, §6 records one interpretation. No interpretation may remove or reorder a spec rule or ranking key. The only added ranking key is the No Travel safety key (D4), agreed explicitly and stated in the README.

---

## 1. Problem statement

Build a **React + Django** web application that helps a truck driver choose the safest route based on:

- weather conditions,
- load weight,
- travel time.

The app generates multiple route options, evaluates the weather along each one at the time the truck will actually be there, classifies risk using the specified rules, and recommends the best route. It shows all routes, checkpoints, risk levels, ETAs and route summaries on a map, plus a weather heatmap along the trip corridor with a 0–48 hour forecast slider.

## 2. User inputs

| Input | Type | Validation |
|---|---|---|
| Origin | Free-text place or address | Must geocode to one location |
| Destination | Free-text place or address | Must geocode; must differ from origin |
| Departure date/time | Local date-time with timezone | Not more than 1 hour in the past; not beyond the forecast horizon (see §6.6) |
| Load weight | Number, pounds | 1–100,000 lb (input sanity check only; it never changes a risk rule) |
| Sampling interval | 10, 25 or 50 miles | Default 25 mi |

## 3. Functional requirements

| ID | Requirement (from spec) | Core |
|---|---|---|
| FR-A | Generate **3 route options** using a routing API. | CORE-1 |
| FR-B1 | Sample weather at intervals of **10, 25 or 50 miles**. | CORE-2 |
| FR-B2 | Use the truck's **estimated arrival time at each checkpoint** when sampling weather. | CORE-2 |
| FR-C | Calculate weather risk using the **risk and load rules** (§5). | CORE-3 |
| FR-D | Recommend the best route by balancing weather risk and travel time, using the **priority order** in §5.4. | CORE-4 |
| FR-E | Show on a map: all routes, checkpoints, risk levels, ETAs, route summaries. | CORE-5 |
| FR-F | Show a **weather heatmap** along the trip corridor with a **0–48 h forecast slider**. | CORE-6 |

### Non-core additions (agreed scope; never change core results)

| ID | Requirement |
|---|---|
| FR-G | Responsive layout usable on mobile (≥ 360 px wide). |
| FR-H | Metric / imperial unit toggle (display only; rules always evaluated in imperial). |
| FR-I | Basic weather alerts along the route (US National Weather Service active alerts). **Informational only:** alerts never change a risk level or the ranking. |
| FR-J | Saved trips in the browser (localStorage). |

## 4. Non-functional requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-1 | Analysis latency (warm cache, ~1,000 mi route, 25 mi interval) | ≤ 8 s end to end |
| NFR-2 | Heatmap slider | No network calls while scrubbing; frame swap ≤ 16 ms |
| NFR-3 | Heatmap payload | ≤ 1.5 MB per corridor |
| NFR-4 | Correctness | Every threshold edge covered by a unit test |
| NFR-5 | Accessibility | Keyboard-operable controls, labelled inputs, risk shown by text + colour |
| NFR-6 | Resilience | Upstream timeouts produce a clear error, never a blank screen |
| NFR-7 | Secrets | API keys only in environment variables, never in the repo or the browser |

## 5. Rules (authoritative)

### 5.1 Weather risk thresholds

Intervals are **half-open `[lower, upper)`** unless the spec says "Above", in which case the boundary value belongs to the lower class.

**Wind speed (sustained, 10 m, mph)**

| Class | Range |
|---|---|
| Low | < 25 |
| Moderate | 25 ≤ w < 35 |
| High | 35 ≤ w < 45 |
| Severe | 45 ≤ w < 55 |
| No Travel | ≥ 55 |

**Rainfall intensity (in/hr)**

| Class | Range |
|---|---|
| Low | < 0.10 |
| Moderate | 0.10 ≤ r < 0.25 |
| High | 0.25 ≤ r < 0.50 |
| Severe | 0.50 ≤ r ≤ 1.00 |
| No Travel | > 1.00 |

**Snowfall intensity (in/hr)**

| Class | Range |
|---|---|
| Low | < 0.5 |
| Moderate | 0.5 ≤ s < 1.0 |
| High | 1.0 ≤ s < 2.0 |
| Severe | 2.0 ≤ s ≤ 3.0 |
| No Travel | > 3.0 |

### 5.2 Load-dependent rules

| Wind speed | Load | Result |
|---|---|---|
| ≥ 55 mph | Any | No Travel |
| 45 ≤ w < 55 mph | > 30,000 lb | No Travel |
| 35 ≤ w < 45 mph | > 40,000 lb | Severe |

Load rules can only **raise** a classification, never lower it.

### 5.3 Checkpoint risk

`checkpoint_level = max(wind_level, rain_level, snow_level, load_override)`

Ordinal scores: Low = 1, Moderate = 2, High = 3, Severe = 4, No Travel = 5.

### 5.4 Route recommendation

The spec compares routes in this order:

1. Fewest **Severe** miles
2. Fewest **High** miles
3. Lowest **average risk**
4. Shortest **travel time**

**Our ranking (interpretation D4):** one safety key is placed in front of the spec's four. Its order is otherwise unchanged:

| Order | Key | Source |
|---|---|---|
| 0 | Fewest **No Travel** miles | Our interpretation (D4) |
| 1 | Fewest **Severe** miles | Spec |
| 2 | Fewest **High** miles | Spec |
| 3 | Lowest **average risk** | Spec |
| 4 | Shortest **travel time** | Spec |

The route ranked first is the recommended route. See D3–D5 for how miles and averages are measured.

## 6. Interpretation decisions

The spec leaves these points open. Each decision is fixed here, implemented once, and tested.

| # | Question | Decision |
|---|---|---|
| D1 | Shared boundaries (e.g. rain 0.25 appears in Moderate and High) | Half-open intervals; the value goes to the higher class, except the "Above" boundaries (rain 1.00, snow 3.00), which stay in Severe. |
| D2 | How miles are attributed | The route is split into **segments between consecutive checkpoints** (origin and destination are checkpoints). A segment's level = the **worse** of its two endpoints (conservative). |
| D3 | "Severe miles" vs "No Travel miles" | Kept **separate**. Severe miles = sum of segment lengths classed Severe only. No Travel miles = sum of segment lengths classed No Travel. Both are reported for every route. |
| D4 | How No Travel affects ranking | The spec's keys don't mention No Travel, but ignoring it would let a route with No Travel miles and 0 Severe miles beat a route with only Severe miles. So **fewest No Travel miles** is ranked first (key 0), followed by the spec's four keys in their original order. Any route with No Travel miles also shows a prominent "No Travel conditions" warning, including the recommended route when every option has them. |
| D5 | Average risk | Distance-weighted mean of segment scores (1–5). |
| D6 | Ties | Compare miles rounded to 0.1 mi and average risk to 0.01, so floating-point noise never decides a ranking. Travel time, the last key, is compared exactly as the router reports it (HERE gives whole seconds), with no rounding. |
| D7 | ETA at a checkpoint | Departure time + cumulative router travel time to that point (from the router's per-segment durations), rounded to the **nearest forecast hour**. HERE gives a duration per speed-limit span, not per coordinate, so inside a span the time is spread by distance: checkpoint ETAs are an informed approximation (exact at span boundaries), not provider timestamps. |
| D8 | Wind speed | Sustained `wind_speed_10m`, not gusts (the spec says "speed"). |
| D9 | Rain | `rain + showers` (liquid) in in/hr; snowfall is classified separately. |
| D10 | Snow units | Converted explicitly to inches/hour from whatever unit the provider reports. |
| D11 | Forecast horizon | Forecasts are requested for up to 16 days so long trips are covered. If a checkpoint ETA still falls beyond the horizon, the request is rejected with a clear message. |
| D12 | Guaranteeing 3 routes (CORE-1) | Ask HERE for up to 5 alternatives, drop near-duplicates (> 90% shared length) and keep the best 3. If fewer than 3 remain, generate extra options through a via-point offset to either side of the route midpoint. Only if no third distinct road exists (e.g. a very short trip) are fewer shown, with the reason stated. |
| D13 | Weight sent to the router | The router needs gross vehicle weight = load + `TRUCK_TARE_LB` (configurable, default 35,000 lb). The risk and load rules always use the **load weight exactly as entered**. |
| D14 | Heatmap time base | Slider hour 0 = the departure hour; hours 0–48 run forward from it. |

## 7. Deliverables

1. **GitHub repository** — complete source code.
2. **Hosted application** — deployed and reachable by URL.
3. **Loom walkthrough** — 5–10 minutes.

## 8. Evaluation criteria (from the brief)

| Category | Weight |
|---|---|
| Routes, weather, risk and recommendation logic | 40% |
| UI, map and heatmap smoothness and performance | 40% |
| Code quality | 15% |
| Documentation and walkthrough | 5% |

## 9. Out of scope

- Building a routing engine (third-party APIs are used).
- User accounts, server-side trip storage, payments.
- Real-time traffic, tolls, hours-of-service planning.
- Phase 4 production hardening (observability, load testing, quotas).

## 10. Acceptance criteria

**Core (all must pass):**

- [ ] CORE-1: 3 distinct route options are returned (D12 explains the only exception).
- [ ] CORE-2: Checkpoints every 10/25/50 mi; each checkpoint's weather is from its ETA hour.
- [ ] CORE-3: Every threshold and load-rule edge in §5.1–5.3 passes unit tests.
- [ ] CORE-4: Ranking uses No Travel miles (D4), then the spec's four keys of §5.4 in order; the top-ranked route is recommended.
- [ ] CORE-5: The map shows all routes, checkpoints, risk levels, ETAs and route summaries.
- [ ] CORE-6: The heatmap covers the corridor; the slider moves 0–48 h.

**Non-core:**

- [ ] Slider scrubbing makes no network calls (performance target).
- [ ] Units toggle, alerts, saved trips and mobile layout work, and none changes a core result.
- [ ] The app is deployed, the README explains setup and decisions, and the Loom is recorded.
