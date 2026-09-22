# ADR 0002: Backend and database (P3)

**Status:** Proposed. This is the design plan from step 1 of the P3 brief, written for Noah to review before
any migrations or models are built. Nothing described here is implemented yet. Once it's approved
and built, this file gets rewritten as the record of what was actually decided (brief §3 step 5).

**Inputs:** the P3 row of `apps/web/README.md`'s phase table, [ADR 0001](0001-api-architecture.md),
`apps/api/README.md`, `apps/api/openapi.yaml`, `app/core/security.py`, `app/core/config.py`,
every `app/stubs/*.py`, and `apps/web/lib/{community,library,auth}.ts` + `lib/mock/admin.ts`.

## 1. Stack

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

## 2. Schema

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
- `accreditation_applications`: user_id, status, organisation, document object key, submitted_at,
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
  and `search_tsv` (a generated column) and `embedding vector(768)`.
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
  action), actor_role, action, target, detail, ip (`inet`). The table is **append-only**: a
  trigger rejects UPDATE and DELETE, and the migration revokes those privileges from the app role.
- `api_usage_hourly`: (api_key_id, hour) → count. This backs `/me/api-usage` and the admin
  "partners" KPI. The hot-path counter lives in Redis and gets flushed to this table.

KPIs and monthly reports become SQL aggregates wherever the data exists: latency, ratings per
verdict, expert turnaround, partners, MAU, languages. The two model-accuracy KPIs (F1 and deepfake
accuracy) come from a small `model_evaluations` table that P4 will write. Until P4 does, it's seeded
with today's numbers.

## 3. pgvector: where and why

The one vector column is `fact_check_reports.embedding`. `apps/web/lib/library.ts` says FR-SEARCH-03
"asks for semantic similarity, which needs embeddings (pgvector, Phase 3)". The Phase 1 stand-in
scores related reports by topic, word overlap, source, language and verdict. Here's the plan for it:

- `GET /fact-checks/{id}/related` ranks by cosine distance, using an HNSW index with
  `vector_cosine_ops`. Suspended reports are excluded. Reports whose embedding is still NULL fall
  back to the `library.ts` lexical score, ported exactly, the same way `scoring.py` ported
  `community.ts`.
- Computing the embeddings is AI-engine work (P4). P3 adds an `EmbeddingProvider` Protocol next to
  `AnalysisProvider`, plus a stub, and a pipeline step that stores whatever the provider returns.
  Like the analysis provider, it has to stay swappable for §10.1 data-protection reasons.
- **The dimension is fixed in the migration.** I'm proposing 768, which fits LaBSE and
  multilingual-e5-base, both reasonable candidates for Ugandan languages. Changing it later means a
  migration plus re-embedding every report. That's cheap while the table only holds seed data, but
  it's still worth deciding on purpose.

I'm deliberately not adding embeddings on submissions ("has this claim already been checked?")
yet. Nothing in the contract uses them, and they're easy to add in P4.

## 4. Weighted CCS and escalation (server-side)

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
    becomes one SQL predicate);
  - enough `content_flags` → a `user-reports` case;
  - pipeline confidence below the `rules.py` low-confidence threshold → a `low-confidence` case.
  Every new case gets `sla_due_at = flagged_at + sla_hours` from settings. Relevant experts get a
  notification.
- **Weight changes.** If an admin changes weights or thresholds, a Celery task recomputes every
  report's score and status in batches and writes one audit entry for the whole run. It doesn't
  open cases retroactively (open question 6).
- **Vote-brigading detector** (feeds `manipulation_signals`): a Celery beat job flags bursts where
  N or more accounts created in the last X days vote the same direction on one report within a
  window. P3 ships the table and this simple heuristic. P4 can replace the heuristic.

## 5. Auth

**Recommendation: opaque server-side sessions, not JWTs.**

- The contract already needs server state for sessions. `GET /me/sessions` lists devices, and
  `DELETE /me/sessions/{id|others}` must revoke them immediately. With JWTs, that means keeping a
  denylist in addition to the tokens, which gives you both halves of the complexity.
- On sign-in we issue 256 random bits, set them as the `zuula_session` cookie (HttpOnly, Secure,
  SameSite=Lax, 30 days with `remember`, otherwise 12 h), and store only the SHA-256 in `sessions`.
  Non-browser core clients send the same token as `Authorization: Bearer …`. The token isn't
  literally a JWT, though, so `openapi.yaml`'s `sessionAuth` description needs a one-word text fix
  (open question 1). The schema itself doesn't change.
- **CSRF:** SameSite=Lax, plus an `Origin` check against `ZUULA_CORS_ORIGINS` on every
  cookie-authenticated request that isn't GET/HEAD.
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
  TOTP would be stronger, but the spec and UI describe SMS or email codes (open question 5).
