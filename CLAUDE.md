# CLAUDE.md — DITSALA

Working notes for whoever (human or Claude) picks up this repo next. Full detail lives in `docs/DITSALA_MASTER_SPEC.md` (v1.0, finalized) — this file is the fast-orientation summary, kept current as phases complete.

## Current phase

**Phase 0 — Foundation: complete.** Monorepo tooling (pnpm + Turborepo, uv for the backend), `docker-compose.yml` (Postgres/Redis/coturn/Mailpit), CI (GitHub Actions: lint/type-check/test for both the TS workspace and the backend), `packages/ui-tokens` (Ditsala palette + type scale), backend skeleton with a working `/api/v1/health` endpoint, and the first Alembic migration (`pgcrypto` extension) are in place.

**Phase 1 — Data model: complete.** All 34 tables from spec §4 as Alembic migrations (`631a559a0977` core schema + `1bcfa1c65e5e` classification/RLS), SQLAlchemy models for every table (`backend/app/models/`), the §5 data-classification registry as its own module (`backend/app/domain/classification.py`), four Postgres DB roles (`app_backend`, `app_admin_readonly`, `app_admin_kyc_reviewer`, `app_maintenance`) with column-level grants matching P0-P3 classification, and RLS policies on `messages`/`conversation_members`/`location_shares`/`location_pings` — all proven against a real Postgres via integration tests, not just declared. A full repository layer (`backend/app/repositories/`) covers every aggregate.

Not yet started: everything in Phase 2 onward (onboarding/KYC, auth, E2EE messaging, Circle, location/SOS/calls, admin panel, recovery/hardening). See "Execution order" in the spec — build in order, don't skip ahead.

`apps/mobile` and `apps/admin` are intentionally stub packages right now (just enough `package.json` for the workspace and CI to resolve) — they get real content in Phase 2 and Phase 7 respectively, not before.

## Brand (non-negotiable in all UI/copy work)

- Name: **DITSALA** (caps in the wordmark, "Ditsala" in prose). Tagline: **Speak with Confidence.** Supporting line: *Your trusted circle.*
- Verified contacts are a **Circle**, never "friends list" or "contacts" in UI copy. Trust tiers shown to users: **Unverified → Verified → Circle**, plus **Blocked** (backing enum may stay `TRUSTED`).
- The auth secret is the **DITSALA Code** — never "password" anywhere user-facing.
- Visual identity: dark-first, restrained, private-members'-club. Serif/high-contrast display type (`Fraunces` in `ui-tokens`) + clean grotesk UI type (`Inter`). Single accent (gold, `#C8A059` dark / `#9C7A34` light) reserved for CTAs and the Circle trust-tier badge. No bubble/playful chrome, must not resemble WhatsApp/Telegram/Signal.

## App icon

Source design lives in `docs/brand/` (a bold geometric "D" monogram, gold-on-dark, drawn programmatically via `generate_icon.py` — not hand-drawn, not a font glyph). Colors pulled directly from `ui-tokens`. Gets copied into `apps/mobile/assets/` once Phase 2 scaffolds Expo — see `docs/brand/README.md` for the exact wiring. An earlier candidate (blue/purple gradient chat-bubble mark) was rejected for conflicting with the brand rules below.

## Locked decisions (do not revisit without asking)

| Area | Decision |
|---|---|
| KYC / liveness / face match | Smile ID (Document Verification + Enhanced KYC + SmartSelfie), behind `KycProvider` |
| Phone OTP | Twilio Verify, behind `OtpProvider` |
| Email | **Resend**, behind `EmailProvider` (settled, see spec "Settled" section) |
| E2EE | Signal Protocol via libsignal, native Expo module — no JS-only or hand-rolled crypto |
| Mobile build | Expo + EAS development builds from day one; Expo Go is never a target |
| Calls | WebRTC, self-hosted coturn for TURN only, DTLS-SRTP end-to-end; **group calls out of v1 scope** (settled) |
| Database | Postgres on Supabase; backend connects via a dedicated role, mobile never talks to Supabase directly |
| Cache/realtime/queues | Redis |
| Media storage | S3-compatible, private, signed short-lived URLs, client-side encrypted before upload |
| Push | Expo Notifications → APNs/FCM, generic payloads only |
| Admin | Next.js (App Router) + TypeScript + Tailwind |
| Monorepo | pnpm workspaces + Turborepo (TS apps); uv (backend, chosen over Poetry) |

