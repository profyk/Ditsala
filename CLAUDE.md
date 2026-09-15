# CLAUDE.md — DITSALA

Working notes for whoever (human or Claude) picks up this repo next. Full detail lives in `docs/DITSALA_MASTER_SPEC.md` (v1.0, finalized) — this file is the fast-orientation summary, kept current as phases complete.

## Current phase

**Phase 0 — Foundation: complete.** Monorepo tooling (pnpm + Turborepo, uv for the backend), `docker-compose.yml` (Postgres/Redis/coturn/Mailpit), CI (GitHub Actions: lint/type-check/test for both the TS workspace and the backend), `packages/ui-tokens` (Ditsala palette + type scale), backend skeleton with a working `/api/v1/health` endpoint, and the first Alembic migration (`pgcrypto` extension) are in place.

**Phase 1 — Data model: complete.** All 34 tables from spec §4 as Alembic migrations (`631a559a0977` core schema + `1bcfa1c65e5e` classification/RLS), SQLAlchemy models for every table (`backend/app/models/`), the §5 data-classification registry as its own module (`backend/app/domain/classification.py`), four Postgres DB roles (`app_backend`, `app_admin_readonly`, `app_admin_kyc_reviewer`, `app_maintenance`) with column-level grants matching P0-P3 classification, and RLS policies on `messages`/`conversation_members`/`location_shares`/`location_pings` — all proven against a real Postgres via integration tests, not just declared. A full repository layer (`backend/app/repositories/`) covers every aggregate.