- **Sign-up verification.** The contract's `POST /auth/sign-up/verify` body only has `code`, which
  can't be tied to an account safely on its own. Sign-up therefore also sets a short-lived HttpOnly
  `zuula_signup` cookie that points at the challenge. The JSON shape doesn't change.
- **Password reset** uses the same challenge table, and completing it revokes every session.
  `forgot-password` always returns 202, so it doesn't reveal which identifiers have accounts.
- **Brute force:** a Redis counter per identifier and per IP allows 5 failed sign-ins per 15 min.
  The contract's `signIn` has no `429` response, so that's a gap (open question 2).
- **OAuth:** a real authorization-code flow with a signed `state` cookie (CSRF plus `next`),
  matched to `oauth_identities`, and a new account for a new identity. OAuth accounts whose role
  needs 2FA still have to pass it.
- **Partner keys:** `zl_live_` + 32 hex characters. We look the key up by prefix and compare
  SHA-256 hashes in constant time. It has to be unrevoked, and the owner has to be active and still
  a journalist or admin. The `read`/`submit` scopes are enforced per route. The rate limit becomes a
  real Redis sliding window per key id (100/h from settings), and `X-RateLimit-*` comes from the
  same counter.

## 6. Submission state moves to Postgres

`app/realtime/submissions.py`'s `load_state` and `save_state` keep their names, but their first
argument becomes a DB session instead of a Redis client. The ADR 0001 interface was the pair of
functions, and only the handle type changes. Redis keeps the pub/sub half (`publish_*`,
`subscribe`) unchanged. When the pipeline finishes, it writes a real `fact_check_reports` row, and
the report-id stub (`fc-new-…`) is replaced by the sequence. The multipart upload path the contract
already declares (`file`, with 413/415 responses) gets built: the file streams to S3 under
`MAX_MEDIA_BYTES` from `rules.py`, and the worker gets real bytes for ClamAV.

## 7. Real adapters

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

## 8. Tests and CI

- CI adds service containers `pgvector/pgvector:pg16` and `redis:7`. The fixtures create a test
  database, run `alembic upgrade head` once per session, and load the seed data (today's
  `app/stubs/*` moved to `app/db/seed/`, which is also `python -m app.db.seed` for local dev).
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

## 9. Delivery: PRs to `main`, in order

1. **DB foundation:** deps, engine/session, Alembic, all models, migration 0001, seed, test
   fixtures, CI services. Routers stay untouched and the suite stays green.
2. **Auth and roles:** sessions, bcrypt, OTP/2FA, OAuth wiring, the `security.py` internals,
   partner keys and the Redis limiter, the audit writer, and the contract-fixture switch.
3. **Content:** submissions, fact-checks/search/related, ratings/CCS/escalation, review,
   notifications (per-user SSE over Redis), and account endpoints.
4. **Admin:** users, moderation, sources, broadcasts (fan-out), settings (with recompute),
   overview and reports aggregates, and audit-log reads. Every mutation writes an audit row.
5. **Real adapters**, one commit each, plus webhook signatures and multipart upload.
6. **Docs:** this ADR rewritten as Accepted, `apps/api/README.md`, and deleting `app/stubs/`.

## 10. Open questions for Noah

1. **Opaque sessions instead of JWTs** (§5). OK to change `sessionAuth`'s description text from
   "bearer JWT" to "bearer session token"? This is a description-only change. Related gap: `Session`
   responses carry no token, so a non-browser client has to read it from `Set-Cookie`. I'd leave
   that as it is unless a non-browser core client actually exists.
2. **Contract gap:** add `429` to `signIn` for lockout? (The same response already exists on
   `resendTwoFactor`.)
3. **`app/core/rules.py` isn't on `main`**, and no other branch has it. Should I wait for P2
   Step 5, or create it in PR 1 with the constants and spec citations and have the P2 session
   rebase onto it?
4. **Embedding dimension 768** (§3): fix it now, or do you want P4's model choice made first?
5. **2FA channel:** SMS or email OTP per the spec and UI, or add TOTP as well?
6. **Rating weight:** use the rater's role *at vote time* (a snapshot, which I'd recommend because
   it's auditable and stable) or their current role? And when admins change weights or thresholds,
   should reports that newly cross a threshold open cases retroactively? I'd recommend no.
7. **Un-suspending:** after a review decision on a `suspended` case, the report is listed again even
   while CCS stays under 20, since the spec says "hidden until reviewed". Is that correct?
8. **Branch:** the brief says `p3/backend-db`, and this session was started on
   `claude/happy-hamilton-0v3via`. Which should the PRs come from?
9. **Hosting-dependent settings:** cookie domain and SameSite depend on whether the API lives on a
   subdomain of the web app (`api.zuula.ug` vs `zuula.ug`). I've assumed it does.
