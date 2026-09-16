# DITSALA Documentation

Engineering-facing setup, architecture, and deployment reference. For the full product/engineering specification this implements, see `docs/DITSALA_MASTER_SPEC.md` — that document is the source of truth for locked decisions; this one is the practical "how to actually run it" companion. `CLAUDE.md` tracks what's been built phase by phase and any environment-specific quirks hit along the way; read that first if you're picking this codebase up mid-flight.

## 1. Architecture overview

```
apps/
  mobile/      Expo Router + NativeWind (React Native) — the end-user app
  admin/       Next.js (App Router) + Tailwind — internal admin panel
backend/       FastAPI (Python), SQLAlchemy async ORM, Alembic migrations
packages/
  ui-tokens/   Shared design tokens (colors, type scale) consumed by both TS apps
infra/         docker-compose.yml — Postgres, Redis, coturn (TURN), Mailpit (dev SMTP)
docs/          This spec, ADRs, policy documents, security gap register
```

**Backend**: every external dependency (KYC, OTP, email, push, SMS, storage) sits behind a Python `Protocol` interface in `app/domain/*/interfaces.py`, with a real production adapter and a `Sandbox*` adapter in `app/services/*/`, selected purely by environment variable via `app/services/factory.py`. This is the single most important pattern in the backend — never add a new external call without following it.

**Data model**: PostgreSQL via SQLAlchemy async models (`app/models/`) and a matching repository per aggregate (`app/repositories/`). Every schema change is an Alembic migration — no manual DDL, ever. Data is classified by sensitivity (`app/domain/classification.py`) and enforced via separate Postgres roles with column-level grants plus row-level security, not just application-layer checks.

**Messaging/E2EE**: the backend is deliberately crypto-agnostic — it stores and relays public key material and ciphertext it can never decrypt (Signal Protocol via libsignal on-device). See `docs/adr/0005-e2ee-native-module-gap.md`.

**Realtime transport**: a single authenticated WebSocket connection per device carries messaging events *and* WebRTC call signaling (offer/answer/ICE relay) — see `app/services/realtime/websocket_manager.py`.

**Scheduled maintenance**: retention sweeps, SOS escalation, and the account-deletion cascade run via APScheduler inside the same backend process (`app/tasks/scheduler.py`) — see that module's docstring and `app/tasks/README.md` for the single-instance caveat and the Redis-backed evolution path.

## 2. Local setup

### Prerequisites

- Python 3.12+, [uv](https://github.com/astral-sh/uv)
- Node.js + [pnpm](https://pnpm.io/)
- Docker (for `infra/docker-compose.yml`) — or see "Without Docker" below

### Standard path (with Docker)

```bash
cd infra && docker compose up -d        # postgres, redis, mailpit, coturn
cd backend && uv venv && uv pip install -e . --group dev
cp .env.example .env                     # fill in secrets — see .env.example's comments
alembic upgrade head
uvicorn app.main:app --reload
pnpm install                             # from repo root — ui-tokens/shared-types for both TS apps
```

Backend tests: `cd backend && pytest` (needs a running Postgres — see `.env`'s `DATABASE_URL`). Lint/type-check: `ruff check app/` and `mypy app/`.

Admin panel: `cd apps/admin && pnpm dev` (needs the backend running; copy `.env.example` first for `NEXT_PUBLIC_API_URL`).

Mobile: `cd apps/mobile && pnpm start` — **always via an EAS development build, never Expo Go** (locked decision, see CLAUDE.md's decision table — several native modules, including calling and eventually libsignal, aren't available in Expo Go).

### Without Docker

This codebase has been developed and verified against real Postgres without Docker, using a portable native binary (see CLAUDE.md's "Local dev" section for the exact non-superuser role bootstrapping this needs) — useful on a machine where Docker itself isn't available. Mailpit and a local S3-compatible store (MinIO) can similarly run as standalone binaries; see `docs/SECURITY_GAPS.md`'s entry on local S3 storage for the one piece not yet exercised this way.

## 3. Environment variables

Each app has its own `.env.example` documenting every variable it needs — provider credentials, JWT secrets, database URLs, feature-flag-style toggles (e.g. `invite_only_mode` is a runtime `system_config` row, not an env var — see the admin panel's System Configuration screen). Never commit a real `.env` file; `.gitignore` already excludes `.env*` and key material.

## 4. Deployment runbook (staging/production)

This is a runbook outline for whoever provisions a real environment — no staging/production environment has actually been stood up in this repository's history to date; treat this as the plan, not a record of what's running.

1. **Database**: provision managed Postgres (Supabase, or any Postgres 15+). Run `alembic upgrade head` against it before first deploy. Create the classification-scoped DB roles (the classification migration does this) and confirm RLS policies are active (`app/tests/test_rls.py` is the reference for what "working" looks like).
2. **Secrets**: generate fresh `JWT_SECRET`/`NATIONAL_ID_PEPPER` values for production — never reuse a value that appeared in a `.env` during development. Store real provider credentials (Smile ID, Twilio, Resend, S3) in your platform's secret manager, not in environment files checked into anything.
3. **Provider DPAs**: confirm signed Data Processing Agreements exist for Smile ID, Twilio, and the email provider before enabling real credentials against real user data — this is a launch blocker per `docs/DITSALA_MASTER_SPEC.md` §34.3, not a nice-to-have.
4. **coturn**: stand up a real TURN server for WebRTC calling (`infra/docker-compose.yml` scaffolds this) — without it, calls between users on different, NAT-restrictive networks will fail to connect.
5. **Backend**: deploy as a standard ASGI app (uvicorn/gunicorn behind a reverse proxy). Because scheduled sweeps run in-process (`app/tasks/scheduler.py`), **run exactly one backend instance until that module moves to a distributed scheduler** — see `docs/SECURITY_GAPS.md`.
6. **Redis**: provision before scaling past one instance — `InMemoryRateLimiter` and the WebSocket `ConnectionManager` are both documented single-instance placeholders for what should become Redis-backed state.
7. **Mobile**: build via EAS (`eas build`), never distribute an Expo Go bundle. Confirm push notification credentials (APNs/FCM) are configured in the EAS project before a production build.
8. **Admin panel**: deploy the Next.js app behind authentication that at minimum matches its own login/MFA (§29) — it should never be reachable without going through `AdminAuthService`'s flow.
9. **Monitoring**: none is wired up in this codebase yet — structured logging (`structlog`) is in place and redaction-aware per the classification registry, but shipping logs to an aggregator and alerting on them is an operational setup step for whoever deploys this, not something the application code does itself.

## 5. Where to look next

- `docs/DITSALA_MASTER_SPEC.md` — the full spec, section by section.
- `docs/adr/` — architecture decision records for every non-obvious call made while building this.
- `docs/SECURITY_GAPS.md` — everything shipped behind an interface because it couldn't yet be built to the full standard, and what closing each gap actually requires.
- `CLAUDE.md` — phase-by-phase build log, kept current at the end of every phase.
