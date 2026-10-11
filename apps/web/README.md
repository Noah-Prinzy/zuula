# Zuula web app

Zuula is the web front end of **Uganda Fact-Guard**, an AI fake-news detection platform specified by Victoria University's Centre for Intelligent Technologies (*System Development Plan & Functional Requirements Specification v1.0*, April 2026). Requirement IDs in the code and docs (FR-AUTH-01, §9.2, …) refer to that specification.

- Pages and routes: [docs/ui/sitemap.md](../../docs/ui/sitemap.md)
- Components: [docs/ui/component-inventory.md](../../docs/ui/component-inventory.md)

## Implementation plan

Deadline **30 Nov 2026**, one developer.

| Phase | Dates | Scope | Status |
|---|---|---|---|
| P1 Frontend | 21 Sep – 9 Oct | Next.js 16 + shadcn/ui, every page on mock data | In progress — core pages done; auth layout, home hero and mobile UI passes landed ahead of schedule |
| P2 API design | 12 – 20 Oct | FastAPI core REST API; separate partner API (API keys, 100 requests/hour); SSE/WebSockets; WhatsApp and Telegram webhooks; AI job queue (Celery + Redis); OAuth, Africa's Talking SMS, Turnstile, ClamAV, S3 | Done — Steps 1–6 merged |
| P3 Backend + database | 21 Oct – 6 Nov | PostgreSQL + pgvector, Redis, auth (bcrypt, 2FA), weighted CCS and escalation, audit log | Done — PRs 1–6 merged (DB foundation, auth/roles, content, admin, real adapters, docs); [ADR 0002](../../docs/adr/0002-p3-backend-and-database.md) accepted |
| P4 AI engine | 9 – 24 Nov | Hosted LLM (Claude) with evidence retrieval; Sunbird AI for Ugandan languages; Whisper; RoBERTa AI-text detector and a deepfake API; evaluation on about 500 labelled items | In progress — Groq+Tavily verdict engine (dedupe check, one search + one Llama 3.3 70B call per claim), Groq Whisper transcription, trafilatura article fetch, local RoBERTa AI-text signal, and 363 real AFP-verified fact-checks all merged (PRs #46, #48); `GROQ_API_KEY`/`TAVILY_API_KEY` now set and the FR-DETECT-03 accuracy run against the held-out ~500-item set is in progress. Still open: backfilling embeddings on seeded reports so dedupe has anything to match against, and the deepfake API (dropped for v1, see below) |
| Hardening + launch | 25 – 30 Nov | Security, performance, deployment | Not started |

All four phases above are running well ahead of their scheduled windows — P2, P3 and P4 are each substantially built before their windows have opened (P3 finished on 23 Sep, four weeks before its 21 Oct start; P4's first PRs merged 3 Oct, five weeks before its 9 Nov start).

Repo layout: `apps/web` (this app), `apps/api` (P2–P4), `packages/shared`. `apps/api` now has substantial code (see its own README), including the P4 AI providers (`app/providers/`). The original plan's `services/ai` directory was never used — P4 landed inside `apps/api` instead, following the same real-or-stub provider pattern as every other integration there.

Pages live in `app/[locale]/(public|auth|app)/`. The URL never carries the language: `proxy.ts` (next-intl, `localePrefix: "never"`) maps the `NEXT_LOCALE` cookie to the `[locale]` segment, so each language is prerendered. English strings live in `messages/en.json`.

### Changes from the specification

These were agreed during planning and still need the supervisor's sign-off.

| Spec | Plan | Why |
|---|---|---|
| Fine-tuned LLaMA 3 / Mistral trained on Ugandan corpora (§5) | Hosted LLM with evidence retrieval, Sunbird AI for local languages | 10-week timeline; no training data or GPU budget yet |
| Accuracy targets of at least 90% text and 85% deepfake (FR-DETECT-03, 04) | Measured on about 500 labelled items | Estimates only, not proof |
| Native Android and iOS apps (Phase 5) | PWA at launch, React Native after | Timeline |
| Kubernetes (§7.4) | Docker Compose | Single-server deployment is enough at launch |
| Browser extension (FR-API-04), coordinated behaviour detection (FR-DETECT-09) | After launch | Low priority in the spec |
| 14-month roadmap, AI before platform (§8) | 10 weeks, frontend first | Deadline |
| Product name "Uganda Fact-Guard" | Branded "Zuula" | — |

Open questions for the supervisor:
- FR-RATE-05 escalates at more than 100 *dislikes*; §9.2 says more than 100 *ratings*. The code follows §9.2.
- The spec gives admins no rating weight. The code uses 1×.
- FR-API-01 targets media organisations, but FR-AUTH-02 has no organisation role. API keys are currently limited to Verified Journalists and Admins.
- Sending submissions to a hosted LLM outside Uganda must be checked against the Data Protection and Privacy Act 2019 (§10.1).
- FR-RATE-10's leaderboard (a Wilson-lower-bound ranking on weighted CCS, at least 25 ratings) was built on the home page and moved to `/verify` at Noah's request (24 Sep 2026). The home hero's Community card still rotates the same top-rated verdicts as a teaser.

### Known gaps

- Ratings, review, admin and account settings still use mock data from `lib/mock`. Fact-checks (home, library, report, `/verify` leaderboard) now call the real API, falling back to the mock data if it's unreachable (PR #48). Sign-up, sign-in, two-factor, password reset, sign-out and "who am I" are real calls to `apps/api` (`lib/api.ts`); see "Signing in locally" below.
- Role checks in the UI run in the browser, from the real session's role. The API enforces roles on its own endpoints, but most screens don't call it yet.
- CAPTCHA is off in development.
- Python must be upgraded to 3.12 before P3.
- `messages/{lg,ach,nyn,teo}.json` are partial, unreviewed machine drafts (Sunbird AI). Keys they don't have fall back to English. They need native-speaker review before they count as real translations.
- `fact_check_reports.embedding` isn't backfilled for the 363 seeded real reports (or the fictional sample reports), so the P4 dedupe cache (pgvector cosine search) has nothing to match against yet — new live submissions still populate it correctly. See `apps/api/README.md`'s "Verdict engine (P4)" section.

## Development

```bash
npm install
npm run dev
```

Checks: `npm run lint`, `npm run typecheck`, `npm test`.

### Demo sign-in (until the API is hosted)

A production build with no `NEXT_PUBLIC_API_URL` (the deployed site today) uses a browser-only demo sign-in instead of the API (`lib/demo-auth.ts`): any password works, the part of the address before `@` picks the role (`admin@`, `expert@`, `journalist@`, anything else is a Public User), codes are any 6 digits except `000000`, and the "Demo: view as" bar switches roles directly. Nothing is sent anywhere and nothing is protected. Setting `NEXT_PUBLIC_API_URL` switches to real sign-in; `NEXT_PUBLIC_AUTH_MODE=api|demo` forces either.

### Signing in locally

Sign-in needs `apps/api` running with its database (see [its README](../api/README.md)). Then:

```bash
cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                  # open http://localhost:3000 (not 127.0.0.1: the session cookie is SameSite=Lax)
```

Deployed, the API usually isn't on a sibling subdomain (e.g. Vercel + Render), so the site proxies it instead: set `NEXT_PUBLIC_API_URL=/` and `ZUULA_API_ORIGIN=<the API's URL>` in the web app's build environment, and the site's own origin in the API's `ZUULA_CORS_ORIGINS`. See `.env.example` and [docs/deploy/render-agent-prompt.md](../../docs/deploy/render-agent-prompt.md).

- Seeded accounts (`python -m app.db.seed`) all use the password `zuula-sample-password`: `amina@example.com` (Public User), `sarah@example.com` (Journalist), `david@example.com` (Expert), `mary@example.com` (Admin). Experts and admins get a two-factor code.
- Codes (sign-up, two-factor, reset) go through the API's stub email/SMS adapters, which only log them at INFO level. A plain `uvicorn app.main:app` doesn't show that level, so run the API with logging on to see them:
  `python -c "import logging, uvicorn; logging.basicConfig(level=logging.INFO); uvicorn.run('app.main:app', reload=False)"`
- Some Safari versions won't store the API's `Secure` cookie over plain `http://localhost`; if sign-in doesn't stick there, set `ZUULA_SESSION_COOKIE_SECURE=false` in `apps/api/.env`. Chrome and Firefox work as is.
- `NEXT_PUBLIC_ROLE_SWITCHER=true` adds a "Preview as" bar for looking at role-gated screens as a sample user while signed out. It's a UI preview, not sign-in: it grants nothing in the API and disappears once you really sign in. It's off unless set. Add shadcn components with `npx shadcn@latest add <name>`; they go in `components/ui`.
