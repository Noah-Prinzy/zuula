# Zuula — State of the Project

**Zuula** is the product name for **Uganda Fact-Guard**, an AI fake-news detection platform specified by Victoria University's Centre for Intelligent Technologies (*System Development Plan & Functional Requirements Specification v1.0*, April 2026). Requirement IDs used everywhere (FR-AUTH-05, §9.2, …) refer to that specification.

This is the project's single document. It replaces the separate READMEs, ADRs, UI docs, deploy notes, eval report and the `app plan/` planning notes. Part 1 says where things stand today; Part 2 keeps every earlier document word for word, so nothing that was written down has been lost.

*Last updated: 28 October 2026 (status review and next-phase plan, §11).*

**Contents**

- [Part 1 — Where the project stands](#part-1--where-the-project-stands)
  - [1. Team and how we work](#1-team-and-how-we-work)
  - [2. Status at a glance](#2-status-at-a-glance)
  - [3. Architecture](#3-architecture)
  - [4. Supabase: what is set up](#4-supabase-what-is-set-up)
  - [5. Sign-in: three modes](#5-sign-in-three-modes)
  - [6. Running it locally](#6-running-it-locally)
  - [7. Security decisions](#7-security-decisions)
  - [8. What's left](#8-whats-left)
  - [9. The completion plan (cost-free stack)](#9-the-completion-plan-cost-free-stack)
  - [10. Design resources](#10-design-resources)
  - [11. Next steps: plan to launch (28 Oct 2026)](#11-next-steps-plan-to-launch-28-oct-2026)
- [Part 2 — Reference (the earlier documents, unchanged)](#part-2--reference-the-earlier-documents-unchanged)

---

# Part 1 — Where the project stands

## 1. Team and how we work

| Who | Role |
|---|---|
| **Noah** | Project owner and supervisor. Final say on direction, approvals, anything touching accounts, credentials or production. |
| **Milka** (Claude) | Senior lead: architecture, code review, complex work, keeping this document current. |
| **Jason** (OpenCode agent, Mistral Large) | Assistant for small, well-scoped tasks: a function, a test, docs, research. Defined in `.opencode/agents/jason.md`; Milka delegates with `powershell -File .opencode/jason.ps1 "<task>"`. Jason can edit files and run commands but can't commit, push, switch branches, reset or delete, and must never handle secrets. Everything he produces is reviewed before it's committed. |

Other Claude sessions may work in the same `D:\Zuula` checkout at once, so:

- Commit each finished piece straight away, **with explicit paths** (`git commit -- <paths>`), after checking `git diff --cached --stat`.
- **Never push** unless Noah asks: `main` deploys to production (Vercel).
- Never switch branches in the shared checkout; parallel work happens in its own git worktree.
- Keep `npx tsc --noEmit` (web) and `pytest` (API) green. `messages/*.json` hold strings or nested objects, never arrays.

Deadline: **30 November 2026**.

## 2. Status at a glance

| Area | State |
|---|---|
| P1 Frontend | Every page built (Next.js 16 + shadcn/ui) and wired to the API (Phase 2). Sample data only in demo builds; live builds show an error or empty state when the API fails (§8). |
| P2 API design | Done (FastAPI core API + partner API, webhooks, Celery pipeline). |
| P3 Backend + database | Done (PostgreSQL + pgvector, auth, weighted CCS, audit log). |
| P4 AI engine | Built (Groq + Tavily verdict engine, multilingual embeddings, local-evidence RAG, Sunbird, Whisper, local signals). FR-DETECT-03's ≥90% accuracy is **unverified** — see §8 and [Appendix F](#appendix-f--ai-evaluation-results-fr-detect-03). |
| **Phase 1 of the completion plan: Supabase migration** | **Mostly done.** Database live on Supabase, RLS lockdown, Supabase Auth working end to end behind a switch (email sign-up with code, sign-in, Expert/Admin second factor), Brevo email, uptime monitor. Storage and Realtime not migrated yet. |
| Phase 2: frontend-to-API wiring | **Done (28 Oct).** Submission flow done (28 Oct): the composers post to `POST /submissions` (JSON, or multipart with real upload progress for media; idempotency key per attempt), and the Status page follows the real pipeline over the API's server-sent events, polling the status if the stream drops, then opens the real report. Demo builds keep the simulated flow. **All 8 admin screens wired** (28 Oct; `lib/admin-api.ts`, shared `useAdminData` hook and `Pager`): Overview, Users (server-side search/filters/paging), Moderation, Sources, Broadcasts, Audit log (action filter + paging server-side), Settings, Reports. Actions the API doesn't have yet are hidden live and kept in demo builds: "send to review" and manipulation-signal actions (Moderation), source re-crawl, WhatsApp broadcasts. **Account screens wired** (28 Oct; `lib/account-api.ts`, shared `hooks/use-live-data.ts`): Profile (details, password, two-factor, devices, data export, account erasure), Activity, Notifications (bell + page), API keys, Alerts, and the journalist verification application (feeds Admin → Verifications). With Supabase sign-in, passwords change in Supabase (current password re-checked first) and the email address isn't edited here. Not in the API yet, so local or demo-only: marking a notification unread or deleting it, alert delivery frequency, withdrawing a verification application, and the application's job title / work email / links fields. Erasing an account anonymises the Zuula account but leaves its Supabase login (deleting that needs the service-role key server-side). **Phase 2's wiring is done**, and a signed-in click-through as Admin (28 Oct) checked every admin, account and review screen against production data through the local API; what it fixed is in §8. |
| Hardening + launch | Not started. |

### Work landed on 27–28 October 2026 (all pushed to GitHub `main` on 28 Oct; Phase 2 and the security upgrade followed, last commit `a644d70`)

| Commit | What |
|---|---|
| `59701c1` | Jason's OpenCode agent; API in `.claude/launch.json`; `app plan/` git-ignored (it holds plaintext credentials). |
| `dbb0d79` | Supabase Auth groundwork: token verifier (JWKS/ES256 and HS256), settings, web client. Fixed an account-takeover bug and an ES256 gap in the first draft. |
| `8a72c0d` | Migration 0005: RLS on every table, all table/sequence grants revoked from `anon`/`authenticated` (applied to production). |
| `ee9335e` | Migration 0006: `users.supabase_user_id` links an account to its Supabase user (applied). |
| `5564d05` | API accepts Supabase access tokens behind `ZUULA_AUTH_PROVIDER`. |
| `7b53deb` | Web app Supabase sign-in mode (`NEXT_PUBLIC_AUTH_MODE=supabase`), `/auth/callback`. |
| `f168ab0` | Supabase email templates with the 6-digit code (drafted by Jason, reviewed). |
| `a153c36` | Migration 0007: deleting a Supabase user unlinks its Zuula account (applied). |
| `98fbee1` | Sign-up says "already has an account" instead of waiting for a code that never comes. |
| `82d1044` | Expert/Admin second sign-in step for Supabase mode (FR-AUTH-05). |
| `bf52c33` | API tests pinned to the test database, never the one in `apps/api/.env`. |

## 3. Architecture

**Supabase-first hybrid**: Supabase provides the database and identity; FastAPI keeps all business logic.

```
Next.js 16 web app (Vercel)
   │  Supabase Auth (supabase-js) for sign-in;  every data call → FastAPI with the Supabase token
   ▼
FastAPI (Render/Fly.io)            Celery worker (Redis broker, Upstash planned)
   │  business rules, CCS, review,     submission pipeline, AI analysis,
   │  admin, partner API, webhooks,    email (Brevo) / SMS (Africa's Talking)
   │  audit log, AI pipeline
   ▼
Supabase: PostgreSQL 17 + pgvector + pg_trgm · Auth · Storage · Realtime
```

- **All data goes through FastAPI.** It connects as the table owner, so RLS (deny-all) doesn't apply to it. The browser never reads tables directly.
- **Roles live in the `users` table**, never in tokens.
- **Live updates** (submission status, notifications, home feed) will use Realtime *Broadcast* sent by the API, not `postgres_changes` — that would need table grants and would open a second, unmetered read path around the partner API.
- The AI engine runs inside `apps/api` (`app/providers/`), real-or-stub per provider. Details in [Appendix A](#appendix-a--zuula-api) and the ADRs.

## 4. Supabase: what is set up

**Project:** `zuula-production`, ref `xskkttjlgkanopzivfpy`, West EU (Ireland), Free plan, organisation "Zuula". Secrets (database password, JWT secret, service-role and `sb_secret_` keys, Brevo SMTP key) live only in `apps/api/.env`, `apps/web/.env.local` and Noah's password manager — **never in this document or in git.** They were shared through chat and planning notes during setup, so **rotate them before launch.**

| Setting | Value |
|---|---|
| Database | Alembic migrations `0001`–`0008` applied (25 tables). pgvector 0.8.2, pg_trgm 1.6. Sample data seeded. |
| RLS | On for every table, no policies; `anon`/`authenticated` hold no grants (migration 0005). |
| Realtime | `supabase_realtime` publication has `submissions`, `notifications`, `fact_check_reports` (no effect until Broadcast is wired, see §3). |
| Storage | Buckets `zuula-media` (public) and `zuula-documents` (private) exist; the API still uses its own S3 settings. |
| Auth → Email | Sign-ups on; **Confirm email** on; **Secure email change** on; **minimum password 12**; **email code length 6**, expiry 3600 s. |
| Auth → SMTP | Custom SMTP via **Brevo**: `smtp-relay.brevo.com:587`, sender **Zuula &lt;zuulaug@gmail.com&gt;** (verified in Brevo; a Gmail sender may land in spam until a `zuula.ug` domain is authenticated). |
| Auth → Templates | "Confirm sign up" and "Reset password" use `docs/supabase/email-templates/` (code + link). |
| Auth → URLs | Site URL `http://localhost:3000`; redirect URLs `http://localhost:3000/**` (add production URLs at deploy). |
| Auth → Providers | Email only. Google, Facebook and phone (needs an SMS provider) are off. |
| JWT signing | ES256 signing keys (JWKS at `/auth/v1/.well-known/jwks.json`); the legacy HS256 secret is still accepted. |
| Database trigger | `unlink_zuula_account` on `auth.users` delete (migration 0007). |

**Monitoring:** UptimeRobot monitor "Zuula Supabase" (5-minute HTTP check of `https://xskkttjlgkanopzivfpy.supabase.co/storage/v1/version`; Supabase's health endpoint rejects UptimeRobot's free-plan HEAD requests). It confirms Supabase is reachable, not that the database is; a daily GitHub Action running a real query would also guard against the free tier pausing.

**Brevo:** the API's own emails (2FA codes, alerts) use the same Brevo account through `EMAIL_SMTP_*` in `apps/api/.env`, sending as `zuulaug@gmail.com`.

## 5. Sign-in: three modes

`NEXT_PUBLIC_AUTH_MODE` (web) picks how people sign in; `ZUULA_AUTH_PROVIDER` (API) must match for Supabase.

| Mode | How | Where |
|---|---|---|
| `api` (default with an API URL) | Zuula's own auth: bcrypt passwords, HttpOnly `zuula_session` cookie, email/SMS codes. | `lib/api.ts`, `app/core/security.py` |
| `demo` (default without an API URL) | Browser-only demo: any password, role from the address. Grants nothing. | `lib/demo-auth.ts` |
| `supabase` (only when set) | Supabase Auth; the API accepts its access tokens. | `lib/supabase-auth.ts`, `app/core/supabase_auth.py` |

**How Supabase mode works**

1. **Sign-up:** Supabase sends the 6-digit code (Brevo), the form verifies it, and the API creates a **Public User** on first contact and links it by `supabase_user_id`. An address that already has an account gets "An account with that email or phone number already exists."
2. **Account linking:** by `supabase_user_id`; on an existing account's first Supabase sign-in, by its confirmed email (else phone). An account already linked to another Supabase user is never re-linked. Deleting a Supabase user unlinks the account (trigger), so signing up again re-links it. Roles never come from the token.
3. **Second factor (FR-AUTH-05, as specified):** after the password step the web app calls `POST /api/v1/auth/supabase/second-factor`. Expert Reviewers, Admins and opted-in users get the API's own 6-digit code by email/SMS, tied to that Supabase session; the existing `/sign-in/two-factor` screen completes it. Until then their tokens count as signed out. Passing it creates a `sessions` row (key: an HMAC of the Supabase session id), so sign-out, revocation and `/me/sessions` work as before.
4. **Forgot password:** Supabase emails a 6-digit code ("Reset your Zuula password"); the reset screen takes email + code + new password, then signs out. Email errors from Supabase are shown (it answers unknown emails like known ones, so nothing leaks); for phones only rate limits are shown. Supabase records each send in `auth.users.recovery_sent_at`, handy for checking whether an email went out.
5. **Google/Facebook** go through Supabase OAuth and come back to `/auth/callback` (needs the providers enabled first).

Verified end to end on 27 Oct 2026: sign-up with the emailed code, account created and linked, `/api/v1/me` authenticated. The Expert second factor is covered by contract tests; a live run needs Redis + the worker locally (§6).

**Who can change what:** users edit their own name, language, district, password, two-factor opt-in and devices, can export or delete their data, and can apply for Journalist/Expert verification (`/me/verification`). Only admins change roles and statuses (Admin → Users, audited; admins can't change their own). **Admin → Verifications** (merged 28 Oct 2026 from `claude/competent-taussig-0c616a`, reviewed): the queue of Journalist/Expert applications, each with the applicant's details and 10-minute signed links to their documents (virus-scanned before download; links work without a session). Approve gives the requested role; reject needs a note the applicant sees. Both are audited (`accreditation.approve` / `accreditation.reject`) and the applicant is notified in-app and by email. Applicants choose the role they apply for (`role` = journalist or expert) on `/me/verification`. Database change: migration **0008** (`requested_role` column, new audit actions), applied to production 28 Oct 2026.

**How admin accounts are created:** every account starts as a Public User. The first Admin has to be set directly in the database, as done for `noahprinzy@gmail.com` on 28 Oct 2026 (audited); after that, Admins promote others through Admin → Users. Journalists and Experts apply through verification and are approved by an Admin. Admin sign-in was verified end to end on 28 Oct 2026: password, then the emailed second-step code, then the Admin area.

**Future idea (Noah, 28 Oct 2026; not planned yet):** let people choose the role they're registering for at sign-up (Journalist, Expert, Admin). The account stays pending until checks pass: a series of confirmation steps where they submit details verified against official Ugandan documents as the source of truth. Builds on the verification flow and admin review queue.

## 6. Running it locally

```bash
# API (Windows: .venv\Scripts\activate)
cd apps/api && .venv/Scripts/activate
python scripts/quick_test.py            # Supabase connection check
uvicorn app.main:app --reload           # http://localhost:8000
celery -A app.worker.celery_app worker --loglevel=INFO   # needs Redis

# Web
cd apps/web && npm run dev              # http://localhost:3000 — must be 3000 (CORS + Supabase redirect)
```

- `.claude/launch.json` has `web` and `api` configurations.
- Port 3000 is often taken by Noah's portfolio site (`D:\Noah\Desktop\My_Portfolio`); stop it first, or add `:3001` to `ZUULA_CORS_ORIGINS` and Supabase's redirect URLs.
- **Redis and the worker (set up 28 Oct 2026):** Redis runs in Docker as `zuula-redis` (`docker run -d --name zuula-redis --restart unless-stopped -p 6379:6379 redis:7-alpine`; Docker Desktop must be running). The API and worker use their built-in `localhost:6379` defaults; the `redis://redis:6379` values in `.env` are for Docker Compose and aren't read locally. The worker needs `--pool=solo` on Windows, and the `EMAIL_*` values from `.env` in its environment, so code emails go out through Brevo instead of only being logged:
  ```bash
  cd apps/api && set -a && eval "$(grep -E '^EMAIL_[A-Z_]+=' .env | tr -d '\r' | sed -E "s/^([A-Z_]+)=(.*)$/\1='\2'/")" && set +a
  .venv/Scripts/python.exe -m celery -A app.worker.celery_app worker --pool=solo --loglevel=INFO
  ```
- `apps/api/.env`'s `DATABASE_URL` now uses the IPv4 session pooler (the direct IPv6 line is kept as a comment above it).
- **Tests never touch production.** `apps/api/.env` points at Supabase production; tests pin `DATABASE_URL` to `TEST_DATABASE_URL`. Use a throwaway database:
  ```bash
  docker run -d --rm --name zuula-test-db -e POSTGRES_USER=zuula -e POSTGRES_PASSWORD=zuula -e POSTGRES_DB=zuula -p 55433:5432 pgvector/pgvector:pg17
  export TEST_DATABASE_URL=postgresql+asyncpg://zuula:zuula@localhost:55433/zuula_test
  pytest tests -q
  ```
- Local env files are currently in Supabase mode (`ZUULA_AUTH_PROVIDER=supabase`, `NEXT_PUBLIC_AUTH_MODE=supabase`); set both back to `legacy`/unset for the original sign-in.
- Never run `alembic upgrade` against production without Noah's go-ahead.
- **IPv6:** `db.xskkttjlgkanopzivfpy.supabase.co` (the direct connection in `DATABASE_URL`) is IPv6-only. On a network without IPv6, connections fail with `getaddrinfo failed`; use Supabase's IPv4 session pooler instead: host `aws-0-eu-west-1.pooler.supabase.com`, port 5432, user `postgres.xskkttjlgkanopzivfpy`, same password. Hosting on Render/Fly.io will likely need the pooler too.

## 7. Security decisions

- **RLS deny-all plus no grants** for Supabase's API roles: the publishable key can't read or write any table (checked: `/rest/v1/*` returns 401).
- **Supabase tokens:** verified against JWKS (ES256) or the legacy secret, with issuer, audience and expiry checked; `none` and unconfigured secrets refused; bearer header only.
- **Account linking** never trusts `user_metadata` (users can write it) and never re-links an account that belongs to another Supabase user.
- **Second-factor session keys** are HMACs under `ZUULA_SECRET_KEY`, so they can't be replayed as legacy session tokens.
- The unlink trigger function is `SECURITY DEFINER` with an empty `search_path`, and nobody else can execute it.
- `app plan/` is git-ignored: it held plaintext credentials. Credentials must be rotated before launch.

## 8. What's left

**GitHub `main` vs local `main`:** synced 28 Oct 2026 by merging GitHub `main` into local `main` (PR #70's follow-up fix and Dependabot #66–#69). GitHub's `0005_accreditation_review` doesn't exist locally (it's `0008`, applied to production); `alembic heads` shows the single head `0008`. Everything was pushed on 28 Oct 2026; local and GitHub `main` match (`a644d70`), and Vercel deployed it. Every push to `main` deploys the web app. **Never apply a `0005_accreditation_review` migration to production.**

**Fixed 28 Oct 2026 (`52e99a0`): no silent fallback to sample reports.** Home, the Library, report pages, Verify and the Review screens used to show the fictional `lib/mock/` reports whenever an API call failed, so an outage would have passed invented fact-checks off as real ones. Sample data is now for demo builds only (no `NEXT_PUBLIC_API_URL`). Live: the Library and report pages go to the error page with Retry; Home's two cards say "Fact-checks can't be loaded right now" (or "No fact-checks published yet" when the API has none); Verify hides its leaderboard; Review screens start empty and show a "Couldn't load this data" toast; an unknown review case is "not found", never a sample case. Checked in the browser by stopping the local API. Tests: `components/review/review-live.test.tsx`, `app/[locale]/(public)/public-live.test.ts`. The two new Home strings are in English in all five locale files, pending the translation review.

**Signed-in click-through (28 Oct 2026, as Admin, Supabase sign-in, production data via the local API).** Every admin, account and review screen was opened; nothing was changed in production. Fixed:
- *Real review cases and reports 404'd* (`297a243`). Report and case pages listed their ids at build time, and with the `[locale]` layout's `dynamicParams = false` every other id was a 404: every case the API creates, and every report published after a build (or all of them if the API was unreachable while building). Both now render on request; unknown reports 404, unknown cases say "Case not found". This also removes the build-order risk for Milestone B.
- *Admin → Verifications showed the sample applications* under Supabase sign-in (it only treated `api` mode as live), and *Admin → Users' "N pending · N suspended"* counted only the 50 users on screen; `GET /admin/users` now returns platform-wide `counts` (`fa3202b`, contract + shared types updated).
- *Broadcasts* offered regions and topics with a hardcoded "About 52,000 people", though the API sends every broadcast to every active account; and its "link a fact-check" list was sample reports, never sent. Live: audience "Everyone", the real reach in the toast, no link field (`2666819`). Regional targeting is Phase 4.
- *Account*: "Password last changed 3 months ago" was a fixed string; Alerts offered WhatsApp/Telegram (a simulated connect) and a delivery frequency the API doesn't store. All demo-only now (`9d15053`).
- *Review* screens showed zeros while loading (over 8 s against the remote database), which read as an empty queue; they show a placeholder now (`297a243`).
- *Sign-in crash* when Chrome autofills a password: the "D" theme shortcut read `event.key` of a keydown that has none (`e481523`).

Still sample data in production (goes with the Milestone E reset): the overview's "Text detection F1 91.4%" and "Deepfake accuracy 83.1%" are seeded `model_evaluations` rows, not a real evaluation; moderation reports, review cases rc-0414–0418, source crawl times and the one accreditation application are seeded too. Noah's Admin account is named "admin" (from sign-up); he can rename it under Account → Profile. The local API runs without auto-reload: restart it after API changes.

**Launch blocker: production holds only sample data.** The production database was seeded with `python -m app.db.seed` *without* `--real`. Audit of 28 Oct 2026 (read-only):

| What | In production | Notes |
|---|---|---|
| Named sample accounts `u1`–`u9` | 9 | Their password `zuula-sample-password` is public. **Locked 28 Oct 2026:** all suspended, passwords removed, 3 sessions and 2 API keys revoked, one `user.suspend` audit entry each. (Were: 1 Admin, 2 Experts, 2 Journalists, 4 Public.) |
| Sample raters | 430 | No password; can't sign in. |
| Real accounts (Supabase-linked) | 3 | Noah's: `noahprinzy@gmail.com` (Admin), `noahdevsug@gmail.com` and `noahwebalemukama@gmail.com` (Public). |
| Fact-check reports | 12 | **All fictional** (`fc-2026-*`). The 363 AFP fact-checks and 11 Uganda claims were never loaded. |
| Ratings / comments / submissions / review cases | 2,042 / 5 / 13 / 9 | Sample. |
| Sessions / API keys | 3 / 2 | Seeded with random hashes; unusable. |
| Notifications / audit entries / broadcasts / accreditation applications | 6 / 10 / 2 / 1 | Sample. |
| Trusted sources | 12 | Real registry; keep. |

**Production's Admin:** after the lock, Noah's Supabase-linked account **noahprinzy@gmail.com** (`usr_41ed27efa0095765`) was made Admin directly in the database (audited `user.role_change`, 28 Oct 2026). It's the only active Admin; further role changes go through Admin → Users. As an Admin it needs the second sign-in step, so signing in to Supabase mode needs Redis and the worker running for the code email.

Remaining fix, before launch: back up the database, then reset it to real content only (no sample users, ratings or reports; AFP + Uganda fact-checks and trusted sources loaded). The seed script needs a real-content-only mode for that, since `--real` still adds the fictional set. Supabase's free plan has no backups, so take a `pg_dump` first.

**Before Supabase sign-in can be the production default**
- Google and Facebook providers (Google Cloud and Meta apps; redirect URI `https://xskkttjlgkanopzivfpy.supabase.co/auth/v1/callback`).
- Phone sign-in needs an SMS provider in Supabase (Africa's Talking isn't built in).
- A `zuula.ug` sending domain in Brevo (DKIM/DMARC) so emails stop landing in spam.
- Live test of the Expert second factor (Redis + worker locally).
- Production URLs in Supabase's Site URL / redirect list; rotate all credentials.
- Then delete the legacy auth code (~2,000 lines).

**Rest of Phase 1 (Supabase)**
- Storage: point the API's S3 settings at Supabase Storage; bucket policies.
- Realtime: API sends Broadcast messages; web subscribes (replaces Redis pub/sub + SSE).
- Upstash Redis for Celery; Cloudflare (DNS, CDN, Turnstile); local AI providers on.

**Phase 2 onwards** — see §9: wire admin, account and submission screens to the API; AI SDK fallback chain and a trustworthy FR-DETECT-03 run with dedicated keys; missing features; deployment; translations, accessibility, performance, tests.

**Security updates (28 Oct 2026):** Next.js 16.3.8 → 16.4.1 (fixes two critical unauthenticated remote-code-execution flaws and a high denial-of-service flaw), eslint-config-next 16.4.1, vitest/@vitest/mocker 4.1.12, ip-address 10.7.5. Still open: `deepmerge` 4.3.1 (low severity, transitive; no fixed version exists yet). Check GitHub's Dependabot alerts after each dependency change; production runs whatever `main` holds.

**Housekeeping**
- Done 28 Oct 2026: seed and eval data files are read as UTF-8 (`6ca9507`), so all 489 API tests pass on Windows without `PYTHONUTF8`; the unused setup leftovers `apps/web/lib/supabase-api.ts` and `apps/api/scripts/test_supabase_connection.py` were deleted (never committed).
- Restart the web dev server after any `npm install` that changes Next.js: a server left running across the 16.4.1 upgrade served only 500s (Turbopack "module not found") until it was restarted with `.next/dev` cleared.
- `scripts/run_eval.py` still writes its report to `apps/api/EVAL_RESULTS.md`; fold new results into Appendix F.

**Open questions for the supervisor** are listed in [Appendix B](#appendix-b--zuula-web-app) ("Changes from the specification").

## 9. The completion plan (cost-free stack)

Agreed 27 Oct 2026: finish Zuula on free tiers only (domain the one possible cost, about $10/year), in six phases over 6–8 weeks.

| Phase | Scope | Status |
|---|---|---|
| 1. Supabase migration (wk 1–2) | Database, Auth, Storage, Realtime, RLS; keep Redis only for Celery; local AI providers; Cloudflare, Brevo, UptimeRobot | Database, Auth, RLS, Brevo, UptimeRobot done; Storage, Realtime, Upstash, Cloudflare pending |
| 2. Frontend-to-API wiring (wk 2–3) | Replace all mock data: home, library, report, submission (+ live status), all admin screens, all account screens | Wiring done 28 Oct; sample-data fallback removed from live builds; signed-in click-through done (§8) |
| 3. AI engine upgrades (wk 3–4) | Vercel AI SDK with Groq → Gemini → OpenRouter fallback, Gemini grounding search, all local signals on, FR-DETECT-03 re-run with dedicated keys, trusted sources 12 → 50 | Not started |
| 4. Missing features (wk 4–5) | Push notifications (FCM/OneSignal), WhatsApp/Telegram media (Groq Whisper), webhook dedupe, regional broadcast targeting, virus-scanned accreditation documents | Not started |
| 5. Production deployment (wk 5–6) | Cloudflare, API + worker on Render/Fly.io, Upstash, Vercel, Brevo SMTP, Turnstile, monitoring, end-to-end test | Not started |
| 6. Quality and polish (wk 6–7) | Native-speaker translation review (lg, ach, nyn, teo), WCAG 2.1 AA, Lighthouse ≥ 80, Vitest/Playwright/contract tests | Not started |

**Free stack:** Supabase (Postgres + pgvector 500 MB, Auth 50K MAU, Storage 1 GB, Realtime 200 connections), Vercel (web), Render/Fly.io (API + worker), Upstash Redis (256 MB, Celery broker), Cloudflare (CDN, DNS, Turnstile), Brevo (300 emails/day), Africa's Talking (SMS sandbox), UptimeRobot, Groq (primary LLM + Whisper), Google Gemini and OpenRouter (fallback LLMs), Tavily (1,000 searches/month), Sunbird AI (Ugandan languages), Hugging Face and local models (sentence-transformers, RoBERTa, EXIF, image classifier).

**Supabase migration risks:** the free tier pauses after a week without activity (mitigation: monitor plus a real daily query); limits of 50K MAU, 500 MB database, 1 GB storage and 200 Realtime connections are enough for launch (Pro is $25/month).

## 10. Design resources

Current design system: shadcn preset `b20twYRDfO`; brand colours Crimson `#C70036`, Ink `#0B0F11`, Blush `#FFF1F2`; type Raleway (headings), Geist (body), Lora (serif), Geist Mono. For a later UI-upgrade phase, after the backend:

- **Inspiration:** [Godly](https://godly.design), [Inspora](https://inspora.design), [SiteReel](https://sitereel.ai), [Layers](https://layers.to), [Mobbin](https://mobbin.com), [Figma Community](https://www.figma.com/community)
- **Component libraries:** [shadcn/ui](https://ui.shadcn.com), [Watermelon UI](https://ui.watermelon.sh), [Componentry](https://componentry.dev), [Skiper UI](https://skiper-ui.com), [Amicro](https://amicro.vercel.app), [Bencho](https://bencho.dev), [Hero UI](https://heroui.com), [Aceternity UI](https://ui.aceternity.com), [Smooth UI](https://smoothui.dev), [Cult UI](https://cult-ui.com), [Hyper UI](https://hyperui.dev), [Preline UI](https://preline.co), [PrebuiltUI](https://prebuiltui.com)
- **Templates:** [React JS Templates](https://reactjstemplates.com), [HTML5 UP](https://html5up.net), [FreeHTML5.co](https://freehtml5.co), [Astro](https://astro.build)
- **Colours and backgrounds:** [Realtime Colors](https://realtimecolors.com), [Coolors](https://coolors.co), [Shader Gradient](https://shadergradient.co), [Mesh Gradient](https://meshgradient.com), [Pattern Monster](https://pattern.monster), [Haikei](https://haikei.app), [Vanta JS](https://vantajs.com)
- **3D and animation:** [Spline](https://spline.design), [Vectary](https://vectary.com), [Unicorn Studio](https://unicorn.studio), [Theatre JS](https://theatrejs.com), [GSAP](https://gsap.com), [Motion](https://motion.dev), [Barba JS](https://barba.js.org), [SVGator](https://svgator.com)
- **Icons and fonts:** [Lucide](https://lucide.dev), [Phosphor Icons](https://phosphoricons.com), [Iconify](https://iconify.design), [Heroicons](https://heroicons.com), [Fontshare](https://fontshare.com), [Bunny Fonts](https://fonts.bunny.net)
- **AI builders:** [Manus](https://manus.im)

## 11. Next steps: plan to launch (28 Oct 2026)

About 4½ weeks to the 30 November deadline. The §9 phases are reordered so the riskiest work, a hosted API, happens early rather than in week 5. Production today is the Vercel web app in demo mode with no hosted API. Each milestone ends green (`tsc`, vitest, pytest), committed, with this document updated.

| # | Milestone | Work | Done when | Size |
|---|---|---|---|---|
| A | **Close Phase 2** | (1) Live builds stop falling back to sample reports: show an error or empty state; sample data only in demo builds. (2) Signed-in click-through of every wired screen as Admin, and as a Public user. (3) Housekeeping: delete the two untracked leftovers, `encoding="utf-8"` for the 9 Windows-only seed tests. | No `lib/mock` data is reachable in a live build; every screen checked against the local API. | **Done 28 Oct** |
| B | **Host the API early** (Phase 5 brought forward) | API + Celery worker on Render (free), Upstash Redis, Supabase IPv4 pooler, `ZUULA_CORS_ORIGINS` and Supabase redirect URLs for the Vercel domain, Vercel `NEXT_PUBLIC_API_URL` + `NEXT_PUBLIC_AUTH_MODE=supabase`. Follows [Appendix E](#appendix-e--deploying-the-api-to-render). | The Vercel site signs in and submits against the hosted API. | **Done 28 Oct** (preview; production switches after E) |
| C | **Storage** (rest of Phase 1) — **Done 29 Oct** | Supabase Storage confirmed by Noah on 28 Oct over Cloudflare R2 (R2: 10 GB and free egress, vs 1 GB here; revisit if media outgrows it). API's S3 settings → Supabase Storage (S3-compatible); `zuula-documents` stays private with signed links. Realtime Broadcast is deferred: the SSE + polling status page already works. | Uploads and verification documents land in Supabase Storage. | 1 day |
| D | **AI engine** (Phase 3) | Groq → Gemini → OpenRouter fallback chain, in Python inside `apps/api/app/providers/` (the engine lives in FastAPI, so the Vercel AI SDK doesn't fit); trusted sources 12 → 50; FR-DETECT-03 re-run with dedicated keys, results into Appendix F. | A provider outage doesn't fail a check; accuracy measured honestly. | 4–5 days |
| E | **Production data reset** | `pg_dump` backup, real-content-only seed mode, reset production (AFP + Uganda fact-checks, trusted sources, Noah's accounts kept). Needs Noah's go-ahead. | Production holds no sample data. | 1 day |
| F | **Missing features** (Phase 4, by priority) | Webhook dedupe; regional broadcast targeting; WhatsApp/Telegram media via Groq Whisper; push notifications last, cut if time runs out. | Agreed subset shipped. | 4–5 days |
| G | **Hardening and launch** (Phase 6 + remaining Phase 5) | Cloudflare DNS + Turnstile, `zuula.ug` sending domain in Brevo, Google/Facebook sign-in, credential rotation, delete legacy auth, WCAG 2.1 AA and Lighthouse ≥ 80 passes, Playwright smoke tests, native-speaker translation review (needs reviewers Noah arranges). | Launch checklist signed off by Noah. | 5–6 days |

### Milestone B in detail: hosting the API (planned 28 Oct 2026)

[Appendix E](#appendix-e--deploying-the-api-to-render) predates the Supabase move; this replaces its plan. Facts checked on 28 Oct 2026:

- **Render free web services** sleep after 15 minutes idle, have 512 MB RAM and 750 instance-hours a month (enough for one service around the clock), and since Sept 2025 **block outbound SMTP (25/465/587)**, so Brevo SMTP won't work there. **Background workers have no free tier** (Starter about $7/month each); pre-deploy commands are paid too.
- **Upstash free**: one database (no Redis DB indexes 0/1/2), 256 MB, **500K commands a month**. An idle Celery worker polls Redis constantly and can use that up on its own.
- **Brevo's HTTP API** is on the free plan (300 emails/day), so emails can go over HTTPS instead of SMTP.
- The Docker image installs `sentence-transformers`, which pulls in PyTorch (the multi-GB CUDA build by default) and won't fit 512 MB at runtime once the local models are switched on.

**Options**

| | How | Cost | Catch |
|---|---|---|---|
| **1. Render free, one process** (recommended) | API on one free Render web service (Frankfurt, nearest to Supabase in Ireland). Background jobs run inside the API process instead of a Celery worker; Redis (Upstash free) only for live status and sign-in lockout. Email over Brevo's HTTP API. An UptimeRobot check on `/healthz` every 5 min keeps it awake within the 750 hours. | $0 | 512 MB: local AI models stay off (stub or hosted APIs); one instance only; jobs in flight are lost if the service restarts. |
| 2. Render paid | API + Celery worker as in Appendix E, Upstash Redis. | ≈ $14/month (+ Upstash pay-as-you-go if Celery's polling passes 500K commands) | Costs money; otherwise the closest to today's code. |
| 3. Oracle Cloud Always Free VM | The whole Docker Compose stack (API, worker, Redis) on a free ARM VM. | $0 | Card required, ARM capacity often unavailable, and we'd run the server ourselves (TLS, updates, restarts). |

**Steps (option 1)**
1. Email over Brevo's HTTP API (`EMAIL_PROVIDER`); SMTP stays for local use.
2. An in-process job mode for `app/worker/dispatch.py` (the four `.delay()` calls), switched by a setting; Celery stays the default locally.
3. One Redis URL: no DB-index separation, keys already distinct.
4. A slimmer image: local-model packages become an optional extra; CPU-only PyTorch when they're installed.
5. `render.yaml` Blueprint (shown to Noah before use); production env var list (names only) in this document.
6. Noah: create the Render and Upstash accounts and paste secrets into their dashboards (Milka never enters keys or passwords into web forms); approve Supabase's Site URL and redirect list for the Vercel domain.
7. Deploy and verify: `/healthz`, sign-in with the second step (email arrives), a submission through the pipeline, CORS, and which client IP the API sees behind Vercel.
8. Vercel: point a **Preview** deployment at the API first. Switch **Production** only after Milestone E, so the public site never shows the sample data as real.

No database migration is involved: production is already at `0008`.

**Progress (28 Oct 2026, option 1 chosen by Noah).** Code done (`59fed8a`): `JOB_RUNNER=inline` (jobs, email/SMS retries and the 5-minute brigading check run inside the API), the Brevo HTTPS email sender (`BREVO_API_KEY`, preferred over SMTP), the local-model packages as an optional `ml` extra (`INSTALL_ML=true` in the Dockerfile, CPU-only PyTorch), and `render.yaml`. The image is 550 MB and used about 93 MB of memory running in production mode locally (`/healthz`, `/readyz` with database and Redis both ok). All 498 API tests pass.

**Found on Render (Noah's workspace):** an older `zuula-api` web service (free, **Ohio**, `https://zuula-api.onrender.com`) and a free `zuula-redis` Key Value, both from an earlier session. That API auto-deploys every push to `main` and runs `alembic upgrade head` before each deploy, but its database is **not** production Supabase (it has 0 fact-checks). Ohio is also the wrong side of the Atlantic for a database in Ireland. So `render.yaml` creates a new API in **Frankfurt**, `zuula-api-eu`. Redis is **Upstash's free plan** (Frankfurt, TLS): the first Blueprint sync failed because Render allows one free Key Value per workspace and the Ohio `zuula-redis` holds it, and Noah chose Upstash over deleting the Ohio pair. Once the new API works, Noah should suspend or delete the Ohio pair; until then, every push also redeploys it.

**Production env vars** are the ones in `render.yaml`. Secrets Noah enters when applying the Blueprint: `DATABASE_URL` (the Supabase IPv4 session pooler, `postgresql+asyncpg://`), `REDIS_URL` (Upstash, `rediss://`), `SUPABASE_JWT_SECRET`, `BREVO_API_KEY`, `GROQ_API_KEY`, `TAVILY_API_KEY`, `SUNBIRD_API_KEY`, `ZUULA_CORS_ORIGINS` and `ZUULA_WEB_APP_URL` (the Vercel URLs). `ZUULA_SECRET_KEY` is generated by Render.

**Live (28 Oct 2026): `https://zuula-api-eu.onrender.com`** (free, Frankfurt, Blueprint "zuula"). `/readyz` reports app, database and Redis ok; it reads production Supabase (the fact-checks come back), `/api/v1/me` is 401 signed out, the home feed answers in about 0.75 s, and CORS allows `https://zuula.vercel.app`. Upstash database: `Zuula` (`flowing-crow-242290`, Frankfurt, free). Getting there: the Supabase pooler needs the user `postgres.xskkttjlgkanopzivfpy` (plain `postgres` is refused), and `REDIS_URL` must be the **TCP** tab's `rediss://` URL with the Redis password: Upstash's REST token is a different credential. The REST token was shared in chat during setup, so Noah reset the Upstash credentials. `/readyz` now logs why a check fails (error type and message, no URLs).

**Vercel preview, verified end to end (28 Oct 2026): `https://zuula-git-api-preview-victoriauniversity.vercel.app`** (branch `api-preview`, kept equal to `main`). Its four variables are scoped to that branch only, so production is unchanged: `NEXT_PUBLIC_API_URL=https://zuula-api-eu.onrender.com` (direct, no proxy: with Supabase sign-in the browser sends a bearer token, and `NEXT_PUBLIC_API_URL=/` would break the server-rendered pages, which can't fetch a relative URL), `NEXT_PUBLIC_AUTH_MODE=supabase`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` (type Config: Vercel won't store a `NEXT_PUBLIC_` value as Secret). Supabase's redirect list now has `https://zuula-git-api-preview-victoriauniversity.vercel.app/**` besides localhost. Checked: Home shows production fact-checks through the API; Noah signed in as Admin and the second-step code arrived by Brevo; the Admin area loads; a text submission (`ZL-3YCK-FB`) ran through the inline pipeline with live progress and produced report `fc-2026-0165` (Groq verdict, 11.6 s), whose page opened although it didn't exist at build time.

Fixed on the way:
- *Builds no longer depend on the API* (`31c2d91`): Home, Library and Verify were prerendered at build time, which froze their data and, with no sample fallback, failed the Vercel build when the sleeping free instance didn't answer. They call `connection()` and render per request in live builds; demo builds stay static.
- *Sign-in codes weren't sent*: Brevo answered 401 "Key not found" to Render's first `BREVO_API_KEY`. Noah made a new restricted key (Transactional email: All, Account: Read). `/readyz` now checks the key against Brevo every 10 minutes and reports `email: unavailable` (`92bb461`).
- *Real reports were labelled "sample"* (`cb05a42`): the notice showed on every id not starting `fc-real-`; it now uses the known seed ids.

**Sunbird and Tavily fixed (28 Oct 2026, late).** Both keys had failed everywhere, local too: Sunbird answered 401 (the token wasn't expired, valid to 2126, but carries a version claim, so it had most likely been revoked by generating a newer one) and Tavily answered 432 (the free plan's monthly quota was used up). Noah made new keys and set them locally and on Render. Checked: locally Sunbird identifies a Luganda sentence as `lg` and Tavily returns results; on the preview a Luganda test claim (`ZL-S55V-LH`) came back as report `fc-2026-0166` with language **Luganda**, an English title, and no Tavily error in the logs (no sources cited, as expected for an invented claim). It took **97 s**, against the "about 10 seconds" the status page promises; Sunbird translation is the slow step, a Milestone D item. Also for D: these failures were silent (only thinner reports); the Admin "System health" card should show Groq, Sunbird and Tavily status, and search should fall back to a second provider when Tavily's quota runs out.

### Milestone C in detail: file storage on Supabase Storage (29 Oct 2026)

The API's storage adapter (`app/adapters/storage.py`) already spoke S3, so C is mostly settings. What the API stores, and who reads it: media submissions (`submissions/<id>/original`, read by the pipeline's malware scan and metadata check; only an infected file is deleted, clean uploads are kept) and accreditation documents (`accreditation/<user>/<application>/<n>`, read only by the API when an admin opens a signed link). Nothing is ever served straight from the bucket, so **both go in the private bucket `zuula-documents`**; the public `zuula-media` bucket stays unused for now (it's for public assets later, such as report images).

Code (tests: 502 passed):
- Path-style addressing whenever `S3_ENDPOINT_URL` is set: Supabase serves buckets as `…/storage/v1/s3/<bucket>`, not as subdomains.
- `/readyz` checks the bucket (`HeadBucket`) every 10 minutes, as it does Brevo's key, and reports `storage: unavailable` with a WARNING log naming the error. The Brevo check and this one share `_external_ok()`.
- `render.yaml` declares `S3_ENDPOINT_URL`, `S3_REGION=eu-west-1`, `S3_BUCKET=zuula-documents` and the two keys (`sync: false`). `s3` stays in `ZUULA_ALLOW_STUB_ADAPTERS` until the keys are set, because production refuses to start with a half-configured adapter.

Steps for Noah: (1) Supabase → Storage → Settings (S3 connection): enable it, create an access key, copy the key id and secret (shown once). (2) Render `zuula-api-eu` → Environment: set `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, and the three plain values above if the Blueprint sync didn't add them; remove `s3` from `ZUULA_ALLOW_STUB_ADAPTERS`; save and redeploy. Then: `/readyz` shows `storage: ok`; on the preview an image submission completes and its file is gone from the bucket afterwards; an accreditation upload appears under `accreditation/` and opens from Admin → Verifications.

**Live (29 Oct 2026).** Noah created the Supabase S3 key and set the variables on Render (`s3` removed from the stub list); `6d7e148` deployed. `/readyz`: `{"app","database","redis","email","storage"}` all `ok`. A test image posted to the API (`ZL-GYXS-O2`) was stored under `submissions/…/original` in `zuula-documents`, read back by the malware scan and the media step, and completed as `fc-2026-0167` in 17 s (verdict "unverifiable": the image models are still stubs, a Milestone D item). Not yet tried live: an accreditation document upload and opening it from Admin (same put/get path; Noah can try it from Account → Verification).

Open question for Noah: clean uploads are kept indefinitely (no rule in the requirements says otherwise). The free plan has 1 GB of storage, so before launch decide a retention period (for example, delete originals 90 days after the report) or move to R2 if media grows.

### Milestone D in detail: the AI engine (planned 29 Oct 2026)

**What the code does today** (`apps/api/app/providers/`, `app/worker/pipeline.py`): one Tavily search per submission (trusted domains first, unrestricted if fewer than a few hits), then one Groq chat completion (`openai/gpt-oss-120b`, JSON mode) that writes the verdict, then Sunbird translates the explanation into the submission's language. On Render the local models (embeddings, RoBERTa AI-text, deepfake) are stubs, because they don't fit in 512 MB.

**Found while planning:**
1. *Fake waiting.* Every pipeline step also sleeps its display time (`STEP_SECONDS × PIPELINE_STEP_SCALE`, 1.0 by default), about 10–17 s per check that does no work. It was there for the demo's progress bar.
2. *Translation is the slow step and eats the quota.* `_explain_in` translates the title, summary, every bullet and every claim reason one after another: 10–15 Sunbird requests per non-English check at several seconds each (the 97 s Luganda check). Sunbird's daily quota is about 450–500 requests, so only about 30–40 non-English checks a day.
3. *One LLM, no fallback.* If Groq is down or over quota, every check fails ("We couldn't check that").
4. *Search fails silently.* When Tavily fails (as with the exhausted quota on 28 Oct), the check goes on without web evidence and nobody is told.
5. *Images are never really checked.* Nothing reads the picture: no OCR or vision model, so an image always comes back "unverifiable" (`fc-2026-0167`).
6. *No duplicate detection in production.* The embedding model is a stub on Render, so the dedupe check and the "Zuula's own earlier reports as evidence" step are off.
7. *Accuracy unmeasured.* FR-DETECT-03 (≥ 90 %) ran on only 17 usable items (64.7 %) because shared quotas ran out.

**Plan, in order** (each step tested and deployed on its own):

| # | Step | Done when |
|---|---|---|
| D1 | **Real timing:** no sleeps in production (`PIPELINE_STEP_SCALE=0` on Render; the demo keeps 1.0); steps report real seconds. | A text check finishes in seconds, not ~15 s. |
| D2 | **Faster, cheaper translation:** translate the explanation's fields concurrently (bounded, under Sunbird's ~50/min), skip empty fields, and fall back to the English explanation with a note if Sunbird fails, instead of failing the check. | The Luganda test claim comes back in under 30 s. |
| D3 | **LLM fallback chain:** one OpenAI-compatible client tried in order: Groq → Gemini (Google's OpenAI-compatible endpoint, free tier) → OpenRouter (free models). A timeout, 429 or 5xx moves to the next; the report records which model answered. No new SDK: plain `httpx`, like today. | With Groq's key broken, a check still completes via Gemini. |
| D4 | **Read images:** send the image to a vision model (Groq `llama-4-scout`, Gemini as fallback) to extract its text and the claim it makes, then check that like text. | An image of a claim gets a real verdict. |
| D5 | **Search fallback and visibility:** a second search provider when Tavily fails or runs out of quota; the report says when no web evidence was found. | Tavily's key broken → the check still cites sources. |
| D6 | **AI status on Admin → System health:** Groq, Gemini, OpenRouter, Sunbird, Tavily: last success, last error, quota errors today. | A broken key shows up there, not just in thinner reports. |
| D7 | **Duplicates in production:** hosted embeddings for the same 384-dimension model (Hugging Face Inference API, free token), so no migration and existing vectors still match. | Submitting a known claim reuses its report. |
| D8 | **Trusted sources 12 → 50:** list drafted from the requirements' source types (media, government, fact-checkers, health, NGOs), for Noah to approve before it's seeded. | 50 active sources in production. |
| D9 | **FR-DETECT-03, measured honestly:** the 278-item held-out set over two days with dedicated keys (Groq's daily token limit), results into Appendix F. | A real accuracy number, whatever it is. |

**D1 and D2 built (29 Oct 2026; 506 API tests pass).** D1: the verdict (search + LLM) now runs inside the `sources` step and the translation back inside `report`, so the progress bar follows the real work; each step reports its real duration; `PIPELINE_STEP_SCALE` now defaults to 0 (no padding; production needs no new variable) and only pads steps that finish early (`.env.example` keeps 1.0 for local dev with stubs). An analysis failure now fails at `sources`. D2: `_explain_in` translates each distinct field once, up to `TRANSLATE_CONCURRENCY = 4` at a time; any failure keeps the whole explanation in English (never half translated), as before.

**D1 and D2 live (29 Oct 2026, `44f7630`).** Two Luganda claims on Render: `fc-2026-0168` in **32.3 s** and `fc-2026-0169` in **33.9 s** (the same kind of claim took 97 s on 28 Oct), both explained back in Luganda. Step times: language 14.6 / 17.9 s, claims (translation into English) 2.5 / 2.0 s, sources (search + LLM) 6.3 / 3.9 s, report (translation back) 7.2 / 8.5 s. **Sunbird's language detection (`/tasks/language_id`) is now the slowest step, about half the time**, consistently, so not a cold start. Next fix (D2b): skip the call when the submitter picked a language (already the case) and otherwise detect locally first (the five languages have distinctive words; the stub's word lists are a start), calling Sunbird only when unsure.

**D2b built (29 Oct 2026; 517 API tests pass).** Measured locally first: Sunbird's `language_id` answers in **1.6 s** (3.5 s on the first call), so the 15–18 s `language` step on Render isn't Sunbird being slow in general; something on Render's side of the first call is (DNS or connection setup is the likeliest). Two changes: (1) plainly English text (≥ 6 words, ≥ 25 % common English function words) is recognised locally and skips detection, which covers most submissions; Ugandan-language text, short text and mixed text still go to Sunbird. (2) Every Sunbird call slower than 5 s is logged as a WARNING with its path and time, so the next slow Luganda check shows in Render's logs where the time goes.

**D2b live (29 Oct 2026, `69aedad`).** Luganda claim `fc-2026-0170`: **17.9 s** (language 2.6 s, translation in 2.9 s, search + LLM 3.8 s, translation back 6.9 s). English claim `fc-2026-0171`: **5.7 s**, no Sunbird call at all. The 15–18 s detection didn't recur: the only slow-call warning in Render's logs was one `/tasks/translate` at 6.9 s (the slowest of the parallel field translations), so the earlier detection delay was on Sunbird's side at the time, not something in our setup. The warning stays, so it shows if it comes back. Luganda checks went 97 s → 18 s over D1, D2 and D2b.

**D3 built (29 Oct 2026; 525 API tests pass).** No new library: the Vercel AI SDK (ai-sdk.dev) is TypeScript and the engine is Python, and Groq, Gemini and OpenRouter all take the same OpenAI-style chat request, so `GroqExplanationGenerator` now holds an ordered list of `ChatModel`s (name, URL, key, model) and sends the same request down it: Groq → Gemini (Google's `/v1beta/openai` endpoint) → OpenRouter (free models); see the live test below for the model names. Any failure moves on: network error or timeout, 429 (quota), 5xx, 401, or an answer that isn't the JSON asked for (```json fences are tolerated). Each fallback is used only when its key is set (`GEMINI_API_KEY`, `OPENROUTER_API_KEY`; `GEMINI_MODEL` and `OPENROUTER_MODEL` are comma-separated lists, each model tried in turn). A check fails only when every model failed. Every failure and every verdict that came from a fallback is logged as a WARNING (Render's logs); D6 will put this on Admin → System health. The report doesn't yet record which model answered (it would need a column).

**D3 tested against the real services (29 Oct 2026).** Noah made the keys (Google AI Studio, OpenRouter) and set them on Render and in the local `.env`. The first defaults were already stale: `gemini-2.5-flash` is closed to new keys (404) and `meta-llama/llama-3.3-70b-instruct:free` is gone from OpenRouter (404). Probed today: Gemini `gemini-3.1-flash-lite` 2.6 s ✓, `gemini-flash-lite-latest` 13.7 s ✓, `gemini-flash-latest` no answer in 90 s (Google: "high demand") ✗; OpenRouter `nvidia/nemotron-3.5-super-vl:free` 8.8 s ✓, `google/gemma-4-31b-it:free` 502 ✗. Defaults are now `GEMINI_MODEL=gemini-3.1-flash-lite,gemini-flash-lite-latest` and `OPENROUTER_MODEL=nvidia/nemotron-3.5-super-vl:free,google/gemma-4-31b-it:free`. End to end with Groq's key deliberately broken: Gemini gave the verdict in **4.5 s**; with Gemini broken too, OpenRouter in **32.5 s**; both "false" citing the source. Free models change often: if the logs show "trying …" warnings for a model every time, replace its name on Render (no code change needed).

**D4 built (29 Oct 2026; 532 API tests pass).** New `app/providers/image_reader.py`: in the `media` step a vision model reads an uploaded image's text and the factual claim it makes; the claim, the text and a one-line description (after the submitter's headline, if any) become what the search and verdict check, and the report's "submitted text". Same fallback idea as D3, and the loop is now shared (`explanation.first_json`): Groq `GROQ_VISION_MODEL` (default `qwen/qwen3.8-27b`; Groq no longer offers Llama 4 Scout), then the `GEMINI_MODEL` list, then `OPENROUTER_VISION_MODEL` (default `nvidia/nemotron-3.5-super-vl:free`). Images are shrunk to 1,600 px JPEG first (Groq's 4 MB limit for inline images). If every model fails the image is checked on its headline, never failed. Before D4 an image was checked on nothing at all (empty text, the headline was ignored); now the headline is always used. Probed with a fake "free electricity from 1 January 2027" graphic: Groq qwen 1.4 s, OpenRouter Nemotron VL 6.5 s, Gemini Flash-Lite overloaded (503) at that moment; through the finished reader **1.7 s**, every line read and the claim stated. Tests also strip `GEMINI_API_KEY`/`OPENROUTER_API_KEY` from the environment, so the suite can never call them.

**D4 live (29 Oct 2026, `7b37cbf`).** The same graphic uploaded to Render (`ZL-A89W-7H` → `fc-2026-0173`, 11.1 s): the `media` step read it in 1.1 s, the report's title is the claim ("Uganda to provide free electricity to all homes from Jan 1 2027") and its submitted text is the claim plus every line of the image. Verdict "unverifiable", 80 % confidence, no citations: right for an invented claim no source mentions (compare `fc-2026-0167` the day before: "an image that cannot be processed"). A search fallback (D5) and trusted sources (D8) are what would let it say "false" with a citation.

**D5 built (29 Oct 2026; 536 API tests pass).** Backup search compared (third-party comparisons, Oct 2026; check before relying on the numbers): **Exa** gives $10 of free credit every month with no card (about 1,400 searches with highlights); Serper gives 2,500 searches once, no refill; Brave dropped its free tier in Feb 2026 (card on file and a required attribution for $5 of monthly credit); Gemini's Google Search grounding was tried with our key and refused (429, no free quota). Chosen: **Exa**. New `app/providers/exa.py` returns the same results shape as Tavily; `TavilySourceVerifier` tries Exa (trusted domains first, then open, the same rule as Tavily) whenever Tavily fails, and only goes on without web evidence when both fail. Each step is logged as a WARNING. `EXA_API_KEY` empty means no backup (as before). Not done: telling the reader when a report had no web evidence; the summary already says so in words.

**D5 live (29 Oct 2026, `e5d0d04`).** Checked against Exa's own build-with-exa guidance (read from GitHub; its `npx skills` installer wasn't run): `type: auto` and highlights only, as it recommends; `maxCharacters` 500 and 5 results are deliberate (the prompt's per-source budget, Tavily's count); `includeDomains` only ever carries the admin-approved trusted registry. Real test with Tavily's key deliberately broken: Exa returned 5 relevant Monitor / New Vision articles per claim in 3.9 s and 5.3 s. On Render (Tavily healthy) the free-electricity claim came back **false, 95 %, 5.3 s** (`fc-2026-0174`), citing a Monitor article as contradicting it, the first time that test claim got a real verdict. One wording slip to watch in D9: the summary called Umeme "the regulator" (the regulator is ERA; Umeme was the distributor).

**D6 built (29 Oct 2026; 540 API tests pass).** New `app/services/provider_health.py`: every call to Groq, Gemini, OpenRouter (the verdict and image chains), Sunbird, Tavily and Exa records its outcome in Redis (last success, last failure with a short reason such as `HTTP 429 (openai/gpt-oss-120b)`, failures today; never the request text or a key). `GET /admin/overview`'s `systemHealth` gets one row per provider whose key is set: **Working** (last answer N min ago; failures today if any), **Failing** (the reason and when; red), or **Not used yet** (a backup that hasn't been needed). The Admin screen already renders any rows the API sends, so no web or OpenAPI change. Recording is best effort: a Redis outage never fails a check, and the rows just don't show.

**D6 live (29 Oct 2026, `3104a7c`).** After a Luganda check on Render (`fc-2026-0175`, false, 38 s), Admin → System health on the preview shows, below the four existing rows: Groq, Sunbird and Tavily **Working** ("Last answer 6 min ago"); Gemini, OpenRouter and Exa **Not used yet** (backups, not needed). Noticed on the same screen, for D9 / Milestone E: the "Text detection F1 91.4 %" and "Deepfake accuracy 83.1 %" KPIs and "AI model zuula-verify 0.3, evaluated 21 Sep" come from the **seeded sample** `model_evaluations` row, not a real evaluation, so they overstate what's measured (the only real run, on 17 usable items, was 64.7 %). D9 should write a real row; until then these tiles mislead.

**D7 built (29 Oct 2026; 547 API tests pass).** `EMBEDDING_PROVIDER=huggingface` runs the same model (`paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensions) on Hugging Face's Inference API (`hf-inference` serves it, listed as live), so stored vectors and the pgvector column are unaffected. `embed()` is now async everywhere (a network call must not block the API's event loop, where checks run on Render; the local model runs in a thread). The answer is mean-pooled if it comes back per token, normalised, and rejected unless it has 384 dimensions. A failure costs only the duplicate search and local evidence, never the check; "Hugging Face" gets a System health row. Without `HF_TOKEN` it falls back to the stub with a warning, so `render.yaml` can already say `huggingface`. **Production data to fix after the token works** (Noah's approval needed, it writes to the production database): reports made on Render so far carry stub vectors (Render ran `EMBEDDING_PROVIDER=stub`), and seeded reports may have none, so they should be re-embedded with `python -m app.db.backfill_embeddings` (it would need a `--all` option to replace stub vectors, not just fill empty ones).

**Needs from Noah** (keys entered by Noah only): a Gemini API key (Google AI Studio, free) for D3/D4; an OpenRouter key (free) for D3; a Hugging Face token (read) for D7; the choice of second search provider for D5 (options: Brave Search API, Serper or Exa; I will check current free tiers before recommending one); approval of the D8 source list.

**Calls for Noah:** where to start (recommended: A, then B); whether Realtime Broadcast can wait until after launch; which Phase 4 features may be cut; who reviews the translations.

---

# Part 2 — Reference (the earlier documents, unchanged)

These were separate files until 28 October 2026. Their text is kept as written (headings shifted one level down, links pointed at this document); where they describe plans or status, Part 1 is the current word.

- [Appendix A — Zuula API](#appendix-a--zuula-api)
- [Appendix B — Zuula web app](#appendix-b--zuula-web-app)
- [Appendix C — Pages and routes](#appendix-c--pages-and-routes)
- [Appendix D — UI component inventory](#appendix-d--ui-component-inventory)
- [Appendix E — Deploying the API to Render](#appendix-e--deploying-the-api-to-render)
- [Appendix F — AI evaluation results (FR-DETECT-03)](#appendix-f--ai-evaluation-results-fr-detect-03)
- [Appendix G — ADR 0001: API architecture (P2)](#appendix-g--adr-0001-api-architecture-p2)
- [Appendix H — ADR 0002: Backend and database (P3)](#appendix-h--adr-0002-backend-and-database-p3)
- [Appendix I — ADR 0003: LanguageProvider (Sunbird AI)](#appendix-i--adr-0003-languageprovider-sunbird-ai)
- [Appendix J — ADR 0004: AI engine retrieval](#appendix-j--adr-0004-ai-engine-retrieval)


---

## Appendix A — Zuula API

*Formerly `apps/api/README.md`.*

FastAPI implementation of `openapi.yaml`: the core web-app API (`/api/v1/*`) and the public
partner API (`/v1/*`, matching the `/developers` docs). It runs on PostgreSQL + pgvector
with a Celery worker and Redis. The design decisions are in two ADRs:
[`0001`](#appendix-g--adr-0001-api-architecture-p2) (P2: the contract, the pipeline, the adapter
interfaces) and [`0002`](#appendix-h--adr-0002-backend-and-database-p3) (P3: the database,
auth, scoring, admin and the real integrations).

**P4 (the AI verdict engine):** `app/providers/analysis.py`'s `GroqAnalysisProvider` is real
when `GROQ_API_KEY`/`TAVILY_API_KEY` are set (`StubAnalysisProvider` otherwise, unchanged from
P2): a vector-db dedupe check (pgvector by default, Pinecone as an alternative), one Tavily
search and one Groq chat completion per claim, plus local RoBERTa/EXIF/image-classifier
signals for text and image content — no Claude/Anthropic calls, no agent loop. See "Providers"
and "Verdict engine" below. Deepfake-specific forensics (face-swap/lip-sync, trained models)
are out of scope for v1.

### Run it

```bash
cd apps/api
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

docker compose up -d postgres redis   # PostgreSQL 16 + pgvector, and Redis
alembic upgrade head                  # create/upgrade the schema
python -m app.db.seed                 # sample data (empty database only; never in production)

uvicorn app.main:app --reload
celery -A app.worker.celery_app worker --loglevel=INFO   # in a second shell
```

Or everything through Docker Compose: `api`, `worker`, `beat` (periodic jobs), `redis`,
`postgres`, `clamav`, and a one-shot `migrate` service that runs `alembic upgrade head`
before the API and worker start:

```bash
docker compose up --build
docker compose run --rm api python -m app.db.seed   # optional sample data
```

`GET /healthz` is liveness; `GET /readyz` is readiness and answers 503, naming what's down,
until PostgreSQL and Redis both respond. Neither is part of the contract. Interactive docs at
`/docs` are FastAPI's own, generated from the route signatures: see "Two OpenAPI documents".

**Local sign-in:** after seeding, the sample accounts (`mary@example.com` admin,
`david@example.com` expert, `sarah@example.com` journalist, `amina@example.com` public, …)
all use the password `zuula-sample-password`. Without SMS or SMTP credentials, verification
and 2FA codes are logged by the `zuula.adapters.sms` / `zuula.adapters.email` loggers (in
the worker) instead of sent.

### Test

```bash
ruff check .
ruff format --check app/db app/services app/adapters app/worker migrations tests/db tests/adapters
pytest tests/ -q
```

The tests need PostgreSQL with pgvector (`TEST_DATABASE_URL`, default
`postgresql+asyncpg://zuula:zuula@localhost:5432/zuula_test`; the user needs permission to
create databases). They don't need Redis, a worker or any external service: Redis is
`fakeredis`, Celery runs eagerly, and pipeline step durations are scaled to 0.

- **`tests/contract/`** wraps the whole app in
  [`openapi-core`](https://github.com/python-openapi/openapi-core)'s middleware and validates
  every request and response against `openapi.yaml`. Every test signs in for real (a session
  per role, a partner key) inside its own rolled-back transaction, and background work
  (pipeline, recompute, broadcasts, messages) runs inline on that transaction. A failure here
  means code and contract have drifted: fix one or the other, never skip the test. The
  `*_flows.py` files cover behaviour: auth and security, content (ratings, escalation,
  review, notifications), admin, and uploads/integrations.
- **`tests/adapters/`** tests each real integration without calling it: HTTP through `respx`,
  clamd through a fake local socket, S3 through botocore's `Stubber`, SMTP with
  `aiosmtplib.send` captured.
- **`tests/db/`** covers migrations (round trip, `alembic check`), the seed, and the rules the
  database enforces itself.
- **`tests/pipeline/`** covers the submission pipeline and realtime pub/sub;
  **`tests/core/`** covers `app/core/rules.py`.

CI (`.github/workflows/api-ci.yml`) runs lint, format, `alembic upgrade head` + `alembic
check`, and the whole suite against real PostgreSQL and Redis service containers, and
validates `openapi.yaml`.

### The contract

`openapi.yaml` is the source of truth. `packages/shared`'s TypeScript types are generated
from it (`npm run generate` there after any change), the partner docs follow it, and the
contract tests enforce it. Change it deliberately, additively where possible, and say so in
the PR.

#### Two OpenAPI documents

- **`openapi.yaml`** is hand-authored and is the contract.
- **FastAPI's generated schema** (`/openapi.json`, rendered at `/docs`) is derived from the
  route signatures and isn't used for anything. Don't treat `/docs` as the contract.

#### `response_model_exclude_none`

`app.core.router.APIRouter` sets `response_model_exclude_none=True` on every route, matching
how `apps/web/lib/types/*.ts` models optional fields (key absent when unset). A few fields
are the opposite, required *and* nullable (`ApiKey.lastUsedAt`, `ReviewCase.assignee`,
`FactCheckPublic.humanReview`, `CommunityScore.ccs`); those go through small `dump_*()`
helpers in `app/schemas/` that restore the explicit `null`.

### Database

PostgreSQL 16 + pgvector through async SQLAlchemy 2.0 on asyncpg, with Alembic migrations.

- **Models** are in `app/db/models/` (identity, content, review, platform). A model change
  needs a migration: `alembic revision --autogenerate -m "..."`, then review the file by
  hand. CI's `alembic check` fails when models and migrations disagree.
- **Business rules** (CCS weights and thresholds, review SLA, password and OTP rules,
  lockout, media limits, partner rate limit) are constants in `app/core/rules.py`, each with
  its spec citation. Import them; don't redefine them. The weights, thresholds, SLA and rate
  limit are defaults: admins change the live values (`platform_settings`) at runtime.
- **Scores are derived from vote rows.** A rating stores the rater's role at the time, and
  `app/services/community.py` recomputes the weighted CCS and status from the rows, opening or
  upgrading review cases when a report crosses a threshold.
- **The audit log** (`audit_log`) is append-only, enforced by a trigger. Every admin mutation
  and security event writes a row in the same transaction (`app/services/audit.py`).
- **Search** uses PostgreSQL full-text search with the `simple` configuration (no stemmer
  exists for Luganda, Acholi, Runyankole or Ateso) plus trigram matching on titles.
  `fact_check_reports.embedding` (pgvector, 384 dimensions, all-MiniLM-L6-v2, HNSW/cosine —
  migrations/versions/0004_embedding_dimensions.py) powers related reports and the P4 dedupe
  check where it's filled in.
- **Sample data** lives in `app/db/sample_data/` (transliterated from
  `apps/web/lib/mock/*.ts`); `python -m app.db.seed` loads it. The sample reports only carry
  aggregate rating counts, so the seed casts individual votes from labelled sample raters
  (`seed-p001`, `…@seed.zuula.invalid`) that add up to exactly those counts.

### Auth

- **Core API:** an opaque session token in the `zuula_session` cookie (HttpOnly, Secure,
  SameSite=Lax), or the same token as `Authorization: Bearer …` for non-browser clients. Only
  its SHA-256 is stored, so signing out takes effect on the next request, and roles are read
  from the database on every request. Cookie-authenticated writes must come from an origin
  in `ZUULA_CORS_ORIGINS`.
- **Passwords:** bcrypt (cost 12) over a SHA-256 pre-hash, at least 12 characters.
- **Codes and 2FA:** 6-digit codes by SMS, or email when there's no phone; 2FA is always on
  for Expert Reviewers and Admins (FR-AUTH-05).
- **Lockout:** 5 failures per account in 15 minutes gives `429`; wrong sign-up and reset codes
  count too. The per-IP limit is 50, because many users share an IP.
- **Google/Facebook sign-in:** authorization-code flow with a signed state cookie; an account
  is linked by email only when the provider verified that email.
- **Partner API:** `zl_live_…` keys, stored as SHA-256 and scoped (`POST` needs `submit`,
  `GET` needs `read`). A key only works while its owner is a journalist or admin. The limit
  is a Redis sliding window at the admin-configured rate (default 100/hour), reported in
  `X-RateLimit-*`.

### Submissions and the worker

Every channel (website, partner API, WhatsApp, Telegram) creates a submission the same way:
the `submissions` row is committed, then the pipeline is dispatched to Celery
(`app/worker/dispatch.py`). The worker runs the steps (`PIPELINES`/`STEP_SECONDS` mirror
`apps/web/lib/analysis.ts`), publishes live progress over Redis for the SSE endpoint, writes
the report, opens a low-confidence review case when needed, and notifies the submitter or
replies in the chat.

Media submissions are `multipart/form-data` with a `file` (images, audio and video up to
50 MB; `413`/`415` otherwise). The API stores the file, and the worker's "scan" step runs
ClamAV on it before anything else reads it. The scan fails closed, and an infected file is
deleted.

The worker also sends every SMS and email (`zuula.send_message`, retried with backoff),
recomputes scores after an admin changes weights or thresholds, delivers broadcasts, and,
via `beat`, runs the brigading detector every 5 minutes.

### Integrations

Every `app/adapters/` module has a real implementation and a logging stub. The real one is
used as soon as its `.env` values are set (see `.env.example`); leave them empty for local
dev.

**With `ZUULA_ENV=production`, the API and the worker refuse to start while any integration is
missing its settings**, naming each missing variable, so production can't quietly run on a
stub. A deployment that knowingly goes without some (a demo, or launching before the WhatsApp
number exists) lists their ids in `ZUULA_ALLOW_STUB_ADAPTERS` (`google`, `facebook`, `sms`,
`email`, `turnstile`, `clamav`, `s3`, `whatsapp`, `telegram`) and starts with a warning. Even
then, an unconfigured Google/Facebook sign-in sends people back to the sign-in page instead of
the stub's demo account, and an unconfigured WhatsApp/Telegram webhook refuses every call.
`ZUULA_SECRET_KEY` can never be left at its development default.

| Adapter | Real implementation | Needs |
|---|---|---|
| Google / Facebook sign-in | Authorization-code flow over `httpx` | `*_OAUTH_CLIENT_ID`, `*_OAUTH_CLIENT_SECRET` |
| SMS | Africa's Talking messaging API (`sandbox` → their simulator) | `AFRICASTALKING_USERNAME`, `AFRICASTALKING_API_KEY` |
| Email | SMTP via `aiosmtplib` | `EMAIL_SMTP_*`, `EMAIL_FROM` |
| Captcha | Cloudflare Turnstile `siteverify`, with the visitor's IP | `TURNSTILE_SECRET_KEY` |
| Malware scan | clamd `INSTREAM` over TCP; its `StreamMaxLength` must be at least 50M | `CLAMAV_HOST`, `CLAMAV_PORT` |
| Media storage | `boto3`, any S3-compatible endpoint (AWS, R2, MinIO) | `S3_*` |
| WhatsApp | Graph API messages; inbound calls must carry a valid `X-Hub-Signature-256` | `WHATSAPP_*` |
| Telegram | `sendMessage`; inbound calls must carry `X-Telegram-Bot-Api-Secret-Token` | `TELEGRAM_*` |

**Languages (Sunbird AI).** `app/providers/language.py` detects which of the five languages a
submission is in and translates between them and English with Sunbird AI's API
(`/tasks/language_id`, `/tasks/translate`) whenever `SUNBIRD_API_KEY` is set, and with a
stub that marks its "translations" `[stub-translation xx->yy]` otherwise. In the pipeline, the
`language` step detects the language when the submitter chose `auto`; Luganda, Acholi,
Runyankole and Ateso text is translated into English before `claims`; and the report's title,
summary, what's false/true and claim reasons are translated back (FR-EXPLAIN-05). If Sunbird
fails, the submission is still checked: untranslated, with an English explanation. That
includes Sunbird's HTTP 429 (about 50 requests a minute, and a daily quota of roughly 450-500
requests per key), which is logged as a rate-limit/quota failure. See
[ADR 0003](#appendix-i--adr-0003-languageprovider-sunbird-ai).

The hosted AI provider (`ANALYSIS_PROVIDER`, `ANALYSIS_PROVIDER_REGION`) stays switchable
because sending submissions to a model hosted outside Uganda is an open data-protection
question (ADR 0001) — Groq's hosted inference doesn't resolve that either way.

#### Providers (app/providers/)

Every module here follows the same convention as `app/adapters/`: a Protocol interface, a
real implementation, and a dev/test stub, picked by its own env var.

| Provider | Real implementation | Switch (default) | Needs |
|---|---|---|---|
| Language (`language.py`) | Sunbird AI detect/translate | `LANGUAGE_PROVIDER` (`stub` when no key) | `SUNBIRD_API_KEY` |
| Verdict engine (`analysis.py`) | Groq-orchestrated pipeline below | `ANALYSIS_PROVIDER` (`stub` when no key) | `GROQ_API_KEY`, `TAVILY_API_KEY` |
| Source verification (`source_verification.py`) | Tavily web search | — (used by `analysis.py` when `groq`) | `TAVILY_API_KEY` |
| Explanation (`explanation.py`) | Groq chat completion | — (used by `analysis.py` when `groq`) | `GROQ_API_KEY` |
| Dedupe embedding (`embedding.py`) | sentence-transformers (CPU) | `EMBEDDING_PROVIDER` (`stub`) | — |
| Vector DB (`vector_db.py`) | pgvector / Pinecone | `VECTOR_DB_PROVIDER` (`pgvector`) | `PINECONE_API_KEY`+`PINECONE_HOST` for `pinecone` |
| AI-text detector (`ai_text_detector.py`) | RoBERTa classifier (CPU) | `AI_TEXT_DETECTOR_PROVIDER` (`stub`) | — |
| Metadata tampering (`metadata_integrity.py`) | EXIF + SHA-256 (CPU) | `METADATA_TAMPERING_PROVIDER` (`stub`) | — |
| Deepfake/AI-image (`deepfake_detector.py`) | pretrained image classifier (CPU) | `DEEPFAKE_DETECTOR_PROVIDER` (`stub`) | — |
| Transcription (`transcription.py`) | Groq Whisper | `TRANSCRIPTION_PROVIDER` (`stub` when no key) | `GROQ_API_KEY` |
| Article fetch (`fetch.py`) | trafilatura | always real | — |

#### Verdict engine (P4)

`app/providers/analysis.py`'s `GroqAnalysisProvider.analyze()` orchestrates four independently
swappable pieces — this is where the spec's §4.1 Core AI/ML Engine components (LLM
Verification Module, AI Content Detection Module, Source Verification Engine, Explanation
Generator) actually live in the code, composed back into one claim-level result:

1. **Dedupe**: embeds the claim locally (`app/providers/embedding.py`, all-MiniLM-L6-v2 via
   sentence-transformers, CPU, no key) and looks for a near-duplicate through
   `app/providers/vector_db.py` (≤ `DEDUPE_MAX_COSINE_DISTANCE`, default 0.08). A match is
   reused outright — no Tavily search, no Groq call — which is what keeps a viral claim from
   costing anything the second time it's submitted.
2. Otherwise, **the Source Verification Engine** (`app/providers/source_verification.py`)
   runs one Tavily web search (`app/providers/tavily.py`, free tier) for evidence, restricted
   to the trusted-source registry when it has enough to offer. **The Explanation Generator**
   (`app/providers/explanation.py`) then turns that evidence into the
   verdict/claims/citations/summary shape in one Groq chat completion (`GROQ_MODEL`, free
   tier) — not an agent loop, and not a second LLM call either (see that module's docstring
   for the cost/latency tradeoff). The two were one fused function before this split; now
   they're separate modules, each independently tested. The P4 brief specified Llama 3.3 70B;
   Groq has since retired every Llama text model from its catalog, so `GROQ_MODEL` now
   defaults to `openai/gpt-oss-120b`, the current free-tier model closest in size/capability
   (see `scripts/run_eval.py`'s eval, which caught this live).
3. For text content, an in-process AI-generated-text signal
   (`app/providers/ai_text_detector.py`, a small RoBERTa classifier via `transformers`, CPU, no
   key) is appended to `ai_signals`.
4. For image content, two more AI Content Detection Module signals are appended from the
   submission's raw bytes: a metadata tampering check
   (`app/providers/metadata_integrity.py`, EXIF inconsistencies + a SHA-256 content hash, no
   model) and a basic AI-generated-image signal from a pretrained classifier
   (`app/providers/deepfake_detector.py`). Deepfake-specific forensics (face-swap/lip-sync,
   trained on FaceForensics++-style data) are explicitly out of scope — no labelled corpus, no
   GPU budget; see that module's docstring.

`app/providers/transcription.py`'s `GroqWhisperProvider` does the same for the `transcribe`
step (audio/video), and `app/providers/fetch.py`'s `TrafilaturaArticleFetcher` does real
article extraction for the `fetch` step (URL submissions) — both self-contained, no shared
base class, same as every provider above.

`EMBEDDING_PROVIDER`/`AI_TEXT_DETECTOR_PROVIDER`/`METADATA_TAMPERING_PROVIDER`/
`DEEPFAKE_DETECTOR_PROVIDER` default to `stub` even when `ANALYSIS_PROVIDER=groq`: unlike
Groq/Tavily, there's no credential to gate the real implementation on, and two of them are a
model download dev/CI must never trigger by default. Set them to
`sentence-transformers`/`roberta`/`exif`/`transformers` for the real local implementations.
`VECTOR_DB_PROVIDER` defaults to `pgvector` (the live demo path, unchanged); set it to
`pinecone` (with `PINECONE_API_KEY`/`PINECONE_HOST`) for the spec's named vector-DB
alternative — see `app/providers/vector_db.py` for why pgvector stays the default.

### Layout

```
app/
  main.py            App assembly: CORS, error handlers, routers, /healthz and /readyz
  core/              Settings (config.py), business rules (rules.py), auth dependencies
                     (security.py), the error envelope, pagination, the router default
  db/                Models, async session, Alembic-facing base, report ids, seed and sample_data/
  services/          Domain logic shared by routers, worker and seed: auth, audit, community
                     (weighted CCS), escalation, reports and search, ratings, submissions,
                     notifications, broadcasts, recompute, brigading, admin metrics
  schemas/           Pydantic v2 models mirroring openapi.yaml, camelCase on the wire
  api/v1/            Core API routers
  partner/v1/        Partner API routers
  webhooks/          Inbound WhatsApp/Telegram webhooks
  adapters/          The integrations: one interface, a real implementation and a dev stub
                     each; readiness.py picks between them and guards production
  providers/         AnalysisProvider (the verdict engine orchestrator: Groq, real when
                     GROQ_API_KEY/TAVILY_API_KEY are set), LanguageProvider (Sunbird AI
                     detection and translation), source_verification/explanation (the Source
                     Verification Engine and Explanation Generator), vector_db (pgvector/
                     Pinecone dedupe lookup), plus fetch/transcription/embedding/
                     ai_text_detector/metadata_integrity/deepfake_detector, each with its own
                     real-or-stub switch
  realtime/          Redis clients and submission pub/sub
  worker/            Celery app, the pipeline, messaging, admin tasks, dispatch
migrations/          Alembic (async env)
tests/               contract/, adapters/, db/, pipeline/, core/; conftest.py and dbutil.py
```


---

## Appendix B — Zuula web app

*Formerly `apps/web/README.md`.*

Zuula is the web front end of **Uganda Fact-Guard**, an AI fake-news detection platform specified by Victoria University's Centre for Intelligent Technologies (*System Development Plan & Functional Requirements Specification v1.0*, April 2026). Requirement IDs in the code and docs (FR-AUTH-01, §9.2, …) refer to that specification.

- Pages and routes: [docs/ui/sitemap.md](#appendix-c--pages-and-routes)
- Components: [docs/ui/component-inventory.md](#appendix-d--ui-component-inventory)

### Implementation plan

Deadline **30 Nov 2026**, one developer.

| Phase | Dates | Scope | Status |
|---|---|---|---|
| P1 Frontend | 21 Sep – 9 Oct | Next.js 16 + shadcn/ui, every page on mock data | In progress — core pages done; auth layout, home hero and mobile UI passes landed ahead of schedule |
| P2 API design | 12 – 20 Oct | FastAPI core REST API; separate partner API (API keys, 100 requests/hour); SSE/WebSockets; WhatsApp and Telegram webhooks; AI job queue (Celery + Redis); OAuth, Africa's Talking SMS, Turnstile, ClamAV, S3 | Done — Steps 1–6 merged |
| P3 Backend + database | 21 Oct – 6 Nov | PostgreSQL + pgvector, Redis, auth (bcrypt, 2FA), weighted CCS and escalation, audit log | Done — PRs 1–6 merged (DB foundation, auth/roles, content, admin, real adapters, docs); [ADR 0002](#appendix-h--adr-0002-backend-and-database-p3) accepted |
| P4 AI engine | 9 – 24 Nov | Hosted LLM (Claude) with evidence retrieval; Sunbird AI for Ugandan languages; Whisper; RoBERTa AI-text detector and a deepfake API; evaluation on about 500 labelled items | Done — Groq+Tavily verdict engine (dedupe check against a vector DB, one search + one Groq chat completion per claim, search scoped to the `trusted_sources` registry), Groq Whisper transcription, trafilatura article fetch, local RoBERTa AI-text signal, 363 real AFP-verified fact-checks, the pgvector embedding backfill for seeded reports, the FR-DETECT-03 eval harness, and the spec-fidelity additions (Pinecone vector-DB option, decoupled Source Verification Engine/Explanation Generator, EXIF/hash metadata-tampering check, pretrained deepfake signal) are all merged (PRs #46, #48, #52, #53, #57, #58). FR-DETECT-03's ≥90% target is not met and not yet reliably testable — see "Path to full functionality" below |
| Hardening + launch | 25 – 30 Nov | Security, performance, deployment | Not started |

All four phases above are running well ahead of their scheduled windows — P2, P3 and P4 are each substantially built before their windows have opened (P3 finished on 23 Sep, four weeks before its 21 Oct start; P4's first PRs merged 3 Oct, five weeks before its 9 Nov start).

Repo layout: `apps/web` (this app), `apps/api` (P2–P4), `packages/shared`. `apps/api` now has substantial code (see its own README), including the P4 AI providers (`app/providers/`). The original plan's `services/ai` directory was never used — P4 landed inside `apps/api` instead, following the same real-or-stub provider pattern as every other integration there.

#### Path to full functionality

What's between the app today and a fully wired, launch-ready platform:

- **FR-DETECT-03 is unverified, not just "not met"**: the eval harness (`apps/api/scripts/run_eval.py`) ran the full 278-item held-out set to completion, but Groq's shared daily token quota and Tavily's shared monthly search quota were both exhausted by other concurrent work during the run. Only 17 of 278 items got both a real verdict and real web evidence — those hit 64.7% accuracy, well under the 90% target but too small a sample to certify either way. A trustworthy number needs a dedicated (non-shared) Groq/Tavily key. Full results: `apps/api/EVAL_RESULTS.md`.
- **Frontend-to-API wiring**: ratings, review, admin and account settings still run on mock data (`lib/mock`) — only fact-checks and auth call the real API so far. This is the largest remaining gap for an end-to-end-real demo.
- **Role enforcement in the UI**: the API checks roles on its own endpoints, but most screens still only check the browser session's role, not the API. Needs wiring screen-by-screen.
- **Translation review**: `messages/{lg,ach,nyn,teo}.json` are unreviewed Sunbird AI machine drafts and need native-speaker review before they count as real translations.
- **CAPTCHA**: currently off in development; needs enabling for production.
- **Hardening + launch phase**: not started — security review, performance testing, and production deployment.
- **Permanently deferred, not blocking launch**: fine-tuned LLM and custom-trained CV detectors (§5) — blocked on a labelled-corpus and GPU budget this project doesn't have; see "Spec-fidelity additions" below.

#### Spec-fidelity additions

`main`'s P4 engine follows the pragmatic plan agreed with the supervisor — a hosted LLM doing retrieval-augmented generation, not the fine-tuned classifier §4/§5 of the spec describe. On top of that, the parts of the original §4/§5 architecture that are achievable without new training data or GPU budget are now merged into `main` (PR #58):

- A hosted vector DB option (Pinecone, `VECTOR_DB_PROVIDER=pinecone`) alongside the default pgvector dedupe cache (§4.1 Layer 4), matching the spec's technology choice even though pgvector already does the job
- The single Groq call split into the spec's separate components — a Source Verification Engine (`app/providers/source_verification.py`, evidence retrieval + cross-referencing) feeding a distinct Explanation Generator (`app/providers/explanation.py`, §4.1 Layer 3), rather than one fused generation call
- Metadata Tampering detection via EXIF/hash inspection (`app/providers/metadata_integrity.py`, §5.3's cheapest row, >95% target) — no ML needed
- A deepfake/synthetic-media signal (`app/providers/deepfake_detector.py`) using an existing pretrained model, wired in behind the same real-or-stub provider pattern as everything else — not a custom-trained classifier

**Explicitly not attempted, here or anywhere else, until a data-collection phase exists:** fine-tuning LLaMA 3 / Mistral on Ugandan news and multilingual corpora (§5.1–§5.2) and training custom deepfake/synthetic-audio/manipulated-video detectors (CNNDetection+FaceForensics++, Resemblyzer, FaceSwap+temporal, §5.3). Both need a curated, labelled corpus that doesn't exist yet plus real GPU budget — no amount of code produces that. This is a future phase, not a gap in the current plan.

Pages live in `app/[locale]/(public|auth|app)/`. The URL never carries the language: `proxy.ts` (next-intl, `localePrefix: "never"`) maps the `NEXT_LOCALE` cookie to the `[locale]` segment, so each language is prerendered. English strings live in `messages/en.json`.

#### Changes from the specification

These were agreed during planning and still need the supervisor's sign-off.

| Spec | Plan | Why |
|---|---|---|
| Fine-tuned LLaMA 3 / Mistral trained on Ugandan corpora (§5) | Hosted LLM with evidence retrieval, Sunbird AI for local languages | 10-week timeline; no training data or GPU budget yet — picked up again once a labelled corpus exists, not before |
| Accuracy targets of at least 90% text and 85% deepfake (FR-DETECT-03, 04) | Deepfake detection via a pretrained model (`app/providers/deepfake_detector.py`), not a custom-trained one; FR-DETECT-03 measured on a 278-item held-out set, but not yet reliably (see "Path to full functionality") | Estimates only, not proof; no training data for a custom detector; eval needs a dedicated API quota |
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

#### Known gaps

- Ratings, review, admin and account settings still use mock data from `lib/mock`. Fact-checks (home, library, report, `/verify` leaderboard) now call the real API, falling back to the mock data if it's unreachable (PR #48). Sign-up, sign-in, two-factor, password reset, sign-out and "who am I" are real calls to `apps/api` (`lib/api.ts`); see "Signing in locally" below.
- Role checks in the UI run in the browser, from the real session's role. The API enforces roles on its own endpoints, but most screens don't call it yet.
- CAPTCHA is off in development.
- Python must be upgraded to 3.12 before P3.
- `messages/{lg,ach,nyn,teo}.json` are partial, unreviewed machine drafts (Sunbird AI). Keys they don't have fall back to English. They need native-speaker review before they count as real translations.

### Development

```bash
npm install
npm run dev
```

Checks: `npm run lint`, `npm run typecheck`, `npm test`.

#### Demo sign-in (until the API is hosted)

A production build with no `NEXT_PUBLIC_API_URL` (the deployed site today) uses a browser-only demo sign-in instead of the API (`lib/demo-auth.ts`): any password works, the part of the address before `@` picks the role (`admin@`, `expert@`, `journalist@`, anything else is a Public User), codes are any 6 digits except `000000`, and the "Demo: view as" bar switches roles directly. Nothing is sent anywhere and nothing is protected. Setting `NEXT_PUBLIC_API_URL` switches to real sign-in; `NEXT_PUBLIC_AUTH_MODE=api|demo` forces either.

#### Signing in locally

Sign-in needs `apps/api` running with its database (see [its README](#appendix-a--zuula-api)). Then:

```bash
cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                  # open http://localhost:3000 (not 127.0.0.1: the session cookie is SameSite=Lax)
```

Deployed, the API usually isn't on a sibling subdomain (e.g. Vercel + Render), so the site proxies it instead: set `NEXT_PUBLIC_API_URL=/` and `ZUULA_API_ORIGIN=<the API's URL>` in the web app's build environment, and the site's own origin in the API's `ZUULA_CORS_ORIGINS`. See `.env.example` and [docs/deploy/render-agent-prompt.md](#appendix-e--deploying-the-api-to-render).

- Seeded accounts (`python -m app.db.seed`) all use the password `zuula-sample-password`: `amina@example.com` (Public User), `sarah@example.com` (Journalist), `david@example.com` (Expert), `mary@example.com` (Admin). Experts and admins get a two-factor code.
- Codes (sign-up, two-factor, reset) go through the API's stub email/SMS adapters, which only log them at INFO level. A plain `uvicorn app.main:app` doesn't show that level, so run the API with logging on to see them:
  `python -c "import logging, uvicorn; logging.basicConfig(level=logging.INFO); uvicorn.run('app.main:app', reload=False)"`
- Some Safari versions won't store the API's `Secure` cookie over plain `http://localhost`; if sign-in doesn't stick there, set `ZUULA_SESSION_COOKIE_SECURE=false` in `apps/api/.env`. Chrome and Firefox work as is.
- `NEXT_PUBLIC_ROLE_SWITCHER=true` adds a "Preview as" bar for looking at role-gated screens as a sample user while signed out. It's a UI preview, not sign-in: it grants nothing in the API and disappears once you really sign in. It's off unless set. Add shadcn components with `npx shadcn@latest add <name>`; they go in `components/ui`.


---

## Appendix C — Pages and routes

*Formerly `docs/ui/sitemap.md`.*

Status: **v0.2 (approved)** — 21 Sep 2026.

Routes below are the public URLs. In code, every page lives under `apps/web/app/[locale]/(public|auth|app)/…`. The language is never in the URL: `proxy.ts` (next-intl, `localePrefix: "never"`) reads the `NEXT_LOCALE` cookie and rewrites each request to the matching `[locale]` segment, so every page is prerendered once per language.

### 1. Pages

#### Public (site layout)
| Name | Route | Access | Spec |
|---|---|---|---|
| Home | `/` | Everyone | FR-SEARCH-05, FR-RATE-10 |
| Verify | `/verify` | Everyone (CAPTCHA when signed out) | FR-SUBMIT, FR-AUTH-07 |
| Status | `/submissions/[trackingId]` | Anyone with the tracking ID | FR-SUBMIT-06, FR-DETECT-07 |
| Library | `/fact-checks` | Everyone | FR-SEARCH-01–04 |
| Report | `/fact-checks/[id]` | Everyone; rating requires sign-in | FR-DETECT, FR-EXPLAIN, FR-RATE, FR-REVIEW-04 |
| About | `/about` | Everyone (includes FAQ) | §10.3, §11 |
| API | `/developers` | Everyone | FR-API |
| Privacy · Terms | `/legal/privacy`, `/legal/terms` | Everyone | §10.1 |
| Offline | `/offline` | Everyone (PWA fallback) | §7.3 |

#### Authentication (centered layout)
| Name | Route | Spec |
|---|---|---|
| Sign In | `/sign-in` | FR-AUTH-01 |
| Sign Up | `/sign-up` | FR-AUTH-01 |
| Verify Account | `/sign-up/verify` | FR-AUTH-03 |
| Two-Factor | `/sign-in/two-factor` | FR-AUTH-05 (Expert, Admin) |
| Forgot Password · Reset Password | `/forgot-password`, `/reset-password` | FR-AUTH-06 |

#### Account (sidebar layout)
| Name | Route | Access | Spec |
|---|---|---|---|
| Profile | `/account` | All signed-in | FR-AUTH, §10.1 |
| Activity | `/account/activity` | All signed-in | FR-SUBMIT-07, FR-NOTIFY-03 |
| Notifications | `/account/notifications` | All signed-in | FR-NOTIFY |
| Alerts | `/account/alerts` | All signed-in | FR-NOTIFY-01, 04 |
| Accreditation | `/account/verification` | Public User, Journalist | FR-AUTH-02, FR-RATE-06 |
| API Keys | `/account/api-access` | Journalist, Admin | FR-API-02 |

#### Review (sidebar layout, Expert + Admin)
| Name | Route | Spec |
|---|---|---|
| Overview | `/review` | FR-REVIEW |
| Queue | `/review/queue` | FR-REVIEW-01, 06 |
| Case | `/review/cases/[id]` | FR-REVIEW-02–05, FR-EXPLAIN-08 |
| History | `/review/history` | FR-REVIEW-03 |

#### Admin (sidebar layout, Admin)
| Name | Route | Spec |
|---|---|---|
| Overview | `/admin` | FR-ADMIN-01, §13 |
| Users | `/admin/users` | FR-ADMIN-02 |
| Moderation | `/admin/moderation` | FR-RATE-07 |
| Sources | `/admin/sources` | FR-ADMIN-03 |
| Broadcasts | `/admin/broadcasts` | FR-ADMIN-05 |
| Reports | `/admin/reports` | FR-ADMIN-04 |
| Audit Log | `/admin/audit-log` | FR-ADMIN-07 |
| Settings | `/admin/configuration` | FR-ADMIN-06 |

### 2. Navigation
- **Header:** Verify · Library · About · Review (Expert, Admin) · Admin (Admin). Right: Search (Ctrl K) · Language · Theme · Notifications · Sign In / Sign Up or user menu.
- **User menu:** Review · Admin (by role) · Activity · Notifications · Profile · Sign Out.
- **Sidebar:** Review · Admin · Account (filtered by role), Back to site, user card.
- **Footer:** Product · Organisation · Legal.
- **Mobile:** header → slide-out menu; sidebar → drawer.

### 3. Main flows
1. **Verify:** Verify → Status (live progress) → Report → rate · share · report issue.
2. **Discover:** Home feed or Library → Report.
3. **Review:** Notification or Queue → Case → confirm/override → Report shows "Human Verified".
4. **Sign up:** Sign Up → Verify Account → (Two-Factor for Expert/Admin) → return to previous page.

### 4. Build status
Updated 22 Sep 2026. All pages run on mock data (`apps/web/lib/mock`); there is no backend yet.

| Area | Built | In progress | Placeholder |
|---|---|---|---|
| Public | All 10 (Home, Verify, Status, Library, Report, About, API, Privacy, Terms, Offline) | — | — |
| Authentication | All 6 | — | — |
| Account | All 6 | — | — |
| Review | All 4 | — | — |
| Admin | All 8 | — | — |

Notes:
- Home is a single screen: hero text, the composer, and two rotating status cards (recent checks; trending and community-confirmed verdicts). "Why Zuula" moved to About.
- Report pages list related fact-checks (FR-SEARCH-03). Matching uses topic, source and wording overlap for now; true semantic matching needs embeddings (pgvector, P3).
- API docs (`/developers`) document the planned v1 contract; not callable until the P2 backend.

Remaining Phase 1 work across the app:

| Item | Status |
|---|---|
| Translations (next-intl, 5 languages) | In progress: shell, sign-in, library and report translated; Home, About and legal pending. Locale routes (`app/[locale]/`) being added |
| PWA (manifest, service worker, offline fallback) | Built: `app/manifest.ts`, `public/sw.js` (production only; keeps the last 30 viewed reports offline, never caches account, review or admin pages). The offline fallback still needs testing on a real network drop after a production deploy |
| Error pages (404, error boundaries) | Built: `error.tsx` per route group, `global-error.tsx`, `not-found.tsx` |
| Accessibility (WCAG 2.1 AA) and Lighthouse ≥ 80 pass | Not started |
| Tests | Not started |


---

## Appendix D — UI component inventory

*Formerly `docs/ui/component-inventory.md`.*

Source library: [shadcn/ui](https://ui.shadcn.com) (Radix UI primitives, Tailwind CSS).
Status: **v0.2** — 21 Sep 2026. Theme: shadcn preset `b20twYRDfO`. Fonts: Raleway (headings), Geist (body), Lora (serif), Geist Mono. Icons: Remix Icon.

Built so far: all atoms and molecules listed below are installed in `apps/web/components/ui`, and all Zuula components for verdicts, community rating, submission and discovery are built. Review and admin components are built (`UserManagement`, `SourceManager`, `PlatformSettings`, `Broadcasts`, `AuditLog`, `Moderation`, `AdminOverview`, `TrendReports`, shared `DataTable`).

Tiers:
- **Atoms** — single-purpose shadcn primitives, used everywhere.
- **Molecules** — shadcn composites.
- **Zuula components** — our own, built from atoms/molecules for Zuula-specific features.
- **Blocks** — full page sections from shadcn blocks.

---

### 1. Atoms (shadcn)

| Component | Used for |
|---|---|
| Button | All actions (Check Now, Review, Override, Save) |
| Badge | Verdict labels, roles, statuses, SLA state |
| Input | Text/URL/email/phone fields |
| Textarea | Text submission, rating comments, reviewer notes, override justification |
| Label | Form labels |
| Checkbox | Terms/privacy consent, table row selection |
| Radio Group | Verdict choice in expert override, report reasons |
| Switch | Topic alert subscriptions, notification preferences, 2FA toggle |
| Slider | Admin rating-threshold configuration (CCS %, rating counts) |
| Select | Language, role, verdict filters |
| Native Select | Mobile-friendly filters on small screens |
| Separator | Section dividers |
| Skeleton | Loading states (feed, verdicts, tables) |
| Spinner | Inline loading (buttons, analysis steps) |
| Progress | File upload progress, analysis pipeline progress |
| Avatar | User menu, reviewer identity in audit logs |
| Kbd | Search shortcut hint (Ctrl K) |
| Tooltip | Icon buttons, score explanations |
| Typography | Headings, body text, explanation prose |
| Aspect Ratio | Image/video previews of submitted media |

### 2. Molecules (shadcn)

| Component | Used for |
|---|---|
| Card | Verdict summary, fact-check result cards, stat cards |
| Alert | Emergency broadcasts, "Community questions this verdict", suspended-verdict notice |
| Alert Dialog | Destructive confirmations (suspend user, remove content, delete data) |
| Dialog | Review detail, override verdict, share verdict, report issue |
| Sheet | Mobile nav, search filter panel, admin detail side panels |
| Drawer | Mobile bottom sheets (rating comment, filters) |
| Tabs | Submission type (Text / URL / Media / Article), admin sections, verdict detail sections |
| Accordion | FAQs, "How we reached this verdict" details, source list expanders |
| Collapsible | Expandable claim explanations, AI-signal details |
| Hover Card | Hover a highlighted claim to see why it was flagged; source previews |
| Popover | Notification tray, date-range picker, share menu |
| Dropdown Menu | User menu, table row actions, language switcher |
| Navigation Menu | Public top navigation |
| Breadcrumb | Dashboard/admin page hierarchy |
| Pagination | Search results, admin tables |
| Command | Global search with autocomplete of trending topics (FR-SEARCH-02) |
| Combobox | Filtering by category/source/topic |
| Calendar + Date Picker | Date-range search filter, report periods |
| Input OTP | SMS/email OTP verification, 2FA code |
| Input Group | Search bar with icon, URL input with "Fetch" button, API key with copy button |
| Field | Consistent form field layout + validation messages (with react-hook-form) |
| Button Group | Thumbs up / thumbs down rating pair, share options |
| Toggle Group | Verdict-type quick filters, list/grid view switch |
| Table | Simple tables (citations, API usage) |
| Data Table | Review queue, users, sources, audit log, moderation (sorting, filters, pagination) |
| Chart | Admin metrics, misinformation trends, verdict distribution |
| Sidebar | Reviewer dashboard and admin shell |
| Scroll Area | Live feed, notification list, long explanations |
| Empty | "No results", empty review queue, no notifications |
| Item | List rows: feed items, notifications, sources, sessions |
| Attachment | Uploaded media file display with upload state (FR-SUBMIT-01/05) |
| Toast (Sonner) | Success/error feedback ("Rating saved", "Copied tracking ID") |
| Carousel | Optional: trending / most-debated stories on the homepage |

#### Not needed now
Bubble, Message, Message Scroller, Marker, Questionnaire (chat/agent UI), Context Menu, Menubar, Resizable, Direction (RTL). Revisit Message/Bubble if we add an in-app chat version of the WhatsApp bot.

---

### 3. Zuula components (custom, built on the above)

#### Verdict & explanation (FR-DETECT, FR-EXPLAIN)
| Component | Built from | Purpose |
|---|---|---|
| `VerdictBadge` | Badge | 5 variants: Authentic, Likely False, False, AI-Generated, Unverifiable (colour + icon, not colour alone) |
| `ConfidenceMeter` | SVG ring / Progress | AI confidence 0–100% |
| `ClaimHighlighter` | Hover Card, Typography | Highlights flagged sentences with the reason on hover/tap |
| `CitationCard` | Card, Item | Source name, article title, date, direct URL |
| `WhatIsTrueCard` | Card, Alert | "What is True" vs "What is False" summary |
| `AISignalsList` | Collapsible, Progress | Which AI-detection signals fired (perplexity, metadata, etc.) |
| `HumanVerifiedBadge` | Badge, Tooltip | Shown when an expert overrode/confirmed the verdict |
| `ExpertAnnotation` | Card, Avatar | Manual notes added by Expert Reviewers |

#### Community rating (FR-RATE)
| Component | Built from | Purpose |
|---|---|---|
| `RatingButtons` | Button Group, Tooltip | Accurate / Inaccurate, one vote per user, changeable |
| `RatingCommentForm` | Drawer/Dialog, Textarea | Optional reason for rating |
| `CCSMeter` | Progress, Badge | Community Confidence Score with like/dislike counts |
| `CommunityStatusBanner` | Alert, Badge | Community Verified / Community Questions This Verdict / Under Expert Review / Suspended |

#### Submission (FR-SUBMIT)
| Component | Built from | Purpose |
|---|---|---|
| `SubmissionComposer` | Tabs, Textarea, Input Group, Attachment, Select | Text / URL / Media / Article input with language choice |
| `MediaDropzone` | Attachment, Progress | Drag & drop, type/size (50 MB) validation |
| `CaptchaField` | — (Cloudflare Turnstile) | Anonymous submissions |
| `AnalysisProgress` | Progress, Spinner, Item | Live pipeline steps (extract → claims → sources → verdict) |
| `TrackingIdChip` | Badge, Button, Toast | Copyable tracking ID |

#### Discovery (FR-SEARCH)
| Component | Built from | Purpose |
|---|---|---|
| `GlobalSearch` | Command, Kbd | Search + autocomplete of trending topics |
| `SearchFilters` | Sheet, Select, Date Picker, Toggle Group | Keyword, date range, verdict, category |
| `FactCheckCard` | Card, VerdictBadge, CCSMeter | Result/feed item |
| `LiveFeed` | Scroll Area, FactCheckCard | Recently verified & most debated |
| `Leaderboard` | Card, Item | Most accurately rated stories |

#### Review & admin (FR-REVIEW, FR-ADMIN)
| Component | Built from | Purpose |
|---|---|---|
| `ReviewQueueTable` | Data Table | Flagged items with verdict, CCS, SLA |
| `SLAIndicator` | Badge, Tooltip | Under 24h / 24–48h / Overdue |
| `OverrideDialog` | Dialog, Radio Group, Textarea | Override with mandatory justification |
| `UserManagementTable` | Data Table, Dropdown Menu | Activate, suspend, change role |
| `SourceManager` | Data Table, Dialog | Add/update/remove trusted sources |
| `ThresholdEditor` | Slider, Field | Configure escalation thresholds |
| `BroadcastComposer` | Dialog, Textarea, Alert | Emergency misinformation broadcast |
| `AuditLogTable` | Data Table, Avatar | Admin/expert action history |
| `MetricCard` | Card, Chart | KPIs (accuracy, MAU, delivery time) |
| `TrendChart` | Chart | Misinformation trends, monthly reports |

#### App shell & account
| Component | Built from | Purpose |
|---|---|---|
| `SiteHeader` / `SiteFooter` | Navigation Menu, Sheet | Public pages |
| `AppSidebar` | Sidebar | Reviewer/admin shell |
| `RoleGate` | — | Show/hide by role (Public, Journalist, Expert, Admin) |
| `LanguageSwitcher` | Dropdown Menu | EN, Luganda, Acholi, Runyankole, Ateso |
| `ThemeToggle` | Dropdown Menu | Light / dark / system |
| `NotificationBell` | Popover, Scroll Area, Item | In-app notifications |
| `TopicSubscriptions` | Switch, Item | Alerts for Health, Politics, Elections, etc. |
| `ApiKeyCard` | Card, Input Group | Partner API key management |
| `OfflineBanner` | Alert | Low-connectivity / offline mode notice |
| `EmptyState` | Empty | Consistent empty screens |

---

### 4. Blocks (shadcn)

| Block | Zuula screen |
|---|---|
| `dashboard-01` | Admin dashboard (sidebar + charts + data table) |
| `sidebar-07` | Reviewer/admin shell (collapses to icons) |
| `login-04` / `login-03` | Login (form + image / muted background) |
| `signup-04` / `signup-03` | Registration (matching the chosen login) |

### 5. Outside shadcn (public marketing pages only)

PrebuiltUI / ReactJSTemplates offer Tailwind landing-page templates and sections (hero, features, FAQ, footer, testimonials). They do not cover app screens. Use: borrow individual sections for Home/About/FAQ if they speed things up, restyled to Zuula tokens. Check each template's licence before copying.

### 6. Brand

Owner: CREST. Import brand pieces from `apps/web/components/brand/*`; check with CREST before editing those files, `components/shell/logo.tsx`, `public/brand/*` or the favicons (`app/favicon.ico`, `app/icon.svg`, `app/apple-icon.png`).

| Colour | Hex |
|---|---|
| Crimson (primary) | `#C70036` |
| Crimson deep | `#A50036` |
| Ink | `#0B0F11` |
| Blush | `#FFF1F2` |
| White | `#FFFFFF` |

| Asset | Where |
|---|---|
| `ZuulaMark` (the right theme variant is picked automatically), `ZuulaMarkLight`, `ZuulaMarkDark`, `ZuulaMarkOutline`, `BRAND_CRIMSON` | `components/brand/zuula-mark.tsx`; pass `animated` for the loader |
| `Logo` (mark + wordmark) | `components/shell/logo.tsx` |
| SVG mark, wordmark and lockups (light/dark) | `public/brand/` |


---

## Appendix E — Deploying the API to Render

*Formerly `docs/deploy/render-agent-prompt.md`.*

Paste everything below the line into a coding agent running on your own machine.

---

You're deploying the Zuula backend (`apps/api`, FastAPI) to Render so the Vercel-hosted web app (`apps/web`) can sign people in for real. Work carefully, confirm with me before anything that costs money or can't be undone, and tell me plainly what you verified and what you didn't.

### 0. Get the current code first

```bash
git clone https://github.com/Noah-Prinzy/zuula.git || true
cd zuula && git fetch origin && git checkout main && git pull --ff-only origin main
git log --oneline -5
```

If branch `integrate/real-auth` has unmerged commits (compare `git log main..origin/integrate/real-auth`), it holds the Vercel proxy described in step 4; tell me whether it's merged yet. Then read, before changing anything: `apps/api/README.md`, `apps/api/Dockerfile`, `apps/api/docker-compose.yml`, `apps/api/.env.example`, `apps/api/app/core/config.py`, `apps/web/.env.example`, `apps/web/next.config.ts`, `apps/web/lib/api.ts`. Trust the code over this prompt where they disagree, and tell me.

### 1. What has to run on Render

From `docker-compose.yml`:

| Piece | Render resource | Command |
|---|---|---|
| API | Web Service (Docker, root dir `apps/api`) | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'` |
| Worker | Background Worker (same image) | `celery -A app.worker.celery_app worker --loglevel=INFO` |
| Migrations | Pre-deploy command on the API service | `alembic upgrade head` |
| PostgreSQL 16 + pgvector | Render Postgres | migration 0001 runs `CREATE EXTENSION vector` and `pg_trgm` |
| Redis | Render Key Value (Redis-compatible) | Celery broker/results + SSE + sign-in lockout |

Prefer a `render.yaml` Blueprint at the repo root so this is reproducible; show it to me before applying. Background workers and the pre-deploy command need paid instance types, so check current Render pricing and plan limits and tell me the monthly cost before creating anything.

### 2. Environment variables (API and worker)

Check each name against `app/core/config.py`; the `ZUULA_` prefix applies only to the `Settings` class.

- `DATABASE_URL`: from Render Postgres, **rewritten to the asyncpg driver**: `postgresql+asyncpg://…` (Render hands out `postgres://` or `postgresql://`). Check whether Render's internal URL needs SSL parameters for asyncpg.
- `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`: the Key Value internal URL with DB indices `/2`, `/0`, `/1` (see `.env.example`). Confirm Render Key Value supports multiple DB indices; if it doesn't, tell me and propose an alternative.
- `ZUULA_ENV=production`, `ZUULA_DEBUG=false`.
- `ZUULA_SECRET_KEY`: a new random value (`python -c "import secrets; print(secrets.token_urlsafe(48))"`). Never reuse the dev default, and never commit it.
- `ZUULA_SESSION_COOKIE_SECURE=true`. Leave `ZUULA_SESSION_COOKIE_DOMAIN` **empty** for the proxy setup in step 4.
- `ZUULA_CORS_ORIGINS`: the web app's exact origin(s), comma-separated, no trailing slash (e.g. `https://zuula.vercel.app`). The API's CSRF check refuses cookie-authenticated writes (sign-out, and later every write) from any origin not listed. Vercel preview URLs change per deploy, so ask me which ones to allow.
- `ZUULA_WEB_APP_URL`: the web app's URL (OAuth redirects back there).
- `ANALYSIS_PROVIDER=stub`, `PIPELINE_STEP_SCALE=1.0`. Leave the other adapter vars empty unless I give you values.
- `ZUULA_ALLOW_STUB_ADAPTERS`: with `ZUULA_ENV=production`, the API and worker **refuse to start** while any integration (OAuth, SMS, email, Turnstile, ClamAV, S3, WhatsApp, Telegram) lacks credentials, and the error names each missing variable. List every integration I haven't given you values for, comma-separated from `google,facebook,sms,email,turnstile,clamav,s3,whatsapp,telegram`, and tell me which ones you listed. For those, codes are only logged, uploads aren't virus-scanned or stored durably, the captcha accepts any token, Google/Facebook sign-in is unavailable, and the chat webhooks refuse every call.

### 3. First deploy and checks

1. Deploy; confirm the pre-deploy migration succeeded (the `vector` extension is created).
2. `GET https://<api>/healthz` → `{"status":"ok"}`; `GET /api/v1/me` → 401 JSON error.
3. Ask me before seeding. `python -m app.db.seed` loads **sample** data and nine sample accounts that all share the password `zuula-sample-password`, which is fine for a demo and unacceptable for real users. Run it from a Render shell or one-off job only if I say yes.
4. Test sign-in directly with curl against the API (a seeded account if seeded, otherwise sign up): a 200 with `set-cookie: zuula_session=…; HttpOnly; Secure; SameSite=lax`.

### 4. Connect the Vercel web app (the proxy)

The session cookie is `SameSite=Lax`. A site on `*.vercel.app` calling an API on `*.onrender.com` is cross-site, so the browser would drop the cookie: sign-in would "succeed" and then immediately look signed out. `apps/web/next.config.ts` therefore proxies `/api/v1/*` from the web app to the API, so the browser only ever talks to the Vercel origin. In the Vercel project (Production, and Preview if wanted) set:

- `NEXT_PUBLIC_API_URL=/`
- `ZUULA_API_ORIGIN=https://<your-api>.onrender.com` (server-side only; read at **build** time, so redeploy after setting it)
- optional: `NEXT_PUBLIC_ROLE_SWITCHER=true` to keep the "Preview as" bar on a demo site

Redeploy, then in a real browser on the deployed site: sign in → reload (still signed in) → sign out → reload (still signed out). Also check that `https://<site>/api/v1/me` returns the API's JSON, not a Next.js 404.

With your own domain (`zuula.ug` + `api.zuula.ug`), the direct setup also works: `NEXT_PUBLIC_API_URL=https://api.zuula.ug`, `ZUULA_SESSION_COOKIE_DOMAIN=zuula.ug`, no `ZUULA_API_ORIGIN`. Either way, list the site in `ZUULA_CORS_ORIGINS`.

### 5. Known blockers and risks to report back on (don't paper over them)

- **Verification codes aren't delivered without SMS/email credentials.** The real Africa's Talking and SMTP adapters exist (set `AFRICASTALKING_*` with a non-`sandbox` username, or `EMAIL_SMTP_*`); without them, the stubs only log the code at INFO level, and real users can't finish sign-up or 2FA. To demo it, the code has to be read from the API's logs, and plain uvicorn doesn't print INFO from app loggers. Propose the smallest safe way to make those logs visible, but don't expose codes publicly.
- **Client IP behind two proxies (Vercel → Render).** Per-IP sign-in lockout (50 failures) uses `request.client`, which depends on `X-Forwarded-For` being passed and trusted. Check what the API actually sees. If every user shows up as a Vercel IP, they'd share one lockout counter; report it. Trusting `*` also lets clients spoof the header, which weakens only the per-IP limit; the per-identifier limit still holds.
- **Local `next start` redirect loop.** On `main`, a local production server (`next start`) and `next dev` opened as `127.0.0.1` answer every page with a 307 to the same path. Vercel isn't affected. If you test locally, use `next dev` on `http://localhost:3000`, and don't try to fix this as part of the deploy.
- Free-tier Render services sleep and Render's free Postgres expires. Say which plan you picked and what that means.

When you're done, give me: the API URL, each resource and plan with its monthly cost, every env var you set (names only, never secret values), what you verified in a browser vs. with curl, and anything left open.


---

## Appendix F — AI evaluation results (FR-DETECT-03)

*Formerly `apps/api/EVAL_RESULTS.md`.*

**Headline: FR-DETECT-03's >=90% target is NOT MET. The run is now complete (278/278
items attempted), but the result is dominated by Tavily's web-search quota being fully
exhausted for the entire eval — read "What actually happened" before the numbers below.**

### What actually happened

This is the completed run of `scripts/run_eval.py` against live Groq + Tavily traffic,
combining the original attempt (31/278 scored before Groq's daily quota ran out) with a
`--resume` pass that retried the other 247 items once that quota had partially recovered.

- **Groq's daily token quota (200,000 tokens/day, free tier) was repeatedly re-exhausted
  during the resume by other concurrent sessions sharing the same key.** The resume pass
  saw the same `"Rate limit reached ... on tokens per day (TPD)"` error recur several
  times (e.g. `Used 199685/200000`, `Used 199847/200000`) as the quota trickled back and
  got spent again before this harness's turn. The harness's "give up fast on daily-quota
  waits" logic correctly treated each of these as an error and moved on rather than
  blocking, which is why the run reached 278/278 attempted despite the quota fighting it
  the whole way. **Result: 102/278 items (37%) got a real Groq verdict; 176/278 failed
  outright (175 GroqError, 1 transient ConnectionRefusedError from a Postgres restart
  mid-run).**
- **Tavily's monthly search-plan quota was already fully exhausted before the resume
  started, and stayed exhausted for its entire duration.** Every single search attempted
  during the `--resume` pass got Tavily's HTTP 432 ("exceeds your plan's set usage
  limit"). `GroqAnalysisProvider.analyze()` catches this and proceeds "with no evidence"
  rather than failing, exactly as designed — but it means **zero new evidence-backed
  verdicts were produced during the entire resume.** All 17 evidence-backed scored items
  in this report are the same 17 from the original attempt, before Tavily's quota died.
  **260/278 items (94%) got no real web evidence at all**, up from 148/278 before the
  resume.

Neither of these is a bug in the harness or in `GroqAnalysisProvider` — both are this
project's shared free-tier capacity being spent elsewhere before/during this eval's turn.

#### The one number worth trusting more than the headline accuracy

Of the 102 items that got a real Groq verdict, **17 had real Tavily evidence (frozen at
17 — no new evidence came in during the resume) and 85 did not.** Split by that:

- **With real evidence: 11/17 = 64.7%** accuracy — unchanged from the first attempt,
  since no new evidence-backed items were added.
- **Without evidence (Tavily exhausted): 0/85 = 0.0%** accuracy — every evidence-free
  guess was wrong, across all 85 of them. This is a much larger, starker sample than the
  14 we had before, and it says the same thing more forcefully: **on this held-out set,
  this verdict engine has not gotten a single evidence-free call right.**

That split is the honest way to read this run. The flat **"10.8% overall" figure below is
not a regression** — it's the same 11 correct answers as before, diluted by 71 more
evidence-free items (all wrong) that the resume was able to attempt once Groq's quota
briefly reopened. The underlying analyzer didn't get worse; the eval just got to test more
of its worst-case behavior (no evidence) and none of its best-case behavior (evidence),
because Tavily had nothing left to give for the entire second half of this run.

#### Two more things worth knowing when reading the numbers below

- **Dedupe hits are 0/278, and that's structural, not a sign dedupe is broken.** This
  environment runs `EMBEDDING_PROVIDER=stub` (the default), and separately, seeded
  `fact_check_reports` rows (fictional and real-AFP alike) are never given a real embedding
  at seed time — only `app/worker/pipeline.py`'s live submission path writes one.
  Production dedupe isn't exercised by this harness at all right now;
  `app/db/backfill_embeddings.py` (merged separately) exists to close that gap but needs
  `EMBEDDING_PROVIDER=sentence-transformers` to produce a real vector, which this run
  didn't set.
- **AFP's `claim` field sometimes isn't the false assertion itself.** Spot-checking
  mismatches earlier while building this harness, several AFP records' `claim` text is
  AFP's own true, descriptive headline about a disinformation pattern (e.g. "False quotes
  and media company logos combine to mislead voters in Kenya") rather than the literal
  false claim circulating — real evidence can correctly confirm that *headline* as true,
  nudging a well-evidenced model toward "authentic" on an item whose ground truth is
  "false". This is a genuine property of the eval data, not something to fix in it or in
  the provider.

#### Next steps

- **This project's Groq/Tavily keys need to move off the free tier, or get a dedicated key
  separate from day-to-day dev traffic, before this eval can produce a trustworthy
  headline number.** Both quotas were fully or mostly spent by other concurrent work
  before and during this eval's only two attempts — a third attempt would very likely hit
  the same wall.
- The evidence-backed sample (N=17, 64.7%) is the only part of this run worth treating as
  a real signal, and it's still too small and too far under 90% to certify FR-DETECT-03
  either way. A re-run with a fresh/dedicated Tavily quota, large enough to cover all 278
  items with real evidence, is what this eval actually needs to produce a meaningful
  number.

### Raw numbers from this run (278 items, resume completed; Tavily exhausted throughout)

- Items: 278 (Kenya + Tanzania held-out split)
- Scored (no error): 102/278
- Errors: 176/278
- **Overall accuracy: 11/102 = 10.8%** (see "one number worth trusting" above)
- FR-DETECT-03 target (>=90% text accuracy): NOT MET
- Dedupe hits: 0/278
- Tavily failures (evidence-free fallback): 260/278

### Confusion matrix (rows = actual, columns = predicted)

| actual \ predicted | authentic | likely-false | false | ai-generated | unverifiable | (error) |
|---|---|---|---|---|---|---|
| likely-false | 0 | 0 | 0 | 0 | 15 | 21 |
| false | 3 | 0 | 11 | 0 | 71 | 151 |
| ai-generated | 0 | 0 | 0 | 0 | 2 | 4 |

### Accuracy by country

- KE: 9/90 = 10.0%
- TZ: 2/12 = 16.7%

### Accuracy by category

- Economy: 0/6 = 0.0%
- Education: 1/3 = 33.3%
- Elections: 0/13 = 0.0%
- Health: 2/8 = 25.0%
- Politics: 5/37 = 13.5%
- Society: 3/31 = 9.7%
- Weather: 0/4 = 0.0%

### Note: likely-false / false ground-truth mapping

`app/db/real_data.py`'s AFP-rating -> Verdict mapping is an editorial judgment call, not something AFP itself assigns, so a predicted/actual mismatch across just these two verdicts is a softer miss than e.g. predicting `authentic` for a `false` claim.
- Ground truth `likely-false`, predicted `false`: 0
- Ground truth `false`, predicted `likely-false`: 0
- Accuracy if these two verdicts are treated as equivalent: 10.8%

### Errors

- GroqError: 175
- ConnectionRefusedError: 1


---

## Appendix G — ADR 0001: API architecture (P2)

*Formerly `docs/adr/0001-api-architecture.md`.*

**Status:** Accepted. Step 1 (the contract, [PR #1](../apps/api/openapi.yaml)), Step 2
(the FastAPI skeleton, [PR #2](https://github.com/Noah-Prinzy/zuula/pull/2)), and Steps 3+4
(the real submission pipeline, realtime delivery, and integration adapters,
[PR #3](https://github.com/Noah-Prinzy/zuula/pull/3)) are merged; Step 5 (business rules as
documented constants) is this revision's addition — see the new Business rules section
below. Several decisions here are explicitly P2-only and are expected to be superseded in
P3 — each says so.

**Superseded in part by [ADR 0002](#appendix-h--adr-0002-backend-and-database-p3) (P3):** stub auth, the
in-memory data, the TTL'd Redis submission state, the in-process rate limiter and the stub
adapters are all replaced there. The contract-first approach, the pipeline's shape and the
adapter/provider interfaces still stand.

### Context

The P2 brief asked for a contract-first API design (`openapi.yaml`) followed by a FastAPI
skeleton that returns contract-valid stub data for every operation, ahead of the real
pipeline/persistence work in later steps. This ADR records the decisions made building that
skeleton: how auth, the job queue, realtime delivery, and external integrations are
represented now, and what each one is a stand-in for.

### Auth

**Decision:** Two separate, deliberately unauthenticated-in-practice stub mechanisms, one
per API surface, each matching what the OpenAPI contract documents as the real scheme:

- **Core API** (`/api/v1/*`): `openapi.yaml` declares `sessionAuth` (an `apiKey` cookie named
  `zuula_session`, or a bearer JWT for non-browser core clients) as the eventual mechanism.
  Today, `app.core.security.get_current_user`/`require_roles` instead read a plain
  `X-Zuula-Role` header (`public` / `journalist` / `expert` / `admin`), mirroring the
  frontend's own `zuula.mock-session` demo-role system so the two stacks can be driven the
  same way in local dev. There is no password hashing, no JWT signing, no session store.
- **Partner API** (`/v1/*`): `openapi.yaml` declares `partnerApiKey` (HTTP bearer,
  `Authorization: Bearer zl_live_...`) — this one **is** the real, documented mechanism (it's
  what `/developers` shows partners), just not yet backed by persisted, provisioned keys:
  `require_partner_key` accepts any token shaped like `zl_live_*`.

**Consequence:** any request can claim any role/identity. This is acceptable for P2 (no real
user data exists to protect) but must not ship — P3 replaces the internals of both
dependencies while keeping their names and signatures, so routers don't change.

**A contract-testing gotcha worth recording:** the P2 contract test suite
(`tests/contract/test_openapi_contract.py`) validates every request/response against
`openapi.yaml` via `openapi-core`, which *does* enforce the declared security schemes'
presence — independently of, and before, our own header-based checks run. A request with no
`zuula_session` cookie at all gets rejected by `openapi-core` itself (its own hardcoded
403), never reaching `app.core.security`'s logic, which would have correctly returned its
own 401. The fixtures send a dummy cookie/bearer value on every request so `openapi-core`'s
presence check passes and our app's own auth logic actually runs and is what gets tested.

### Queue

**Decision:** Celery (`app/worker/`), broker and result backend both Redis, run as a
separate Compose service (`worker`) from the API process. `POST /api/v1/submissions`
(`app/api/v1/submissions.py`) writes an initial state record then calls
`run_submission_pipeline.delay(...)` (`app/worker/pipeline.py`), which runs the submission
through ClamAV scan → storage → transcription → analysis → verdict as a sequence of named
steps, sleeping for each step's documented duration and publishing progress as it goes.
ClamAV scanning, storage and transcription are still stand-ins (the real integrations are
Step 4's adapters — this task's job is the pipeline's *shape*, not real external calls); the
one real interface boundary is the AI step, which goes through
`app.providers.analysis.AnalysisProvider` (see below).

Step sequencing and per-step timing are not invented — `PIPELINES`/`STEP_SECONDS` in
`app/worker/pipeline.py` are transcribed field-for-field from
`apps/web/lib/analysis.ts`'s `PIPELINES`/`STEPS`, including that the step sequence differs
by submission type (a `media` submission scans and transcribes; a `text` submission doesn't;
only `url` fetches). This is deliberate: P3's frontend integration should be able to point
the existing Status page at this API with no change to what it renders, only where its data
comes from.

**Why Celery/Redis and not something else:** it's the combination the brief's Step 3/4 scope
already names (`app/worker/**`, `app/providers/analysis*`), it's a well-understood default
for Python job queues, and Redis is already a dependency for the partner rate limiter's real
(non-stub) implementation, so it isn't an extra moving part.

**State lives in Redis, not Postgres — even though Postgres is already in Compose.** The API
process and the worker process are separate OS processes (`docker-compose.yml`'s `api` and
`worker` services) with no shared memory, so submission progress has to live somewhere both
can reach. Postgres is P2's explicit placeholder-only service (nothing reads `DATABASE_URL`
yet); building real persistence for one table ahead of P3's actual schema work would be
throwaway effort. `app/realtime/submissions.py` stores each submission's state as a JSON
blob under a TTL'd Redis key (`STATE_TTL_SECONDS`, one hour) — enough to demo the full flow,
not a durable record. P3's job is to replace this with a real `submissions` table; the
functions' signatures (`load_state`/`save_state`, taking a redis client and a tracking id)
are intentionally the whole interface, so that swap doesn't ripple into the pipeline task or
the API routes.

### Realtime

**Decision:** Server-Sent Events (SSE), not WebSockets, for both places the contract needs a
live stream: `GET /api/v1/submissions/{trackingId}/events` (pipeline progress for one
submission) and `GET /api/v1/notifications/stream`. The submissions stream is real, backed
by Redis pub/sub (`app/realtime/submissions.py`'s `publish_step`/`publish_done`/
`publish_failed`/`subscribe`): the worker publishes as each step transitions, and
`app/api/v1/submissions.py`'s SSE endpoint replays whatever's already recorded in the
submission's state (so a client that connects mid-pipeline, or after it's finished, still
gets the full picture) and then forwards live pub/sub messages until a `done` or `failed`
event closes the stream. The notifications stream is still a fixed-data stub (nothing in P2
yet produces notification events to publish — that arrives with the features that create
them: review decisions, admin broadcasts) but goes through the same
`StreamingResponse(..., media_type="text/event-stream")` shape.

**Why SSE:** both streams are strictly server-to-client (the client never needs to send
messages over the same connection — actions like "mark read" or "retry submission" are
separate, ordinary POST requests), SSE degrades gracefully over plain HTTP/1.1 and proxies
without extra infrastructure, and it maps directly onto Celery task progress (a worker
publishing progress is naturally a stream of discrete named events, which is exactly SSE's
`event: <name>\ndata: <payload>` shape). Nothing here rules out WebSockets later if a
bidirectional need shows up, but nothing in the current contract needs one.

**A known, accepted gap:** there's a small race window in the submissions SSE endpoint
between reading a submission's already-recorded steps (for replay) and subscribing to its
pub/sub channel (for what's still to come) — a step that completes in exactly that window
could be missed by that one connection. The final `done`/`failed` event and a plain
`GET /api/v1/submissions/{trackingId}` poll both always reflect the true end state
regardless, so the visible effect is at most one skipped intermediate progress tick, not
stale or wrong data. Closing this fully would mean Redis Streams (replay-from-offset)
instead of pub/sub (fire-and-forget) — reasonable if it ever proves to matter in practice,
disproportionate for a P2 stub demo today.

### AnalysisProvider

**Decision:** the AI/verdict step of the pipeline goes through one interface,
`app.providers.analysis.AnalysisProvider` (a `Protocol`: one `analyze(content_type, text,
language) -> AnalysisResult` method), selected at runtime by `ANALYSIS_PROVIDER` via
`get_analysis_provider()`. P2 ships exactly one implementation, `StubAnalysisProvider`,
which deterministically maps its input to one of the existing sample reports' analysis (by
a stable hash, not Python's randomized string hash, since the mapping has to agree across
the worker process and anything else that might call it) — shaped like a real provider's
output, without doing any real analysis.

**Why this needs to be swappable at all:** sending submissions to a hosted LLM outside
Uganda is an open §10.1 data-protection question the spec doesn't resolve. `ANALYSIS_PROVIDER`
and `ANALYSIS_PROVIDER_REGION` (`app/core/config.py`'s `AnalysisSettings`,
`.env.example`) exist so that whichever answer P4 lands on — a regional deployment, an
on-Uganda-soil model, a provider allow-list — is a config change behind this interface, not
a rewrite of the pipeline that calls it.

### Adapters (external integrations)

**Decision:** every external integration the contract implies other than the analysis
provider (its own section above, Step 3) now has a `Protocol` interface plus a stub
implementation in `app/adapters/`, wired into a real call site — not just defined and left
unused. None of them call the real service:

| Adapter | `app/adapters/` | Wired into | Stub behavior |
|---|---|---|---|
| Google/Facebook OAuth | `oauth.py` | `app/api/v1/auth.py`'s `start_oauth`/`oauth_callback`, now real `RedirectResponse`s instead of an empty `{}` body with a decorative 302 status | `authorize_url()` builds a fake link; `exchange_code()` always "succeeds" with a fixed demo profile |
| Africa's Talking SMS | `sms.py` | `sign_in`'s 2FA branch, `two-factor/resend` | Logs the message; nothing is sent |
| Cloudflare Turnstile (FR-AUTH-07) | `turnstile.py` | `app/api/v1/submissions.py`'s `create_submission` — enforced only when `get_current_user()` finds no one signed in | Checks the token is present and non-blank; no call to Cloudflare's siteverify endpoint |
| ClamAV | `clamav.py` | `app/worker/pipeline.py`'s `scan` step | Always reports clean |
| S3-compatible storage | `storage.py` | `app/worker/pipeline.py`'s `media` step | Stores nothing; returns a deterministic fake URL |
| Email | `email.py` | `auth.py`'s `forgot_password` | Logs the message; nothing is sent |
| WhatsApp Cloud API, Telegram Bot (FR-SUBMIT-04) | `whatsapp.py`, `telegram.py` | New `app/webhooks/` routes (below) | Parses the real payload shape; replies are logged, not sent |

**Why these are stubs but still wired in, unlike a typical "interface with no caller" no-op:**
a Protocol nothing calls doesn't prove its own shape is right — the call site is what would
have to change if the interface were wrong (wrong argument, wrong return type, a step that
needed to be async and isn't). Wiring each one in now, even though every implementation is
inert, means P3 replaces one class per adapter (`StubX` → a real client) with no ripple into
the routes or the pipeline that call it.

**ClamAV/S3 in the pipeline don't see real bytes yet.** `create_submission` still takes a
JSON body, not a multipart file upload — building that is a bigger, separate change than
Step 4's adapter-interface scope. The `scan`/`media` pipeline steps call their adapters with
placeholder empty bytes today; P3's real multipart handling is what gives them something
real to scan and store.

**One deviation the test suite forced, not a design choice:** WhatsApp's real webhook
verification (`GET /webhooks/whatsapp`) uses Meta's own query parameter names verbatim —
`hub.mode`, `hub.verify_token`, `hub.challenge`, literal dots included, which is what Meta's
servers actually send. `openapi-core`'s Starlette request matching mishandles a literal `.`
in a query parameter name (confirmed in isolation: the identical setup with an underscore
instead of a dot validates fine) — so `tests/contract/`'s two tests for this one operation
go through a plain, unvalidated `TestClient` instead of the usual contract-validating one,
with a comment explaining why. The contract itself (`openapi.yaml`) still declares Meta's
real parameter names; only the test tooling has the gap.

### Inbound webhooks (`app/webhooks/`)

**Decision:** `GET/POST /webhooks/whatsapp` and `POST /webhooks/telegram` are new paths, not
part of the core (`/api/v1`) or partner (`/v1`) surfaces Step 1 designed — they're called by
Meta's and Telegram's own servers, not by `apps/web` or a partner, so neither `sessionAuth`
nor `partnerApiKey` applies (`security: []`; real signature/secret verification is P3). Both
POST handlers parse the provider's real payload shape, then call the same
`enqueue_submission()` helper `POST /api/v1/submissions` uses — a chat message becomes a
submission through the identical tracking-id/state/pipeline path a website visitor's does,
not a parallel one.

### Business rules (`app/core/rules.py`)

**Decision:** one module holds every numeric business rule the brief's Step 5 names — CCS
weights (§9.1), the CCS status thresholds including the escalation figure (§9.2), the review
SLA, the password minimum (FR-AUTH), the media upload cap (FR-SUBMIT-05), and the partner
rate limit (FR-API-01) — each with a citation and a note on where it's actually used.

**This is a consolidation, not new behavior.** Every one of these values already existed in
P2's code before Step 5, just duplicated: `app/stubs/scoring.py` had its own copy of the CCS
weights and thresholds, `app/stubs/review.py` had its own SLA constant, and
`app/stubs/admin.py`'s platform-settings stub had a *third* copy of essentially all of the
above (plus `app/core/config.py`'s partner rate limit setting was a fourth, independent
default). All four now import from `app/core/rules.py` instead of hardcoding their own
number — one source of truth for something a future edit could otherwise update in one
place and silently miss the other three.

**Two are explicitly open questions**, carried since the Step 1 contract PR and still
unresolved: whether admins get their own CCS weight (§9.1 is silent; the app currently rates
admins at the `public` weight — see `app/api/v1/ratings.py`'s `add_comment`), and whether
escalation should key off total ratings (§9.2, what's implemented) or "dislikes"
(FR-RATE-05, a count the app doesn't currently model at all). Both are flagged in
`rules.py` itself, not just in this ADR, so they surface to whoever next touches that code.

**Two rules are documented but not enforced yet, deliberately:** `PASSWORD_MIN_LENGTH` and
`MAX_MEDIA_BYTES` are declared in the contract (`openapi.yaml`'s schemas, and the frontend's
own `apps/web/lib/submission.ts`) but nothing in `apps/api` checks them — `auth.py`'s
sign-up/reset routes accept an untyped body without validating it, and `create_submission`
takes JSON, not a multipart upload, so there's no file to size-check. The brief's own Step 5
wording is "put these in one module... implement them in P3," so real enforcement is left
for when real password storage and real file uploads exist to enforce them against, rather
than half-built ahead of that. `PARTNER_RATE_LIMIT_PER_HOUR` is the exception — it's already
enforced for real (an in-memory counter; see the Adapters section above for why that's a
P2-only simplification), so Step 5 only needed to point its existing setting at the
constant rather than add new enforcement.

### Pagination

**Decision:** page-based (`{page, perPage, total}`), not the brief's suggested default of
cursor-based pagination. This is a deliberate, disclosed deviation from the brief, made in
Step 1: `apps/web/lib/library.ts`'s `LibraryQuery.page: number` and the partner docs'
`SEARCH_RESPONSE` shape are both already page-based, and matching them avoids a frontend
rewrite for no real benefit — nothing in the product needs cursor stability (no
infinite-scroll-under-concurrent-writes scenario) that page numbers can't handle at Zuula's
scale.

### Serialization: optional-absent vs. required-nullable

**Decision:** most optional fields in the contract follow apps/web/lib/types/*.ts's
`field?: T` convention — omitted from the JSON entirely when unset, enforced by default via
`app.core.router.APIRouter` (see `apps/api/README.md`). A small, explicit set of fields are
instead required-and-nullable (`ApiKey.lastUsedAt`, `ReviewCase.assignee`,
`FactCheckPublic.humanReview`, `CommunityScore.ccs`), matching frontend types that are
`T | null` rather than `T | undefined`, and openapi.yaml schemas typed `oneOf: [T, null]`
with the field in `required`. Those go through small per-schema `dump_*()` helpers instead
of automatic `response_model` serialization. This split was found by, and is enforced by,
the contract test suite — a field modeled the wrong way fails a real response-schema
validation, not a guess. `ccs` (null until a report has its first rating —
`community_score()` in `app/stubs/scoring.py`) is a good example of why this matters beyond
Step 2's original three: every pre-seeded sample report already has ratings, so the bug was
invisible until Step 3's pipeline created the first-ever zero-rating report and the contract
test suite caught it immediately.


---

## Appendix H — ADR 0002: Backend and database (P3)

*Formerly `docs/adr/0002-p3-backend-and-database.md`.*

**Status:** Accepted. Approved by Noah on 23 Sep 2026 (decisions in §10) and built in the six
PRs of §9, all merged. This is the record of what P3 decided and built: where the build
departed from the approved plan, the section says so, and §11 lists everything found along
the way, PR by PR. What's left for P4 is summarised in §12.

**Inputs:** the P3 row of `apps/web/README.md`'s phase table, [ADR 0001](#appendix-g--adr-0001-api-architecture-p2),
`apps/api/README.md`, `apps/api/openapi.yaml`, `app/core/security.py`, `app/core/config.py`,
every `app/stubs/*.py` (P2's in-memory sample data, now `app/db/sample_data/`), and
`apps/web/lib/{community,library,auth}.ts` + `lib/mock/admin.ts`.

### 1. Stack

| Concern | Choice | Why |
|---|---|---|
| ORM | SQLAlchemy 2.0, async (`AsyncSession`) | `.env.example` already names `postgresql+asyncpg://`. Nothing else in the repo picks an ORM. |
| Driver | `asyncpg` | Same hint. The Celery worker is sync, so it runs its DB work inside `asyncio.run(...)` per task and shares the models and repositories with the API process. There's no second driver. |
| Migrations | Alembic, async env, autogenerate reviewed by hand | This is the standard pairing, and the repo hasn't decided anything else. CI runs `alembic upgrade head` followed by `alembic check`, so a model change without a migration fails the build. |
| Vectors | `pgvector` extension plus the `pgvector` Python package | This is in the phase table. See §3. |
| Text search | Postgres FTS with the `simple` config, plus `pg_trgm` | Postgres ships no stemmer for Luganda, Acholi, Runyankole or Ateso. `simple` plus trigram similarity treats all five languages the same way. |
| Password hashing | `bcrypt` (the package itself, not the unmaintained `passlib`), cost 12 | FR-AUTH / phase table. bcrypt only reads the first 72 bytes, so longer passwords are SHA-256 pre-hashed and base64'd before hashing. |
| Redis | Stays as it is: Celery broker/backend, SSE pub/sub, plus the real partner rate limiter | Redis stops being the store of record for submission state (Postgres takes that over). |

New runtime dependencies: `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pgvector`, `bcrypt`,
`redis` (already pulled in by Celery), `boto3`, `aiosmtplib`. `httpx` moves from dev to runtime
because every HTTP adapter uses it directly; I'm not adding vendor SDKs. New dev dependency: `respx`,
for mocking real adapters in tests.

### 2. Schema

Primary keys are `text`. That keeps the ids the contract and the frontend already use: `u1`,
`fc-2026-0142`, `ZL-7K3P-Q9`, `rc-…`. New rows get a prefixed random id (`usr_…`, `ses_…`,
`key_…`) or, for reports, the next `fc-YYYY-NNNN` value from a sequence, which keeps library URLs
human-readable. The seed data keeps the current stub ids, so every hard-coded id in
`tests/contract/` still resolves.

**Identity and auth**
- `users`: id, name, email (unique, nullable), phone (unique, nullable, E.164), password_hash
  (nullable for OAuth-only accounts), role (`public|journalist|expert|admin`), status
  (`active|suspended|pending`), preferred_language, district, two_factor_enabled,
  email_verified_at, phone_verified_at, created_at, last_active_at, deleted_at.
- `oauth_identities`: (provider, subject) unique → user_id.
- `sessions`: id, user_id, token_hash (SHA-256), device, ip, location, created_at,
  last_active_at, expires_at, revoked_at. This table backs `GET/DELETE /me/sessions`.
- `auth_challenges`: id, user_id or pending-signup payload, purpose
  (`signup|two_factor|password_reset`), code_hash (HMAC-SHA256 keyed by `ZUULA_SECRET_KEY`),
  channel (`sms|email`), expires_at (10 min), attempts (max 5), last_sent_at (30 s resend
  cooldown, as the contract says), consumed_at.
- `accreditation_applications`: user_id, status, organisation, press_card_number, document_keys
  (one object key per uploaded document), submitted_at,
  reviewed_at, reviewer_id, note. When an admin approves an application, the user's role changes to
  `journalist`, and that change is audited.
- `api_keys`: id, user_id, name, prefix, secret_hash (SHA-256; the secret is 128 random bits, so it
  doesn't need a slow hash), scopes `text[]`, created_at, last_used_at, revoked_at.

**Content**
- `submissions`: tracking_id PK, user_id / api_key_id (nullable), channel
  (`web|partner|whatsapp|telegram`), type, content, url, headline, media_object_key, language,
  preview, status, steps `jsonb`, submitted_at, completed_at, error `jsonb`, report_id,
  idempotency_key. There's a unique constraint on (principal, idempotency_key), which makes the
  contract's `Idempotency-Key` header real.
- `fact_check_reports`: id, tracking_id, title, content_type, language, submitted_text,
  source_url, source_host, verdict, confidence, summary, what_is_false/what_is_true `text[]`,
  claims/citations/ai_signals `jsonb` (written once by the pipeline and always read whole, so I'm
  not normalizing them), category, checked_at, processing_seconds, human_review `jsonb`, plus
  **denormalized community columns** (six rating counts, ccs, community_status, status_changed_at)
  and `search_tsv` (a generated column) and `embedding vector` (no fixed dimension yet, see §3).
- `expert_annotations`: report_id, author_id, body, created_at.
- `ratings`: PK (report_id, user_id), vote, rater_role, created_at, updated_at.
- `rating_comments`: id, report_id, user_id, vote, body, created_at, removed_at.

**Review and moderation**
- `review_cases`: id, report_id, reason, flagged_at, reports, assignee_id, priority,
  sla_due_at, status (`open|decided`), closed_at. `sla_state` is computed when a case is read,
  not stored. There's a partial unique index on (report_id) where status is `open`, so a report
  can have at most one open case.
- `review_decisions`: id, case_id, report_id, outcome, from_verdict, to_verdict, justification,
  reviewer_id, decided_at, turnaround_hours.
- `content_flags`: one row per user per report ("report an issue"). `content_reports` holds one
  aggregated moderation item per report (reporters, sample, reason, resolved_at, resolution),
  because that's the shape the contract's `ContentReport` has.
- `manipulation_signals`: the table the admin screen reads, filled by the detector in §4.

**Admin and platform**
- `trusted_sources`, `broadcasts` (with reach/opened counters), `notifications` (user_id, kind,
  title, body, href, created_at, read_at), `alert_settings` (user_id PK, `jsonb`).
- `platform_settings`: a single row holding the `PlatformSettings` `jsonb`. When the row is first
  created, its values come from `app/core/rules.py`'s constants.
- `audit_log`: id (bigserial), at, actor_id, actor_name (a copy of the name at the time of the
  action), actor_role, action, target, detail, ip (stored truncated, as text: §11 PR 1). The
  table is **append-only**: a trigger rejects UPDATE and DELETE. *As built:* there's no REVOKE
  as well, because the app has no separate database role, and the trigger also binds the
  table owner and superusers.
- `api_usage_hourly`: (api_key_id, hour) → count. This backs `/me/api-usage`. *As built:*
  each partner request upserts its hour's row directly; the Redis flush wasn't needed at
  100 requests/hour per key. The rate limiter itself is Redis (§5).

KPIs and monthly reports become SQL aggregates wherever the data exists: latency, ratings per
verdict, expert turnaround, partners, MAU, languages. The two model-accuracy KPIs (F1 and deepfake
accuracy) come from a small `model_evaluations` table that P4 will write. Until P4 does, it's seeded
with today's numbers.

### 3. pgvector: where and why

The one vector column is `fact_check_reports.embedding`. `apps/web/lib/library.ts` says FR-SEARCH-03
"asks for semantic similarity, which needs embeddings (pgvector, Phase 3)". The Phase 1 stand-in
scores related reports by topic, word overlap, source, language and verdict. Here's the plan for it:

- `GET /fact-checks/{id}/related` ranks by cosine distance, using an HNSW index with
  `vector_cosine_ops`. Suspended reports are excluded. Reports whose embedding is still NULL fall
  back to the `library.ts` lexical score, ported exactly, the same way `scoring.py` ported
  `community.ts`.
- Computing the embeddings is AI-engine work (P4). *As built:* P3 did **not** add the planned
  `EmbeddingProvider` stub or pipeline step. A stub would only have written placeholder
  vectors that make "related" rankings meaningless, so every report keeps `embedding` NULL and
  uses the lexical fallback until P4 adds the provider (swappable, like `AnalysisProvider`,
  for §10.1 data-protection reasons) and the step that fills the column.
- **The dimension is decided in P4, not here** (Noah, 23 Sep). P3 enables the extension and adds
  the column as an untyped `vector`, which pgvector allows. An HNSW index needs a fixed dimension,
  so P3 adds no index. P4's migration narrows the column to `vector(N)` once it picks a model and
  creates the index then. Until that happens, similarity queries do an exact scan, which is fine
  at seed-data scale. The lexical fallback covers reports with no embedding.

I'm deliberately not adding embeddings on submissions ("has this claim already been checked?")
yet. Nothing in the contract uses them, and they're easy to add in P4.

### 4. Weighted CCS and escalation (server-side)

- The formula, weights and thresholds are exactly `community.ts` (already transliterated in
  `app/stubs/scoring.py`). They move to `app/services/community.py` and read their weights and
  thresholds from `platform_settings`, which admins can edit (FR-ADMIN-06). The defaults come from
  `rules.py`. Admins rate as `public` (§9.1).
- **Writes are transactional.** `POST/DELETE /fact-checks/{id}/ratings` locks the report row
  (`SELECT … FOR UPDATE`), upserts or deletes the rating, recomputes the six counts from `ratings`
  with GROUP BY (instead of incrementing, so the counts can't drift), stores ccs and status, and
  returns the fresh `CommunityScore`, all in one transaction.
- **Escalation hooks run on status transitions only:**
  - entering `escalated` → open a `community-escalation` case (normal priority);
  - entering `suspended` → open a `suspended` case (high priority), and the report disappears from
    search, facets, home feed, related reports and partner search (every `_is_listed` call site
    becomes one SQL predicate). **A review decision does not bring it back** (Noah, 23 Sep): the
    report stays hidden for as long as its status is `suspended`. It's listed again only if new
    ratings lift its score out of the suspended band. The report page itself stays reachable by
    direct link, which is how the page already behaves;
  - enough `content_flags` → a `user-reports` case;
  - pipeline confidence below the `rules.py` low-confidence threshold → a `low-confidence` case.
  Every new case gets `sla_due_at = flagged_at + sla_hours` from settings. *As built:* experts
  aren't notified of new cases; the contract has no notification kind for it, so the review
  queue is where they appear (§11 PR 3).
- **Weight changes.** If an admin changes weights or thresholds, a Celery task recomputes every
  report's score and status in batches. Reports that newly cross a threshold **do** get review
  cases, exactly as if a vote had moved them (decision 6b): a suspended report is hidden, so
  without a case nobody would ever review it. The one audit entry for the settings change
  records how many cases the recompute opened.
- **Which role a vote counts as** (decision 6a): the rater's role *when they voted*, stored on
  the rating as `rater_role`. A promotion doesn't re-weight past votes. When an admin suspends
  a user or revokes their accreditation, they can drop that user's past ratings from every
  score (`ratings.excluded_at`, an audited action) without deleting the evidence.
- **Vote-brigading detector** (feeds `manipulation_signals`): a Celery beat job flags bursts where
  N or more accounts created in the last X days vote the same direction on one report within a
  window. P3 ships the table and this simple heuristic. P4 can replace the heuristic.

### 5. Auth

**Recommendation: opaque server-side sessions, not JWTs.**

- The contract already needs server state for sessions. `GET /me/sessions` lists devices, and
  `DELETE /me/sessions/{id|others}` must revoke them immediately. With JWTs, that means keeping a
  denylist in addition to the tokens, which gives you both halves of the complexity.
- On sign-in we issue 256 random bits, set them as the `zuula_session` cookie (HttpOnly, Secure,
  SameSite=Lax, 30 days with `remember`, otherwise 12 h), and store only the SHA-256 in `sessions`.
  Non-browser core clients send the same token as `Authorization: Bearer …`. `openapi.yaml`'s
  `sessionAuth` description changes from "bearer JWT" to "bearer session token" (approved by Noah,
  23 Sep). This is a text-only change.
- **Cookie scope:** the API lives on `api.zuula.ug` and the web app on `zuula.ug`. They're
  same-site, so `SameSite=Lax` works, and the cookie is set with `Domain=zuula.ug`.
- **CSRF:** SameSite=Lax, plus an `Origin` check against `ZUULA_CORS_ORIGINS` on every
  cookie-authenticated request that isn't GET/HEAD. A foreign Origin gets `401`: the cookie
  doesn't count as authentication for that request. (`403` would be more precise, but the
  contract declares `401` on every authenticated operation and `403` on few of them.)
- **`security.py` keeps its public API.** `get_current_user`, `require_roles(*roles)`,
  `require_partner_key`, `PartnerPrincipal` and `rate_limit_headers` keep their names and
  signatures. Only their internals change: they resolve the cookie or bearer token to a
  `sessions` row joined to `users`. Suspended or deleted users get 401. Role comes from the
  database. The `X-Zuula-Role` header and `STUB_USERS` are **deleted outright**, not kept behind a
  dev flag. Routers' `Depends(...)` lines don't change; only their bodies move from `app.stubs.*`
  to repositories.
- **2FA** (FR-AUTH-05: always on for Expert and Admin, opt-in for everyone else via
  `POST /me/two-factor`). A 6-digit OTP goes over the identifier's own channel (SMS for a phone
  number, email for an email address), matching what the frontend already shows. The code is
  stored HMAC'd in `auth_challenges`, is single-use, expires after 10 min, allows 5 attempts, and
  has a 30 s resend cooldown. `challengeId` is the random challenge row id, so it can't be guessed.
  TOTP was considered and not adopted (decision 5).
- **Sign-up verification.** The contract's `POST /auth/sign-up/verify` body only has `code`, which
  can't be tied to an account safely on its own. Sign-up therefore also sets a short-lived HttpOnly
  `zuula_signup` cookie that points at the challenge. The JSON shape doesn't change.
- **Password reset** uses the same challenge table, and completing it revokes every session.
  `forgot-password` always returns 202, so it doesn't reveal which identifiers have accounts.
- **Brute force:** a Redis counter per identifier allows 5 failures per 15 min. After that,
  sign-in returns `429` with `Retry-After`. Wrong sign-up and password-reset codes count
  towards the same counter, since restarting either flow issues a fresh challenge and would
  otherwise allow unlimited guessing. The per-IP counter's threshold is 50, not 5: mobile
  carriers and schools put many people behind one address. `openapi.yaml` gains `"429": RateLimited` on
  `signIn` (approved by Noah, 23 Sep). This is the only contract response addition.
- **OAuth:** a real authorization-code flow with a signed `state` cookie (CSRF plus `next`),
  matched to `oauth_identities`, and a new account for a new identity. OAuth accounts whose role
  needs 2FA still have to pass it.
- **Partner keys:** `zl_live_` + 32 hex characters. We look the key up by prefix and compare
  SHA-256 hashes in constant time. It has to be unrevoked, and the owner has to be active and still
  a journalist or admin. The `read`/`submit` scopes are enforced per route. The rate limit becomes a
  real Redis sliding window per key id (100/h from settings), and `X-RateLimit-*` comes from the
  same counter.

### 6. Submission state moves to Postgres

As built in PR 3 (this replaces the plan's "load_state/save_state take a DB session"):

- **A submission is a `submissions` row from the moment it's accepted.** Every channel (web,
  partner, WhatsApp, Telegram) goes through one `enqueue_submission()`: validate, insert,
  **commit**, then dispatch. The worker can only see committed rows.
- **The pipeline is one async function over a DB session**, `run_pipeline(db, tracking_id)`.
  It runs each step, writes the `fact_check_reports` row (id from the sequence), opens a
  low-confidence case when the AI's confidence is under the threshold, notifies a signed-in
  submitter, and replies on WhatsApp/Telegram. The Celery task is a thin wrapper
  (`asyncio.run` on the worker's own connection). A redelivered task finds the submission no
  longer `queued` and does nothing.
- **Redis keeps only live pub/sub.** The TTL'd Redis state and `load_state`/`save_state`/
  `new_state` are gone; the status endpoint and the SSE replay read the row.
- **Dispatch is swappable** (`app/worker/dispatch.py`): the contract tests run the pipeline
  inline on the test's own connection instead of through Celery.
- **Multipart uploads** (the contract's `file`, 413/415) move to PR 5 with the real storage
  and ClamAV adapters: without them there's nowhere real to put the bytes.

### 7. Real adapters

Each adapter gets one real class behind its existing Protocol. The existing `get_*()` factories
pick the real class when its credentials are configured and fall back to the stub otherwise. When
`ZUULA_ENV=production` and credentials are missing, startup fails instead of silently using the
stub.

| Adapter | Real implementation |
|---|---|
| OAuth | Google/Facebook token and userinfo endpoints via `httpx` |
| SMS | Africa's Talking messaging REST API (`sandbox` username → sandbox host) |
| Email | `aiosmtplib`, sent from a Celery task, not in the request |
| Turnstile | `siteverify` POST with the remote IP |
| ClamAV | clamd `INSTREAM` over TCP (a small in-house client, since the `clamd` package is unmaintained) |
| S3 | `boto3` (custom endpoint, so R2, MinIO and Wasabi work too) |
| WhatsApp | Graph API `/{phone_number_id}/messages`, and verification of `X-Hub-Signature-256` on inbound calls |
| Telegram | `sendMessage`, and verification of `X-Telegram-Bot-Api-Secret-Token` on inbound calls |

Webhook signature checks need two **new** config keys: `WHATSAPP_APP_SECRET` and
`TELEGRAM_WEBHOOK_SECRET`. The existing keys can't do that job. `DATABASE_URL` finally gets read,
plus `DATABASE_POOL_SIZE`. Nothing else is new. Adapter tests use `respx` / a fake socket; nothing
calls a real service in CI.

### 8. Tests and CI

- CI adds service containers `pgvector/pgvector:pg16` and `redis:7`. The fixtures create a test
  database, run `alembic upgrade head` once per session, and load the seed data (P2's
  `app/stubs/*`, moved to `app/db/sample_data/` in PR 6; `python -m app.db.seed` loads it for
  local dev).
- Isolation works like this: each test runs inside an outer transaction on one connection, and
  both the API's `get_db` and the eager Celery worker are bound to that connection, so pipeline
  tests see their own writes. Everything rolls back at teardown.
- `tests/contract/`: `ADMIN`/`EXPERT`/`JOURNALIST`/`PUBLIC` change from role headers to session
  cookies minted for seeded users, and `PARTNER_KEY` to a seeded, hashed key. **All ~140
  assertions are kept.** New tests cover the real behaviour: a rating actually changes the CCS, a
  report that crosses a threshold opens a case, a revoked session gets 401, a key without the right
  scope gets 403, the 2FA flow works end to end, and audit rows get written.
- Local dev: `docker compose up` (the `postgres` image becomes `pgvector/pgvector:pg16`, and a
  `clamav` service is added).

### 9. Delivery: PRs to `main`, in order

All merged: #5, #8, #18, #20, #23 (plus the follow-up #24) and PR 6.

1. **DB foundation:** deps, engine/session, Alembic, all models, migration 0001, seed, test
   fixtures, CI services. Routers stay untouched and the suite stays green.
2. **Auth and roles:** sessions, bcrypt, OTP/2FA, OAuth wiring, the `security.py` internals,
   partner keys and the Redis limiter, the audit writer, and the contract-fixture switch.
3. **Content:** submissions, fact-checks/search/related, ratings/CCS/escalation, review,
   notifications (per-user SSE over Redis), and account endpoints.
4. **Admin:** users, moderation, sources, broadcasts (fan-out), settings (with recompute),
   overview and reports aggregates, and audit-log reads. Every mutation writes an audit row.
5. **Real adapters**, plus webhook signatures and multipart upload. *As built:* five grouped
   commits rather than one per adapter, since the switch to async touched shared callers.
6. **Docs:** this ADR rewritten as Accepted, `apps/api/README.md`, and deleting `app/stubs/`.

### 10. Decisions

Answered by Noah on 23 Sep 2026:

| # | Question | Decision |
|---|---|---|
| 1 | Sessions vs JWT | Opaque server-side sessions. `sessionAuth` description text updated. |
| 2 | `429` on sign-in lockout | Yes. Added to `signIn`. |
| 3 | `app/core/rules.py` | P2 Step 5's version (PR #4) landed on `main` while PR 1 was open. It is the base; P3's constants (OTP, lockout, sessions, review due-soon, low-confidence, …) are a marked section appended to it, using its names (`CCS_WEIGHTS`, `CCS_STATUS_THRESHOLDS`). |
| 4 | Embedding dimension | Fixed in P4. P3 ships an untyped `vector` column with no index (§3). |
| 5 | 2FA channel | SMS or email OTP only. No TOTP. |
| 6a | Which role weights a vote | The role at vote time (`ratings.rater_role`), plus admin exclusion of a suspended or de-accredited user's past votes (§4). |
| 6b | Cases after a weight/threshold change | Yes, opened like any other threshold crossing (§4). |
| 7 | Suspended report after review | Stays hidden while `suspended`. Only a score recovery relists it (§4). |
| 8 | Branch | PRs come from `p3/backend-db`. |
| 9 | Hosting | API on `api.zuula.ug`. Cookie `Domain=zuula.ug`, `SameSite=Lax`. |

### 11. Found while building

**PR 6 (docs and cleanup):**

- **`app/stubs/` is gone.** The sample data moved to `app/db/sample_data/`, next to the seed
  that loads it; the placeholder `AnalysisProvider` also reads it until P4. The unused
  `fact_checks_public.py` and the `scoring.py` re-export were deleted.
- **`/readyz` checks PostgreSQL and Redis** and answers 503, naming what's down, so a
  deployment's readiness probe means something. Not part of the contract.
- **`rules.py`'s comments** now say where each rule is enforced; several still described P2.

**PR 5 (real adapters):**

- **Every adapter Protocol became async**, apart from pure helpers (OAuth's `authorize_url`,
  WhatsApp/Telegram parsing and signature checks). The real implementations do network I/O,
  and the callers are all async already. boto3 is synchronous, so the S3 class runs each
  call in a thread.
- **SMS goes out from the worker too**, not only email: a new `zuula.send_message` task
  (`app/worker/messaging.py`, retried with backoff), dispatched like the pipeline. So a slow
  or failing provider can't fail a sign-in request. Broadcasts send one task per recipient,
  so one bad number is retried on its own.
- **Real vs. stub** is decided per adapter by `app/adapters/readiness.py`. Production is
  guarded as planned, and the guard also rejects the Africa's Talking `sandbox` username
  and the development `ZUULA_SECRET_KEY`.
- **Follow-up: `ZUULA_ALLOW_STUB_ADAPTERS`.** The Render guide (#21) deploys with
  `ZUULA_ENV=production` and no integration credentials, which the all-or-nothing guard
  refused. A deployment may now list adapters to run without (production only, with a
  startup warning). The unsafe stubs are off even then: stub OAuth would sign anyone in as its
  demo account, so an unconfigured provider redirects to `/sign-in?error=oauth-unavailable`,
  and stub webhooks would accept unsigned calls, so they refuse every call. The secret key
  check has no exception.
- **`CLAMAV_HOST` now defaults to empty** (it was `clamav`), since "set" is what switches the
  scanner on. Compose sets it for the worker and adds a `clamav` service. clamd's
  `StreamMaxLength` defaults to 25 MB, below our 50 MB limit, so it has to be raised in
  production, or bigger files fail the scan.
- **Scanning fails closed.** If clamd is unreachable or refuses the file, the submission fails
  (`server_error`, "couldn't scan") rather than being analysed unscanned. An infected file
  fails the submission (`invalid_content`) and is deleted from storage.
- **Media uploads:** `createSubmission` and `partnerSubmitCheck` accept `multipart/form-data`
  with `file` (types from `apps/web/lib/submission.ts`, 50 MB). A declared `Content-Length`
  over the limit is refused before the body is read. `type: media` without a file is 422.
  The report's `contentType` now comes from the file (image/audio/video).
- **Accreditation documents** are all validated before any is stored (before, a bad second
  file left the first one behind). They aren't virus-scanned yet; that's worth adding before
  admins can download them.
- **OAuth** only passes on an email the provider has verified (Google's `email_verified`;
  Facebook returns confirmed addresses only), because the callback links accounts by email.
- **Webhooks:** each checks its signature or secret before parsing. A failed "got it" reply
  is logged instead of failing the request, since an error would make Meta or Telegram
  redeliver and create a duplicate submission. The WhatsApp handshake no longer accepts an
  empty verify token when none is configured. The contract test that relied on that now
  configures a token.
- **Contract additions** (additive): `403` on `receiveWhatsAppMessage` and
  `receiveTelegramMessage`, `422` on `receiveWhatsAppMessage` (a body that isn't JSON), and
  the two signature headers declared as parameters.
- **Test tooling:** openapi-core hands multipart file parts to the validator as bytes, which
  fail `type: string, format: binary`. The contract conftest decodes them for validation only.
- **Not done:** push notifications (no adapter), media sent over WhatsApp/Telegram (only text
  messages become submissions), and de-duplicating Meta/Telegram redeliveries by message id.

**PR 4 (admin):**

- **Contract additions** (additive):
  - `excludeRatings` (boolean) on `updateAdminUser`'s body: decision 6a's way to drop or
    restore a user's past ratings.
  - `ratings.exclude` in `AuditAction`: dropping/restoring ratings is its own audited action.
    **The frontend's `AUDIT_ACTION_LABELS` needs a label for it**, like `user.reinstate` did.
  - `400`/`404` on `resolveContentReport`; `409` on `addSource`/`updateSource` (duplicate
    domain); `404` on `removeSource`; `400` on `sendBroadcast` and `updatePlatformSettings`.
  - `TrustedSource.lastCrawled`: description only. It's required, so until a source's first
    crawl it carries the time the source was added.
- **Overview KPIs are computed** (MAU = signed-in users active in 30 days; latency = p50 text
  verdict time over 7 days; ratings per verdict; expert turnaround; partners = accounts with
  an active key). F1 and deepfake accuracy come from `model_evaluations`, which P4 writes.
  System health reports the database, the analysis queue, the model and the crawler; there's
  no uptime figure without external monitoring.
- **Moderation "remove" hides the reported comments** (flags now record which comment, migration
  0003). A report about the verdict itself can't be "removed" (400): that's what expert
  review is for.
- **Sources are deactivated, never deleted**: past reports cite them.
- **Broadcasts** go in-app to every active account at once; SMS and email follow from the
  worker to people who turned those channels on. Two gaps: **push** has no adapter yet, and
  **audience** is free text, so a regional broadcast still reaches everyone. Targeting needs
  a district → region mapping.
- **Settings changes** are validated (the score bands must stay in order), audited as a
  readable diff ("Escalated: max score 39 → 55"), and re-score every report in the worker,
  opening or upgrading cases for reports that newly cross a threshold (decision 6b).
- **Brigading detector**: Celery beat runs it every 5 minutes (new `beat` service in Compose).
  25+ accounts under 48 hours old voting the same way on one report within 15 minutes becomes
  a signal for an admin; nothing is excluded automatically.

**PR 3 (content):**

- **Contract additions** (additive): `404` on `rateFactCheck`, `retractRating`,
  `listComments`, `addComment` and `reportFactCheckIssue`. Rating or commenting on a report
  that doesn't exist returned an undeclared 404 already in P2.
- **The notification stream is bounded per connection** (`ZUULA_NOTIFICATION_STREAM_SECONDS`,
  default 300). Every event carries an `id`, and a reconnect with `Last-Event-ID` replays only
  what came after it, so `EventSource`'s automatic reconnect loses and duplicates nothing.
  (An unbounded stream also can't be tested: the client never sees the end of the response.)
- **Notifications are published after their transaction commits**, never before.
- **Experts aren't notified of new cases.** The contract's notification kinds have no fit
  (`review-outcome` is for raters); the review queue is where cases appear.
- **A changed vote counts with the voter's current role.** Decision 6a is "the role when they
  voted", and changing a vote is voting again. An admin's exclusion of the user's ratings
  still applies.
- **The FR-RATE-10 leaderboard follows the frontend** (#16): ranked by the lower bound of the
  95% Wilson interval on the weighted CCS, at least 25 ratings. It's computed in SQL.
- **Search keeps its contract defaults:** `perPage` defaults to 12 (max 50) on
  `/fact-checks`, and to 10 on the partner search, not the generic 20.
- **Partner check status:** a partner sees its own checks at every stage, and anyone's once
  the report is published. Someone else's in-flight submission is a 404.
- **Chat submissions** (WhatsApp/Telegram): a bare link is checked as a URL, anything else as
  text, with no minimum length. There's no form to show a validation error on.

**PR 2 (auth and roles):**

- **Contract additions** (all additive, none change an existing shape):
  - `429` on `signIn` (decision 2).
  - `conflict` in `ErrorEnvelope.code`: `409 Conflict` was declared with no code for it.
  - `user.reinstate` in `AuditAction`: lifting a suspension had no action to be audited
    under. The frontend's `AUDIT_ACTION_LABELS` got its label in #15.
  - Error responses that real validation now returns and the contract didn't declare:
    - `400` on `changePassword`, `setTwoFactor`, `createApiKey` and `updateAdminUser`
    - `404` on `revokeApiKey`
    - `400`/`409`/`413`/`415` on `applyForVerification`
    - `403` (missing scope) on the four partner operations
- **`UserProfile.email` is required**, but an account can be phone-only. Such accounts return
  `""`. If the frontend needs to tell them apart, the contract should make `email` optional.
- **P2 query-parameter bug:** `page_params` read `per_page`, while the contract's parameter
  is `perPage`, so every core list endpoint ignored the page size. The audit log likewise
  ignored `actorRole` (it read `actor_role`). Both are fixed.
- **`packages/shared/src/openapi.ts` was stale.** P2 Step 4's webhook paths had never been
  regenerated; it's now regenerated from the current contract.
- **Admin exclusion of a user's past ratings** (decision 6a) needs a way to trigger it. The
  schema supports it (`ratings.excluded_at`), but the contract's `updateAdminUser` body has no
  field for it. That's PR 4 (admin), where it'll be proposed as an additive request field.

**PR 1 (database foundation):**

- **Sample data tracking-id collision.** `apps/web/lib/mock/quick-reports.ts` (and its P2
  transliteration) derive tracking ids with `n.replace(/[01]/g, "7")`, which maps both
  `fc-2026-0160` and `fc-2026-0161` to `ZL-7767-QK`. Tracking ids are unique in the database,
  so the seed gives `fc-2026-0161` `ZL-7868-QK`. The frontend mock still has the collision;
  it goes away for the frontend once it reads reports from the API.
- **Decided sample cases.** The sample review decisions point at cases (`rc-0412`, …) the
  sample queue doesn't list. The seed creates them as decided `community-escalation` cases,
  since their original reason isn't recorded anywhere.
- **Audit log IPs are stored already truncated** (`196.43.x.x`), as text rather than `inet`:
  that's the only form the contract and admin screen use, and not keeping the full address is
  the §10.1 data-minimisation choice.

### 12. Left for P4 and later

- **The AI engine:** a real `AnalysisProvider` (verdicts, claims, citations, AI signals), the
  `EmbeddingProvider` and its pipeline step, narrowing `embedding` to `vector(N)` with an HNSW
  index (§3), and `model_evaluations` rows for the F1 and deepfake-accuracy KPIs.
- **Integrations not built:** push notifications; photos and voice notes over WhatsApp and
  Telegram; de-duplicating their redeliveries by message id.
- **Worth adding:** virus-scanning accreditation documents before admins can download them;
  regional broadcast targeting (a district → region mapping).
- **Open contract questions:** `UserProfile.email` for phone-only accounts (§11 PR 2), and
  the two open questions in `app/core/rules.py` (admin rating weight; escalation on total
  ratings versus "dislikes").
- **Frontend follow-ups:** a label for `ratings.exclude` in `AUDIT_ACTION_LABELS`, and a
  message for `/sign-in?error=oauth-unavailable`.


---

## Appendix I — ADR 0003: LanguageProvider (Sunbird AI)

*Formerly `docs/adr/0003-language-provider.md`.*

**Status:** Accepted. First added as scaffolding (#17). The Sunbird AI implementation and the
pipeline wiring landed once Noah had an API key (24 Sep 2026); see "Sunbird implementation"
and "Wired into the pipeline" below. The rest of this record is the original scaffolding
decision. **Amended the same day** by "Translation endpoint moved to `/tasks/translate`"
below: `nllb_translate`, as described in "Sunbird implementation", no longer exists.

### Context

FR-SUBMIT-03 says users can submit content in English, Luganda, Acholi, Runyankole and
Ateso. FR-EXPLAIN-05 says the explanation comes back in the same language as the submitted
content. The spec plans Sunbird AI for the four Ugandan languages, as part of P4.

The pipeline already has a `language` step (`app/worker/pipeline.py`'s `PIPELINES`,
transcribed from `apps/web/lib/analysis.ts`: "Identifying the language and any
code-switching") for text, URL and article submissions. Today that step only sleeps. Nothing
defined the interface Sunbird would sit behind. `AnalysisProvider` was stubbed in P2 for the
same reason (ADR 0001, "AnalysisProvider"): so the rest of the system has something real to
call now, and P4 swaps the implementation without changing callers.

### Decision

`app/providers/language.py` defines a `LanguageProvider` Protocol with two methods, a
deterministic `StubLanguageProvider`, and `get_language_provider()`, which picks an
implementation by `LANGUAGE_PROVIDER`.

- **`detect(text) -> DetectionResult`**: a language code (`en`, `lg`, `ach`, `nyn`, `teo`,
  matching `apps/web/lib/locales.ts`) or `other`, a confidence, and `also_contains` for
  code-switching.
- **`translate(text, source, target) -> TranslationResult`**: covers both directions the
  pipeline needs. Inbound, the submission into `PIVOT_LANGUAGE` (English) for the
  claims/sources/ai steps. Outbound, the finished explanation back into the submission's
  language. It raises `ValueError` for anything outside the five, `other` included.
- **`resolve_submission_language(requested, text, provider)`**: an explicit choice from
  `SubmissionInput.language` is trusted as-is. `auto` goes to `detect()`.

**Provider, not adapter.** ADR 0001 keeps the AI engine (`app/providers/`) apart from the
other external integrations (`app/adapters/`). Sunbird is part of P4's AI engine, so this
follows `AnalysisProvider`. Adapters were also each wired into a call site when they landed;
this one deliberately isn't yet.

**The stub.** `detect()` counts a few hand-picked function words per language. That's
enough to tell the test fixtures apart and to demo the flow. It isn't linguistically
validated, and Luganda and Runyankole share enough vocabulary that it will misfire on real
text. `translate()` returns the text with a visible `[stub-translation xx->yy]` prefix, so a
fake translation can't be mistaken for a real one in a demo or a stored report.

**Settings.** `LanguageSettings` has `LANGUAGE_PROVIDER` (default `stub`), `SUNBIRD_API_URL`
and `SUNBIRD_API_KEY`. Nothing reads the Sunbird fields yet, and there are no HTTP calls to
Sunbird. For now the class lives in `app/providers/language.py`, not `app/core/config.py`,
so this change adds files only while P3 PR 3 is changing files nearby. It should move next to
`AnalysisSettings` (and gain `.env.example` entries) once that PR lands.

### Sunbird implementation (24 Sep 2026)

`SunbirdLanguageProvider` calls Sunbird AI's hosted API (`SUNBIRD_API_URL`, default
`https://api.sunbird.ai`) with `Authorization: Bearer SUNBIRD_API_KEY`:

- **`detect()`**: `POST /tasks/language_id` with `{"text"}`. The answer carries a language
  code (`{"language": "lug"}`; also accepted nested under `output`).
- **`translate()`**: `POST /tasks/nllb_translate` with `{"source_language", "target_language",
  "text"}`. The answer is `output.translated_text`, with `output.Error` set on failure.
- **Codes:** Sunbird uses `eng`, `lug`, `ach`, `nyn`, `teo`; Zuula uses the frontend's `en`,
  `lg`, `ach`, `nyn`, `teo`. The provider maps between them. Sunbird also knows languages
  Zuula doesn't support (Lugbara, `lgg`); those are `other`.
- **Choosing it:** `LANGUAGE_PROVIDER` empty (the default) means Sunbird when
  `SUNBIRD_API_KEY` is set and the stub otherwise, the same real-when-configured rule as
  `app/adapters/`. `stub` or `sunbird` forces one; `sunbird` without a key is an error.
  `LanguageSettings` moved to `app/core/config.py` as planned.
- **Async:** the interface became async (`detect`, `translate`,
  `resolve_submission_language`), like the adapters in ADR 0002, since the pipeline is async
  and the real calls are network I/O.
- **Tests** mock Sunbird with `respx`; nothing calls the real API. The test session removes
  any `SUNBIRD_API_KEY` from its environment so the pipeline tests use the stub.

**Where Sunbird can't do what the stub assumed (flagged):**

- **No confidence.** `language_id` returns a language only, so `DetectionResult.confidence`
  became optional and is `None` from Sunbird.
- **No code-switching.** `language_id` names one language, so `also_contains` is always
  empty from Sunbird, and mixed Luganda-English text is translated as a whole.
- **Length.** The public docs don't state a text limit for `nllb_translate`, and the NLLB
  model behind it translates short passages. Text is sent in whole-sentence chunks of at most
  1,000 characters (an assumption). A 20,000-character article is about 20 requests, against
  a documented rate limit of 50 requests a minute on a standard account.
- **Not verified live.** This build environment can't reach `api.sunbird.ai` or Sunbird's
  docs, so the request and response shapes come from Sunbird's published examples, not from
  a real call. The first deploy with the key should confirm them: submit a Luganda text with
  language `auto` and check the report comes back in Luganda.

### Translation endpoint moved to `/tasks/translate` (24 Sep 2026)

Checked live with the key, `POST /tasks/nllb_translate` now answers HTTP 405, so every
translation through the provider failed (and the pipeline quietly fell back to untranslated
text and English explanations). Sunbird's OpenAPI spec (`/openapi.json`) lists
`POST /tasks/translate` in its place, backed by the sunflower-9b LLM instead of NLLB.
`/tasks/language_id` is unchanged. The "Sunbird implementation" section above records what
was built first and is left as it was; this is what changed:

- **Request:** same body and bearer auth. Codes stay ISO 639-3 (`lug`); `source_language` is
  optional there, but the provider always sends it.
- **Response:** the translation is still `output.translated_text`, with `output.Error` on
  failure. `output.text` echoes the *input*, although the schema calls it the translated
  output, so reading it would silently return the original text. A missing or non-string
  `translated_text` is treated as a failure.
- **Chunking kept.** The spec still gives no maximum length, and documents 503 for an
  inference timeout and 502 for empty model output. The 1,000-character whole-sentence chunks
  stay, still as an assumption rather than a verified limit.
- **LLM behaviour:** short inputs can gain a trailing period, and named `{placeholders}` can be
  translated (`{name}` became `{erinnya}`); numeric `{0}` survived. Submissions and
  explanations carry no placeholders, but templated text would need protecting.
- **Limits:** about 50 requests a minute and a daily quota of roughly 450-500 requests per
  key, both HTTP 429 (`RATE_LIMIT_ERROR`, with `details[].retry_after_seconds`).
  `SunbirdError` now carries `status_code`, and a 429 says it's a rate limit or quota and
  when to retry. The pipeline already treats any provider error as "don't translate", so a
  spent quota degrades to English rather than failing submissions. One submission's
  explanation is several requests (title, summary, each what's-false/true item, each claim
  reason), so the daily quota caps real use at a few dozen translated submissions a day.

### Wired into the pipeline

As planned below, in `app/worker/pipeline.py`:

1. **`language` step:** `resolve_submission_language(...)`. An explicit choice is trusted; `auto`
   is detected. The report stores the display name (`Luganda`), where before it stored the
   raw request value (often `auto`). A URL's content isn't fetched yet (P4), so `auto` on a
   URL is `Other`; media keeps an explicit choice or is `Other` until transcription (P4).
2. **Before `claims`:** text and article submissions in Luganda, Acholi, Runyankole or Ateso are
   translated into English, and the analysis provider is given that English text.
   `submitted_text` keeps what the person wrote.
3. **After analysis:** the title, summary, what's false, what's true and each claim's reason are
   translated into the submission's language (FR-EXPLAIN-05). Citation titles stay as their
   sources wrote them. Only the translated version is stored; there's no English copy.
4. **Failures don't fail the submission.** If detection fails the language is `Other`; if
   translation fails the original text is analysed, or the explanation stays in English. Each
   is logged.

**Left for P4:** claim `start`/`end` offsets index the text the analysis read. Once that is
the English translation, they no longer point into the original `submitted_text`, so P4's
analysis has to map them back (or highlight claims another way).

### Originally: not wired in yet

Connecting this is P3 PR 3's territory (`app/worker/pipeline.py`), so it's left for that
work. The expected shape:

1. In the `language` step, call `resolve_submission_language(language, text, provider)`.
   Today `run_submission_pipeline` passes the raw request value (often `auto`) straight into
   `AnalysisProvider.analyze()` and `FactCheckReport.language`. That's a mismatch this step
   should fix, storing `display_name(code)` on the report.
2. Before `claims`, if the code isn't `PIVOT_LANGUAGE` or `other`, translate the text into
   English for the claims/sources/ai steps.
3. After `analyze()`, translate the user-facing explanation fields back into the
   submission's language (FR-EXPLAIN-05).

`media` submissions have no `language` step. Their language would come from transcription,
which is also P4 (Whisper).

### Open questions

Where each stands after the Sunbird work:

- **Sunbird access.** *Answered:* Noah has a key (24 Sep 2026).
- **Which report fields get translated back.** *Built as:* title, summary, what's false,
  what's true and claim reasons; citation titles stay as written; only the translated
  version is stored. Keeping an English copy too would need a `fact_check_reports` schema
  change (ADR 0002). Still Noah's call whether that's wanted.
- **What happens with `other`.** *Built as:* analysed untranslated, explanation in English.
  Rejecting it or sending it to human review instead is still open; the spec doesn't say.
- **Code-switching.** *Answered by Sunbird's API:* it names one language, so mixed text is
  translated as a whole.
- **Data protection.** Still open. Sunbird is a Ugandan organisation, which may make §10.1
  easier than it is for a hosted LLM, but that needs confirming, like
  `ANALYSIS_PROVIDER_REGION`. Submissions in a Ugandan language, and every explanation
  going back to one, are now sent to Sunbird whenever the key is set.


---

## Appendix J — ADR 0004: AI engine retrieval

*Formerly `docs/adr/0004-ai-engine-retrieval.md`.*

**Status:** Accepted and implemented.

### Context

With P4's verdict engine (ADR 0001 "AnalysisProvider", `app/providers/analysis.py`) running
against real traffic, the question came up: what's our actual retrieval-augmented-generation
architecture, how is data chunked, which embedding model fits, and what would genuinely
improve it? This ADR records the audit and the two changes that came out of it.

**What the engine already does (unchanged by this ADR).** `GroqAnalysisProvider` is not
classic RAG over an indexed document collection — it's single-shot search-augmented
generation, closer to Perplexity than to a RAG paper: one live Tavily web search per claim
(`app/providers/source_verification.py`), one Groq chat completion that turns that evidence
into a verdict (`app/providers/explanation.py`). The pgvector index on
`fact_check_reports.embedding` existed only as a dedupe cache — catching a resubmitted
near-identical claim before it cost another search and another Groq call — not as an evidence
corpus anything was retrieved from.

**No chunking exists, and that's deliberate, not a gap.** A text-splitting step only earns
its complexity when there's a long document to split. There isn't one here: submitted claims
are short, Tavily pre-chunks its own results (a title plus a ~500-character snippet, already
sized for the prompt), and every `fact_check_reports` row is a single self-contained unit (one
claim, one summary) rather than a long article body. Introducing a chunker to split nothing
would be exactly the premature complexity this codebase's own conventions warn against. This
becomes worth revisiting only if a future corpus indexes full article bodies rather than
fact-check summaries — noted here so it isn't re-litigated from scratch later.

**The embedding model was English-only.** `all-MiniLM-L6-v2` (sentence-transformers, 384-dim,
CPU, free) has no meaningful multilingual training. Uganda's submissions aren't all English —
FR-SUBMIT-03 names Luganda, Acholi, Runyankole and Ateso (ADR 0003) — so a non-English
resubmission of an already-debunked claim couldn't be matched to its existing report at all;
the dedupe cache silently didn't work across languages.

**The trusted-source registry is thin.** Only 12 of a 50-source target are seeded
(`app/db/sample_data/admin.py`), so `TavilySourceVerifier`'s restricted-search-with-fallback
(`_RESTRICTED_SEARCH_MIN_RESULTS`) almost always falls back to an unrestricted web search.
Independent of this ADR's changes, but it's the reason leaning harder on our own verified
corpus (below) is worth more here than it would be with a mature source registry.

### Decision

#### 1. Multilingual embedding model

`EMBEDDING_MODEL` changes from `sentence-transformers/all-MiniLM-L6-v2` to
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
(`app/core/config.py`, `app/providers/embedding.py`). Same sentence-transformers family, same
384-dim output — no new migration needed past `migrations/versions/0004_embedding_dimensions.py`
— but trained across 50+ languages instead of English-only. This is a straight drop-in
replacement with no code change beyond the configured model name.

#### 2. Local-evidence retrieval (the RAG upgrade)

The pgvector lookup `GroqAnalysisProvider.analyze` already did for dedupe is widened from a
single nearest-neighbor (`find_nearest`) to a top-K lookup (`VectorDbProvider.find_similar`,
implemented on both `PgVectorProvider` and `PineconeVectorProvider`), then split by distance
into two tiers against two thresholds:

- **`DEDUPE_MAX_COSINE_DISTANCE`** (0.08, unchanged): close enough to be the same claim —
  reused outright, exactly as before.
- **`LOCAL_EVIDENCE_MAX_COSINE_DISTANCE`** (0.3, new): not the same claim, but close enough to
  be useful grounding. These matches are resolved to their `fact_check_reports` rows and
  prepended to the evidence passed into the Explanation Generator
  (`GroqAnalysisProvider._augment_with_local_evidence`), cited back to their own original
  source (`report.citations[0]`, e.g. the AFP article) rather than to Zuula's own report page.

`EvidenceBundle` (`app/providers/source_verification.py`) grew one field,
`local_evidence_count`, saying how many of its leading `sources` are local-evidence matches
rather than `TavilySourceVerifier`'s own live results. `GroqExplanationGenerator`
(`app/providers/explanation.py`) uses it to label each evidence item in the prompt — "(Zuula's
own verified fact-check corpus)" versus "(live web search)" — and to mark local-evidence
citations as always `trusted`, regardless of the thin trusted-source registry's domain list:
a match from our own verified corpus is stronger evidence than an arbitrary web result, and
the model and the reader should be able to tell the two apart.

**This costs nothing extra.** The widened vector-DB lookup is the same one call
`analyze` already made for dedupe, just asking for more rows back — a local Postgres query,
not a second Tavily search or Groq call. The P4 cost constraint (one Tavily search, one Groq
completion, per claim) is unchanged either way.

**Why this design over the alternatives considered:**

- **Corpus-only RAG (drop live Tavily search).** Rejected: can't handle a claim about
  something that happened yesterday. Our verified corpus only grows from claims we've already
  checked; breaking news needs live search regardless of how good local retrieval gets.
- **Agentic/multi-hop RAG** (iterative query reformulation, multiple search rounds per claim).
  Rejected: breaks the one-search/one-call free-tier cost constraint this engine is built
  around (`explanation.py`'s own docstring on why it's one Groq call, not two). Nothing here
  rules it out later if a real evaluation shows the single-call design hurts quality enough to
  justify the extra Groq/Tavily usage.
- **Fine-tuning a model on Uganda fact-check data.** Rejected: no GPU budget, no labelled
  corpus at the scale fine-tuning needs (the entire real corpus is ~360 records, and
  `tools/data-collection/README.md` documents that it's almost entirely debunks), and Groq's
  free-tier hosted models aren't fine-tunable by us anyway.
- **GraphRAG / knowledge-graph retrieval.** Rejected: no graph-shaped data exists here
  (entities/relations between claims, people, events), and building one is a bigger
  investment than this stage's traffic or team size justifies.

### Consequences

- `LOCAL_EVIDENCE_MAX_COSINE_DISTANCE` (0.3) and `LOCAL_EVIDENCE_LIMIT` (3) are picked by
  inspection, the same caveat `DEDUPE_MAX_COSINE_DISTANCE` already carries — revisit once
  real traffic or a labelled eval (`scripts/run_eval.py`) exists to tune against.
  `all-MiniLM-L6-v2`'s 0.08 dedupe threshold was picked by inspection against that model;
  swapping to `paraphrase-multilingual-MiniLM-L12-v2` keeps the same dimensionality but not
  necessarily the same distance distribution, so this threshold should be the first thing
  re-checked once real submissions and `scripts/run_eval.py` give something to tune against.
- Local-evidence retrieval only helps as the verified corpus grows. At ~360 records today
  (almost all AFP Uganda/Kenya/Tanzania debunks — see `tools/data-collection/README.md`), it
  will mostly surface prior debunks on recurring viral claims (the Museveni-health-rumor,
  election-rigging-photo kind of repeat); it won't yet have much to say about genuinely novel
  claims, which is exactly where live Tavily search still carries the load.
- `VectorDbProvider.find_nearest` is now implemented in terms of `find_similar(limit=1)` on
  both providers — a refactor, not a behavior change; existing dedupe tests are unaffected.
