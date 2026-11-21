# AI Development Tools — How AI Is Used on This Project

This project is developed with an AI pair-programmer. This document states exactly what the AI does, what the human does, and how AI-written code is checked before it ships, so reviewers can judge the work transparently.

---

## 1. Tools

| Tool | Role |
|---|---|
| **Claude (Anthropic)**, in the Claude app | Primary author of all code, tests, configuration and documentation; architecture and planning |
| **Claude Code** (optional) | Same model working in a terminal, if used to run tests and apply fixes directly in the repo |
| **Git + GitHub** | Version history; every AI change lands as a reviewable commit |
| **GitHub Actions** | Runs lint, type checks and tests on every push, independent of the AI |
| Standard tooling | pytest, Vitest, Playwright, ruff, mypy, ESLint, Prettier: objective checks on AI output |

No AI service is called **at runtime**. The deployed app uses only HERE, Open-Meteo and NWS.

## 2. Division of responsibilities

| Area | Claude | Developer (you) |
|---|---|---|
| Specification & decisions | Drafts and documents (`projects specification.md`) | Approves; final say on interpretation |
| Architecture & stack | Proposes options with trade-offs | Chooses (chose Architecture B + C heatmap) |
| Code | Writes all application code and tests | Reads diffs, runs locally |
| Running & verifying | Cannot run against live APIs from its workspace | Runs services, tests and real trips; reports output |
| Secrets | Never sees or handles real API keys | Creates keys; sets env vars locally and on hosts |
| Deployment | Writes configs and instructions; for the release, created the Render and Vercel resources through the developer's connected accounts | Signs in, enters every secret (HERE key, internal token) and approves each step |
| Walkthrough | Writes the Loom script | Records the Loom |

## 3. Workflow per feature

```
1. Pick the next feature from feature roadmap.md
2. Claude restates scope + "done when" criteria
3. Claude writes code + tests for that feature only
4. Developer runs: tests, then the feature by hand
5. Developer pastes any error or unexpected output
6. Claude fixes; repeat 4–5 until "done when" is met
7. Commit with a clear message; tick the feature off
```

Rules for every iteration:

- **The mandatory core is fixed.** CORE-1 to CORE-6 (`projects specification.md` §0) and the rules and interpretations in §5–6 are never changed, reordered or "improved" by the AI. A change to them needs your explicit decision first, recorded in the spec.
- **Small steps.** One feature per change; no unrelated refactors.
- **Tests with code.** Logic changes ship with their tests in the same commit.
- **No invented APIs.** Third-party request/response shapes come from the provider's documentation or a recorded real response, never from guesses.
- **Explain non-obvious choices** in code comments or the relevant doc.

## 4. Prompt templates

**Build a feature**
```
Feature #<n>: <name>. Scope: <scope>. Done when: <criteria>.
Follow architecture.md and API contracts.md. Write the code and its tests only.
```

**Report a failure**
```
Ran: <command>. Expected: <x>. Got: <paste full error / output>.
Environment: <OS, Python/Node version>.
```

**Review**
```
Review <file/feature> against projects specification.md §5–6 and list any rule mismatch.
```

## 5. Verification of AI-written code

AI output is treated as untrusted until it passes these checks:

| Check | Catches |
|---|---|
| Core checks at the end of each chunk | Any CORE-1 to CORE-6 requirement missing or altered |
| Unit tests at every threshold edge (T1) | Off-by-one and boundary errors in risk rules |
| Scenario tests (T3) | Wrong ranking logic |
| Contract tests (T2) | Drift between Django and Flask payloads |
| Recorded real API responses as fixtures | Hallucinated field names or units |
| Lint + type checks in CI (I5) | Dead code, type mismatches, style drift |
| Manual run on real trips | Anything tests can't see: map rendering, UX |
| Developer reads every diff | Logic the developer can't explain doesn't merge |

## 6. Security & privacy guardrails

- API keys are never pasted into the chat; placeholders such as `HERE_API_KEY=` are used in examples.
- `.env` files are git-ignored; only `.env.example` is committed.
- No personal data is collected by the app; saved trips stay in the user's browser.

## 7. Known limitations of the AI workflow

- During development Claude's workspace could not reach HERE, Open-Meteo or NWS, so live-API behaviour was verified by the developer. For the release, Claude ran the live core checks against the deployed API.
- Package installs may be disabled in the Claude workspace; in that case tests run on the developer's machine.
- AI knowledge can lag provider changes; provider docs win over AI memory whenever they disagree.

## 8. Disclosure

The README and the Loom walkthrough will state that the code was written with Claude under the workflow above, with the developer responsible for decisions, verification and deployment.