## Security non-negotiables (spec §7 — do not weaken these while implementing)

1. No custom cryptography anywhere.
2. No plaintext DITSALA Codes, tokens, or biometric templates ever stored.
3. **No admin path, ever, can retrieve decrypted message content** — true even for support/law-enforcement scenarios.
4. Every external provider behind an interface with a real adapter + a `Sandbox*` adapter using the provider's own test mode. Selection by env var only — never a hand-rolled fake in a production code path.
5. Every schema change is an Alembic migration. No manual DDL, anywhere, ever.
6. Anything that can't yet be built safely is isolated behind an interface and logged in `docs/SECURITY_GAPS.md`, not shipped with a silent weaker fallback.
7. Secrets only via env vars; `.env.example` (no real values) in every app; `.env*` and key material gitignored (already done, see `.gitignore`).

## Compliance (spec §34 — resolved, not open questions)

- **KYC/biometric imagery: zero retention in DITSALA-controlled storage, ever.** Only `smile_id_job_id` + a non-reversible `result_summary` (scores/decision) are stored. This is a POPIA §14/§26-27 driven decision — don't reintroduce a "store the image with a TTL" pattern without revisiting the spec.
- Cross-border transfers to Smile ID/Twilio/Resend require signed DPAs with SCCs (or equivalent) — **launch blocker for Phase 2**, tracked in `docs/SECURITY_GAPS.md` until each is signed.
- SOS overriding standing location-consent settings is a deliberate, documented lawful-basis exception (POPIA §11(1)(d)), not a gap — don't "fix" it by adding a consent prompt into the SOS escalation path.
- Concrete retention numbers (location pings, audit log, login attempts, account deletion cascade) are fixed in spec §34.2 — `DATA_RETENTION.md` (Phase 8) implements them, doesn't re-derive them.

## Working rules

- Never mock in a production code path — real adapter + provider-sandbox adapter only.
- Tests are part of every phase, not a follow-up. Backend: pytest against real Postgres. Mobile: Jest + RNTL. Admin: Vitest + Playwright.
- Commit at the end of every phase; non-obvious decisions get a `docs/adr/` entry.
- Stop and ask before: switching a locked decision, choosing between two unlisted providers, or anything touching key-management design.
- This file gets updated at the end of every phase — don't let it drift from what's actually built.

## Local dev

```
cd infra && docker compose up -d        # postgres, redis, mailpit, coturn
cd backend && uv venv && uv pip install -e . --group dev
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
pnpm install                             # from repo root, for ui-tokens/shared-types
```

Verified: `alembic upgrade head` has been run end-to-end against a real PostgreSQL 18.6 (not just SQLite/mocked) — `pgcrypto`, all 34 tables from spec §4, the classification DB roles + column grants, and RLS on `messages`/`conversation_members`/`location_shares`/`location_pings` are all confirmed working via real integration tests (`app/tests/test_rls.py`, `app/tests/test_repositories.py`), including a genuine infinite-recursion bug in one policy (fixed with a `SECURITY DEFINER` helper function) and a NOT-NULL bug from several columns having only a Python-side ORM default with no `server_default` (also fixed). Docker itself is not installed on the machine this was built on, so verification used a portable native PostgreSQL binary (`theseus-rs/postgresql-binaries` release, since EnterpriseDB's own installer CDN blocked this environment's IP) running on `127.0.0.1:5432`, with a **hand-created, non-superuser** `ditsala` role (unlike the official Postgres Docker image, whose `POSTGRES_USER` bootstraps as a superuser automatically) — so this environment needed one-time manual bootstrapping that `docker-compose.yml` and CI do **not** need:
```
ALTER ROLE ditsala WITH CREATEROLE BYPASSRLS;   -- only for a hand-rolled non-superuser role
```
`docker compose up` itself (the actual compose file, with Redis/coturn/Mailpit alongside Postgres) has not been run — worth doing once on a machine with Docker to confirm it's typo-free, but the migrations/RLS/repository logic itself is already proven against real Postgres, not just assumed to work under Docker.
