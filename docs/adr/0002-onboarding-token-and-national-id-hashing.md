# ADR 0002: Onboarding session token, and why national_id_hash can't use Argon2id

Status: Accepted (Phase 2)

## Context

Onboarding (spec §9-15) happens before a full authenticated session exists (§16-17, Phase 3), but still needs a way to identify "which signup is this request for" across several sequential calls (verify email, verify phone, KYC, next-of-kin, set code).

Separately, `users.national_id_hash` (§4.1) has a uniqueness constraint — it exists specifically to catch duplicate signups against the same national ID.

## Decisions

**Onboarding token, not a raw user id in the URL.** `POST /onboarding/signup` returns a short-lived (2h) signed JWT (`core/security.py::create_onboarding_token`) instead of the new user's UUID. Every subsequent onboarding call requires it as a bearer token. A raw user id in a pre-auth URL is an IDOR: anyone who learned another signup's UUID (log line, referrer, screenshot) could confirm their email code, submit KYC results, or set their DITSALA Code. This token is the minimum viable session for the phase of the flow that happens before §16-17's real session exists.

**`hash_national_id` is HMAC-SHA256, not Argon2id.** `core/security.py::hash_secret` (Argon2id) is correct for the DITSALA Code and email verification codes — we only ever *verify* those, never compare two hashes for equality. `national_id_hash` is different: it must be deterministic so the DB's uniqueness constraint can actually catch a duplicate signup. Argon2id is salted and non-deterministic by design, so it can never do this — using it here would silently defeat the uniqueness check while looking secure. HMAC-SHA256 keyed by a server-side pepper (`national_id_pepper`, deliberately a separate secret from `jwt_secret` — key separation, so rotating one doesn't silently affect the other) is deterministic and still resists a brute-force dictionary attack on national ID formats better than an unkeyed hash would.

## Consequences

- The onboarding token has its own `type: "onboarding"` claim so it can never be replayed as (or confused with) a real Phase 3 access/refresh token, even though both are HS256 JWTs signed with the same `jwt_secret`.
- `national_id_pepper` needs the same secrets-management care as any other credential (§7.7) — it is not optional or cosmetic; losing it means every stored `national_id_hash` becomes unverifiable against a freshly-submitted ID, and rotating it invalidates the uniqueness check's ability to match pre-rotation signups.
- API-level tests (`app/tests/test_api_onboarding.py`) inject stub providers via `dependency_overrides` rather than exercising real Twilio/Smile ID/Resend — those three remain code-complete but not live-verified in this environment (no vendor accounts); see `docs/SECURITY_GAPS.md` and `CLAUDE.md` "Phase 2" notes.