**Phase 2 — Onboarding & identity: backend complete, mobile screens not yet started.** `EmailProvider` (Resend real + `SandboxEmailProvider` over local SMTP), `OtpProvider` (Twilio Verify real + sandbox-credential variant), `KycProvider` (Smile ID real + sandbox-host variant) — all behind `domain/onboarding/interfaces.py`, selected only via `services/factory.py` reading env vars. `domain/onboarding/service.py` implements the full §14 state machine up to `pending_code` (device+key registration to reach `active` is Phase 3's job, deliberately not built here). API routes under `/api/v1/onboarding/*` plus a Smile ID webhook endpoint, gated by a short-lived onboarding JWT rather than a raw user id in the URL (see ADR 0002 — avoids an IDOR in the pre-auth part of the flow). Argon2id for the DITSALA Code and email codes, a separate deterministic HMAC hash for `national_id_hash` (see ADR 0002 for why Argon2id would silently break the uniqueness constraint there).

31 backend tests pass, including a real one: `SandboxEmailProvider` was verified against an actual running Mailpit instance (SMTP delivery + API-confirmed receipt), not just code review. Twilio Verify and Smile ID adapters are code-complete but **not live-verified** — no vendor account exists in this environment; see `docs/SECURITY_GAPS.md` for the Smile ID field-accuracy caveat specifically.

**Mobile**: `apps/mobile` is a real Expo Router + NativeWind app (Expo SDK 57), not a stub — scaffolded via `create-expo-app`, joined into the pnpm workspace (see ADR 0003 for the `node-linker=hoisted` + Metro symlink config that took to make that work with React Native), consuming `@ditsala/ui-tokens` for its dark/gold palette. Full onboarding screen flow wired to the real backend API: welcome → signup → verify-email → verify-phone → kyc-document → kyc-liveness → next-of-kin → set-code → complete. The DITSALA app icon (`docs/brand/`) is wired in for iOS, Android (adaptive + monochrome), and web favicon.

**Known mobile gap** (ADR 0003): the KYC screens request real backend jobs/tokens but have no native capture UI — the Smile ID mobile SDK needs a config plugin and native iOS/Android build tooling (Xcode, Android Studio, EAS) this environment doesn't have. A user cannot progress past `pending_kyc_document` through the app UI alone yet. Not a security gap (no control is weakened) — a feature-completeness one, for whoever picks up the native SDK integration next.

**Not runtime-verified**: no simulator, physical device, or EAS build was available to actually launch the app. Verified: `tsc --noEmit`, ESLint, and Jest (16 tests: validation logic, the onboarding context, `Button`/`TextField`) all pass — including `Button`/`TextField` importing colors from `@ditsala/ui-tokens` directly, which confirms the pnpm workspace symlink + `node-linker=hoisted` + Metro `unstable_enableSymlinks` setup (ADR 0003) resolves correctly through the type-checker, linter, and Jest's module resolution. What's still unverified is Metro's own bundler at actual `expo start`/EAS-build time — smoke-test that on a machine with Xcode/Android Studio before trusting this further.

Not yet built in Phase 2: the breach-corpus check for the DITSALA Code (`docs/SECURITY_GAPS.md`).

**Phase 3 — Authentication & Sessions: complete (backend + mobile).** `domain/auth/service.py` (`AuthService`) owns the `pending_code` → `active` transition (device registration completes onboarding — Signal key upload itself is Phase 4's job) and two-factor login (§17): `POST /auth/login/start` (DITSALA Code) → Smile ID SmartSelfie liveness job → webhook lands the result → `POST /auth/login/complete` (checked within a 15-minute validity window). One uniform login flow handles every full-auth event (new device, after logout, recovery-adjacent) — there is no "trusted device, code only" server path, per §17.

Stateless short-lived access JWTs (`ACCESS_TOKEN_TTL_MINUTES`) + stateful rotating refresh tokens (`POST /auth/refresh`) with reuse detection — replaying an already-rotated-away refresh token revokes the entire session family, not just that token (see ADR 0004 for the full session model and the deliberate access-token revocation-latency tradeoff this implies). Device registry (`GET /auth/devices`, `DELETE /auth/devices/{id}`), `POST /auth/logout` (one session) and `/auth/logout-all` (every session), code-attempt lockout with escalating duration, and login-attempt logging are all in place.

A real Phase 2 bug was found and fixed while building this: `OnboardingService.start_kyc_liveness` never pre-created the `KycFaceVerification` row the webhook router's user-lookup depends on — see ADR 0004. 48 backend tests pass total (11 new domain tests, 5 new API tests for Phase 3). The Smile ID webhook HTTP endpoint's signature verification still has no test with a real payload (`docs/SECURITY_GAPS.md`) — same vendor-account limitation as Phase 2.

**Phase 3 mobile: complete.** `lib/session.ts` (SecureStore-backed access/refresh token storage) and `lib/biometric.ts` (expo-local-authentication) implement routine unlock exactly as §17 describes it: the biometric prompt never leaves the device and only gates access to the stored refresh token — the actual server call is a plain `/auth/refresh`, never a fresh authentication. `app/index.tsx` now checks for a stored session on launch and offers "Unlock" (biometric + refresh) instead of "Get Started" when one exists, falling back to a full login if the refresh token was rejected. `app/login.tsx` implements the full two-factor flow (code, then liveness-check polling) for new devices/after logout. `app/onboarding/complete.tsx` now actually calls `/auth/complete-onboarding` instead of just displaying state. `app/home.tsx` is a placeholder authenticated screen (Phase 4+ builds the real app) that exercises the device registry and logout/logout-everywhere end to end.

25 mobile tests pass (9 new: session storage and biometric-gating logic, both with the native modules mocked — `jest.mock` factories needed their captured variables renamed to a `mock`-prefixed convention, a real Jest/babel hoisting restriction hit while writing these). Same runtime-verification boundary as the rest of Phase 2/3 mobile: `tsc`/ESLint/Jest all pass; nothing has been launched on a simulator/device.

**Phase 4 — E2EE Messaging: backend complete, mobile plumbing only (no chat UI).** See `docs/adr/0005-e2ee-native-module-gap.md` — this is the most important ADR in the repo right now. The backend's role in the Signal Protocol is inherently crypto-agnostic (it stores/relays public key material and opaque ciphertext, never decrypts, by design per §7.3), so `domain/messaging/service.py` and the `/api/v1/messaging/*` REST + WebSocket routes are real, fully tested, production-shaped code: key registration (identity key, signed prekeys with rotation, one-time prekeys with consume-once semantics), prekey-bundle retrieval for X3DH, 1:1 and group conversations, message send/list/edit/delete with idempotency via `client_message_id`, delivery/read receipts, disappearing messages (`purge_expired_messages`, not yet scheduled — Phase 8's job), pin/mute/archive, group Sender Key distribution (relay only), media (presigned S3/MinIO-compatible upload/download via `StorageProvider`), block/unblock, and an in-memory `ConnectionManager` for realtime WebSocket delivery (Redis pub/sub is the documented multi-instance evolution path, not needed at this scale yet).

**What is deliberately not built**: the libsignal native module itself (needs Xcode/Android Studio/Rust — none available here) and any mobile chat UI. Building message screens against a stubbed "encryption" would look like working E2EE without being any such thing — exactly the "weaker fallback shipped silently" Working Rule 6 forbids. Mobile Phase 4 is limited to non-crypto plumbing only: `lib/messaging-api.ts` (REST client for everything above), `lib/messaging-ws.ts` (WebSocket event wrapper), and `lib/base64.ts` (dependency-free — `btoa`/`Buffer` availability wasn't verified in this RN runtime).

A schema gap surfaced and was fixed: the original §4 `messages` table had no column for replies, needed for Phase 4's "replies" feature — added via migration `7cb71e7570d4`. 74 backend tests pass total (18 new messaging-service tests, 8 new API tests). 42 mobile tests pass total (8 new: base64 round-trip correctness, WebSocket event dispatch/subscription with a mocked global `WebSocket`). `docs/SECURITY_GAPS.md` now leads with the libsignal gap as the single highest-priority item in the codebase — it blocks the product's core function, unlike the onboarding-vendor-credential gaps.

**Phase 5 — Circle: complete (backend + real mobile UI).** No native-crypto blocker here, unlike Phase 4 — everything in this phase is real, both ends. `domain/circle/service.py` (`CircleService`) implements §22-24: contact requests (send/accept/decline/list, both sides land at `unverified` tier on send so the pending relationship is visible before either side can message), tier transitions (`unverified` → `verified` on mutual accept → `trusted` via one-sided safety-number confirmation, §23), block/report (moved out of `MessagingService`, which now only reads `BlockRepository` for its own messaging-capability check — block's fuller §24 side effects, hiding the blocker from the blocked user's list and silently dropping any pending request, belong to Circle, not messaging), and invitations (`system_config.invite_only_mode` now actually gates `OnboardingService.start_signup`, redeeming a real `Invitation` row with a `expires_at` — added via migration `6511f2a9f7f2` since the original §4 schema never put a TTL on invite codes despite spec text calling them "time-bounded").

A real cross-phase integration was wired in, not just documented: `MessagingService.start_direct_conversation` now requires a `verified`/`trusted` Circle contact between the two users (§22 — "basic messaging unlocked once both sides accept"), and `MessagingService.register_identity_key` demotes any `trusted` contact back to `verified` (clearing `safety_number_verified_at`) when a device's identity key actually changes vs. an idempotent resend — §23's "does not silently trust re-keyed contacts," now enforced in code, not just spec prose. This touched every Phase 4 test that creates a direct conversation; all were updated to set up a verified `Contact` row first rather than relaxing the new gate.

`GET /auth/me` was added (`CurrentUserResponse`) — a small, real gap: the mobile client had no way to learn its own user id for Circle's add-contact link/QR flow without decoding its own JWT locally.

**Deliberately not built in mobile Phase 5**: an on-screen "safety number" display (two fingerprint strings a user compares to verify a contact). Per the same principle as ADR 0005, fabricating that display without real Signal identity keys would be exactly the "looks encrypted without being any such thing" problem — so `app/circle/index.tsx`'s "Verify in person" action is a real, honest attestation (it really does call `POST /circle/safety-number/verify` and really does promote the contact to `trusted`) with copy that doesn't claim to show a cryptographic fingerprint. Also not built: QR code *generation* (rendering own code as a scannable image) — no QR-generation library was added, to avoid a new native dependency on this memory-constrained dev machine; QR *scanning* (via `expo-camera`) and link-sharing (native `Share` sheet + `expo-linking` deep link, both already-installed dependencies) are real and cover the same `ditsala://circle/add?userId=<id>` flow either way. See `docs/SECURITY_GAPS.md`.

99 backend tests pass total (25 new: Circle service + API tests, plus onboarding invite-only-mode tests and the auth `/me` test). 47 mobile tests pass total (5 new: `circle-link.test.ts`'s pure link-parsing logic — the screens themselves aren't unit-tested, matching the existing convention that `app/*.tsx` screens are verified via `tsc`/ESLint only, not Jest).

Not yet started: Phase 6 onward (location/SOS/calls, admin panel, recovery/hardening). See "Execution order" in the spec — build in order, don't skip ahead.

`apps/admin` is intentionally still a stub package (just enough `package.json` for the workspace and CI to resolve) — it gets real content in Phase 7, not before.

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
`docker compose up` itself (the actual compose file, with Redis/coturn/Mailpit alongside Postgres) has not been run — worth doing once on a machine with Docker to confirm it's typo-free, but the migrations/RLS/repository logic itself is already proven against real Postgres, not just assumed to work under Docker. Mailpit was similarly run as a standalone binary (`axllent/mailpit` GitHub release, SMTP on 1025 / API+UI on 8025) rather than via Docker, and `SandboxEmailProvider` was verified against it for real.
