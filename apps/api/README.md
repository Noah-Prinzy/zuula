# Zuula API

FastAPI implementation of `openapi.yaml`: the core web-app API (`/api/v1/*`) and the public
partner API (`/v1/*`, matching the `/developers` docs). It runs on PostgreSQL + pgvector
with a Celery worker and Redis. The design decisions are in two ADRs:
[`0001`](../../docs/adr/0001-api-architecture.md) (P2: the contract, the pipeline, the adapter
interfaces) and [`0002`](../../docs/adr/0002-p3-backend-and-database.md) (P3: the database,
auth, scoring, admin and the real integrations).

**P4 (the AI verdict engine):** `app/providers/analysis.py`'s `GroqAnalysisProvider` is real
when `GROQ_API_KEY`/`TAVILY_API_KEY` are set (`StubAnalysisProvider` otherwise, unchanged from
P2): a pgvector dedupe check, one Tavily search and one Groq Llama 3.3 70B call per claim, plus
a local RoBERTa AI-text-detector signal — no Claude/Anthropic calls, no agent loop. See
"Verdict engine" below. Deepfake detection (image/video) is out of scope for v1.

## Run it

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

## Test

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

## The contract

`openapi.yaml` is the source of truth. `packages/shared`'s TypeScript types are generated
from it (`npm run generate` there after any change), the partner docs follow it, and the
contract tests enforce it. Change it deliberately, additively where possible, and say so in
the PR.

### Two OpenAPI documents

- **`openapi.yaml`** is hand-authored and is the contract.
- **FastAPI's generated schema** (`/openapi.json`, rendered at `/docs`) is derived from the
  route signatures and isn't used for anything. Don't treat `/docs` as the contract.

### `response_model_exclude_none`

`app.core.router.APIRouter` sets `response_model_exclude_none=True` on every route, matching
how `apps/web/lib/types/*.ts` models optional fields (key absent when unset). A few fields
are the opposite, required *and* nullable (`ApiKey.lastUsedAt`, `ReviewCase.assignee`,
`FactCheckPublic.humanReview`, `CommunityScore.ccs`); those go through small `dump_*()`
helpers in `app/schemas/` that restore the explicit `null`.

## Database

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

## Auth

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

## Submissions and the worker

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

## Integrations

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
[ADR 0003](../../docs/adr/0003-language-provider.md).

The hosted AI provider (`ANALYSIS_PROVIDER`, `ANALYSIS_PROVIDER_REGION`) stays switchable
because sending submissions to a model hosted outside Uganda is an open data-protection
question (ADR 0001) — Groq's hosted inference doesn't resolve that either way.

### Verdict engine (P4)

`app/providers/analysis.py`'s `GroqAnalysisProvider.analyze()`, per claim:

1. **Dedupe**: embeds the claim locally (`app/providers/embedding.py`, all-MiniLM-L6-v2 via
   sentence-transformers, CPU, no key) and looks for a close pgvector cosine-distance match in
   `fact_check_reports.embedding` (≤ `DEDUPE_MAX_COSINE_DISTANCE`, default 0.08). A match is
   reused outright — no Tavily search, no Groq call — which is what keeps a viral claim from
   costing anything the second time it's submitted.
2. Otherwise, one Tavily web search (`app/providers/tavily.py`, free tier) for evidence, then
   one Groq chat completion (`GROQ_MODEL`, Llama 3.3 70B free tier) over the claim and that
   evidence, asked to return the verdict/claims/citations/summary shape in a single JSON
   response — not an agent loop.
3. For text content, an in-process AI-generated-text signal
   (`app/providers/ai_text_detector.py`, a small RoBERTa classifier via `transformers`, CPU, no
   key) is appended to `ai_signals`. Deepfake detection (image/video) is explicitly out of
   scope for v1 — see that module's docstring.

`app/providers/transcription.py`'s `GroqWhisperProvider` does the same for the `transcribe`
step (audio/video), and `app/providers/fetch.py`'s `TrafilaturaArticleFetcher` does real
article extraction for the `fetch` step (URL submissions) — both self-contained, no shared
base class, same as every provider above.

`EMBEDDING_PROVIDER`/`AI_TEXT_DETECTOR_PROVIDER` default to `stub` even when
`ANALYSIS_PROVIDER=groq`: unlike Groq/Tavily, there's no credential to gate the real model on,
and the real one is a model download dev/CI must never trigger by default. Set both to
`sentence-transformers`/`roberta` for the real local models.

## Layout

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
  providers/         AnalysisProvider (the verdict engine: Groq+Tavily, real when
                     GROQ_API_KEY/TAVILY_API_KEY are set), LanguageProvider (Sunbird AI
                     detection and translation), plus fetch/transcription/embedding/
                     ai_text_detector, each with its own real-or-stub switch
  realtime/          Redis clients and submission pub/sub
  worker/            Celery app, the pipeline, messaging, admin tasks, dispatch
migrations/          Alembic (async env)
tests/               contract/, adapters/, db/, pipeline/, core/; conftest.py and dbutil.py
```
