# Performance Results (T5)

Measured 2026-11-20 on the developer's Windows laptop against the local stack (Django + Flask
dev servers), with **live** HERE and Open-Meteo calls, so these numbers include real
network latency rather than the 300 ms fake latency the strategy suggested.
Re-run with `backend/scripts/perf_check.py` (API) and Lighthouse (browser).

## API

Trip: Chicago, IL → Denver, CO (longest route 1,247 mi), load 42,000 lb.

| Metric | Target | Result | Status |
|---|---|---|---|
| Analyze, 25 mi interval, warm cache | ≤ 8 s | **2.4 s** (139 checkpoints, 3 routes) | ✅ |
| Analyze, 25 mi interval, cold cache | (info) | 4.3 s | — |
| Analyze, 10 mi interval, warm cache | ≤ 12 s | **2.4 s** (341 checkpoints) | ✅ |
| Analyze, 10 mi interval, cold cache | (info) | 3.9 s | — |
| Heatmap request after analyze | (info) | 1.8 s (10 × 25 cells × 49 h) | — |
| Heatmap payload | ≤ 1.5 MB | **201 KB** raw, **21 KB** gzipped | ✅ |
| Analyze payload | (info) | 625 KB raw, **175 KB** gzipped | — |

Gzip (`django.middleware.gzip.GZipMiddleware`) was added during this pass: it cut the
analyze response by 72% and the heatmap by 90%. It is safe here because the API sets no
cookies and returns no secrets.

## Browser

| Metric | Target | Result | Status |
|---|---|---|---|
| Slider frame swap | ≤ 16 ms | **~7 ms** median, 9 ms max over 98 steps (React update + frame swap, includes ~4 ms timer overhead) | ✅ |
| Network calls while scrubbing | 0 | **0** over 98 slider steps; also asserted in the Playwright E2E test | ✅ |
| Lighthouse Performance (desktop) | ≥ 80 | **87** median of 3 runs (75 / 87 / 98) | ✅ |
| Lighthouse Accessibility | ≥ 90 | **100** (all runs) | ✅ |
| Lighthouse Best Practices | (info) | 96: the one console error is the local CORS rejection (preview port 4173 is not an allowed origin) | — |
| Largest Contentful Paint | (info) | 0.7 s | — |
| Total Blocking Time | (info) | 260 ms median (was 480 ms) | — |

Lighthouse varied because page weight varied between runs (3.1 MB, 3.8 MB, 0.4 MB): it
depends on how many basemap tiles load during the measurement. The local `vite preview`
also serves files uncompressed; Vercel compresses them, so production should do better.

**Change made for this target:** deck.gl (609 KB) is now loaded on demand, only after an
analysis returns a heatmap (`React.lazy` in `MapView.tsx`). Before that change Performance
was 78 with 480 ms Total Blocking Time. The remaining main bundle is mostly MapLibre,
which the first screen needs to draw the map.

## Not measured here

- Production (Render + Vercel) numbers: Render's free services sleep after 15 minutes, so
  the first request after idle adds about a minute of wake-up. Re-run the checks above
  against the live URL after deploying (see `docs/deployment.md` §5).
