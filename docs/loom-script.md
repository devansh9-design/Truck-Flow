# Loom walkthrough script (about 7 minutes)

**Before recording**

- Live site: **https://truck-flow-psi.vercel.app**. Open it a minute early: the free Render services sleep after 15 minutes and the first request is slow.
- Have the README open in a second tab (Judgement calls and Architecture sections).
- Example trip: **Denver, CO → Salt Lake City, UT**, departing tomorrow 08:00, load **45,000 lb** (above the 40,000 lb wind-rule threshold), checkpoints every **25 mi**.
- Close other tabs and notifications; zoom the browser to 110% so text reads on video.

Lines in quotes are what you say; the rest is what you do. Times are a guide, not a rule.

---

## 1. Intro (0:00 – 0:30)

**Show:** the app's start screen.

> "Hi, I'm Devansh. This is Truck Flow, a weather-aware routing tool for trucks. A dispatcher enters a trip, and the app finds three truck routes, checks the weather each route will meet at the hour the truck gets there, and recommends the safest one. I'll show the app, then how it decides, then briefly how it's built."

## 2. The trip form (0:30 – 1:15)

**Do:** type "Den" in Origin, pick *Denver, Colorado* from the suggestions; same for Salt Lake City. Set departure, load 45,000 lb, checkpoint every 25 mi.

> "Places are suggested as I type, and I can filter by country. The load weight matters: the brief's wind rules get stricter for heavier trucks. Checkpoints can be every 10, 25 or 50 miles. Departure time matters because the weather is checked at each checkpoint's arrival time, not right now."

**Do:** click **Compare routes**.

## 3. Three routes and the recommendation (1:15 – 2:45)

**Show:** the map with three routes, and the three route cards.

> "We always show three distinct truck routes from HERE's truck routing. If HERE returns near-duplicates, we drop them and generate alternatives through detour points."

**Point at** the recommended card and its reason line.

> "The recommended route is the safest by the brief's order: fewest Severe miles, then High miles, then average risk, then travel time. We added one rule in front of those: fewest No Travel miles. Otherwise a route with No Travel conditions but zero Severe miles could win. The card tells you which rule decided it."

**Point at** the Severe / High / No Travel miles and drive time on each card.

> "Each card shows the miles at each risk level, average risk, distance and drive time, so the trade-off is visible, not just the answer."

## 4. Checkpoints (2:45 – 3:45)

**Do:** click another route card to select it; the line recolours by risk. Click a checkpoint on the map.

> "The selected route is coloured by risk between checkpoints. Each stretch takes the worse of its two checkpoints, which is the cautious choice."

**Show:** the popup (ETA, forecast hour, wind / rain / snow, per-factor levels, reason).

> "Each checkpoint shows when the truck arrives, the forecast for that hour, and why it got its level, for example wind of 38 miles an hour with a load over 40,000 pounds gives Severe."

## 5. Heatmap slider (3:45 – 4:45)

**Do:** drag the slider from 0 to 48 h; press play; switch the variable (wind / rain / snow).

> "This heatmap covers the whole corridor for the next 48 hours, starting at departure. All 49 hours are loaded once, so scrubbing makes no network calls; it's instant. The truck marker shows where the truck would be at that hour. This answers 'what if I leave later?' at a glance."

## 6. Extras, quickly (4:45 – 5:45)

Pick two or three; don't show everything.

- **Units:** flip mi ↔ km. "Everything switches, including the form."
- **Weather alerts:** "Official NWS alerts along US routes are listed here. They're informational and never change the ranking."
- **Saved trips:** save, then reopen. "Reopening re-runs the analysis with fresh weather."
- **Mobile:** narrow the window or show your phone. "On a phone, results sit in a bottom sheet."
- **Driving mode:** "On a phone, Start trip follows the truck's position, re-checks the road ahead every 15 minutes and warns, with voice, if another route becomes safer."

## 7. How it's built (5:45 – 6:45)

**Show:** the README Architecture diagram.

> "Three parts. The React website. A Django API, the only public part, which gets routes from HERE, places checkpoints and ranks routes. And a private Flask risk engine, which fetches Open-Meteo forecasts and applies the brief's risk and load rules. Accounts and saved trips live in Postgres. The website is on Vercel, the API and risk engine on Render. One deployment detail: Render's free servers share IP addresses that were already over Open-Meteo's free daily limit, so in production the weather requests go through a small relay function on Vercel."

**Show:** the README Judgement calls table.

> "Where the brief was ambiguous, for example rain of exactly 0.25 falling in two bands, we wrote down our choice. Everything here is tested: unit tests for every threshold edge, full-stack scenario tests, browser tests with accessibility checks, and CI on every push."

## 8. Close (6:45 – 7:15)

> "I built this with Claude as my coding assistant. I made the product decisions, verified the results and deployed it. The repo README has setup steps, the decisions and the docs. Thanks for watching."

---

**If something goes wrong while recording**

- Slow first analysis: say "the free server is waking up" and wait; don't restart.
- An error banner: click **Try again**.
- Weather looks calm everywhere: that's fine. Point at the reason text and the miles per level, and use the heatmap to show where risk would appear.
