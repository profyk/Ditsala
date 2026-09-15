# ADR 0004: Session model — stateless access tokens, stateful refresh tokens

Status: Accepted (Phase 3)

## Context

docs/DITSALA_MASTER_SPEC.md §16 calls for "short-lived access + rotating refresh tokens," device revocation, and "logout everywhere." Two-factor login (§17) always requires DITSALA Code + a fresh SmartSelfie liveness check for any full server-side authentication (new device, after logout, recovery) — never code alone, and never just a device's local biometric enrollment.

## Decisions

**Access tokens are stateless JWTs** (`core/security.py::create_access_token`/`decode_access_token`), checked only by signature and expiry — `api/v1/deps.py::get_current_user` never queries the `sessions` table. **Refresh tokens are opaque, high-entropy random values, hashed (SHA-256) and stored** in `sessions.refresh_token_hash`, checked against the database on every use.

**Consequence, stated explicitly rather than left implicit**: revoking a device or logging out invalidates the *refresh* token immediately, but any *access* token already issued for that session remains valid until its own expiry (`ACCESS_TOKEN_TTL_MINUTES`, default 15). This is the standard, deliberate tradeoff for stateless access tokens — checking every request against the database would erase most of the point of using a JWT for that half of the pair. It bounds the "how long can a revoked device still act" window to the access-token TTL, not indefinitely.

**Refresh rotation creates a new `sessions` row per rotation** (same `access_token_family_id`, previous row marked `revoked_at`/`revoked_reason="rotated"`), rather than overwriting the hash in place. This is what makes reuse detection possible: presenting an already-rotated-away refresh token is unambiguous evidence of token theft (the legitimate client would only ever hold the *latest* token), and `AuthService.refresh_session` responds by revoking every session sharing that family id, not just the one being replayed.

**Two-factor login is one uniform flow for every full-auth event** (new device, after logout, recovery-adjacent) — `POST /auth/login/start` (code) → Smile ID SmartSelfie job → webhook lands the result → `POST /auth/login/complete` (liveness, checked within `LIVENESS_VALIDITY_MINUTES` = 15 of passing). There is no separate "trusted device, code only" server endpoint — §17 is explicit that a trusted device's *local* biometric enrollment is not a substitute for the DITSALA Code server-side, and routine unlock (Face ID/BiometricPrompt gating a SecureStore-held refresh token) never calls this flow at all, only `/auth/refresh`.

**A latent Phase 2 bug surfaced and was fixed while building this**: `OnboardingService.start_kyc_liveness` never pre-created the `KycFaceVerification` row before returning the SDK token, so the webhook router's user lookup (which depends on that row existing) would have 404'd on every real SmartSelfie webhook. It went undetected because the Phase 2 domain tests called `handle_kyc_liveness_result` directly, bypassing the router's lookup entirely. Fixed to mirror `start_kyc_document_capture`, which already pre-created its row correctly; a webhook-path test would be worth adding for the DOCUMENT_VERIFICATION/SMARTSELFIE cases too (currently only login-liveness's webhook path is exercised indirectly via direct service calls in tests, same boundary as Phase 2 — see `docs/SECURITY_GAPS.md`-adjacent note in `CLAUDE.md`).

## Consequences

- Lockout (`users.failed_code_attempts`/`locked_until`) is checked and incremented only on the *code* factor, not the liveness factor — brute-forcing the DITSALA Code is the relevant threat model there; a failed liveness check after a correct code doesn't lock the account (matches §15's rate-limiting intent without conflating the two factors).
- `AuthService` reuses `KycFaceVerificationRepository`/`kyc_face_verifications` for login liveness (via the new `KycJobType.LOGIN_LIVENESS`), not a dedicated table — the row shape (job id, status, scores, verified_at) is identical to onboarding's SmartSelfie use, and adding a new table for the same data shape wasn't justified.
- Not yet built: the actual webhook HTTP endpoint's signature verification path isn't exercised by any test with a real Smile ID payload (same gap as Phase 2, tracked in `docs/SECURITY_GAPS.md`). Backend logic *reachable after* a valid webhook is fully tested; the boundary at the HTTP edge is not.
