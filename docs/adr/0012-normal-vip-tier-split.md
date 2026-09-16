# ADR 0012: Normal (free, no KYC) vs. VIP (paid, KYC-verified) account tiers

Status: Accepted (Phase 8, foundation only — see "Not yet built" below)

## Context

Every account previously went through mandatory KYC (document + SmartSelfie liveness) before reaching `active` — the product's original "every account is identity-verified" premise (see `docs/KYC_POLICY.md`). The user explicitly asked to split this: a free **normal** tier with no identity verification, and a paid **VIP** tier that keeps full KYC plus additional privacy/trust features, framed around giving public figures (the stated example: politicians) a way to communicate with a verified, trusted identity without that verification being a barrier for every ordinary user.

## Decision

**`users.account_tier`** (`normal` | `vip`, default `normal`) is the new source of truth for which authentication/onboarding path an account uses:

- **Onboarding**: `OnboardingService.confirm_phone_verification` now branches on tier — `normal` goes straight to `pending_next_of_kin`, skipping `pending_kyc_document`/`pending_kyc_liveness` entirely. Every real signup today creates a `normal` account (`start_signup` has no tier parameter) — VIP is reachable only via upgrade, not at signup. The two KYC states remain in the schema and `OnboardingService` unchanged, ready for a `vip` account to pass through them (currently only reachable by a test manually setting the tier, or by `VipUpgradeService` reusing the same methods — see below).
- **Login (§17)**: `AuthService.start_login` now also branches on tier. A `vip` account keeps the original two-factor flow (DITSALA Code, then a fresh liveness check) unchanged — it has real Smile ID biometric enrollment to check that capture against. A `normal` account has no such enrollment, so there is nothing for a liveness check to verify — it authenticates with the DITSALA Code alone, and `start_login` returns a session directly. `LoginStartResult`/`LoginStartResponse` carry a `requires_liveness` discriminator so the client (and the API response shape) can tell which path a given login took.
- **KYC purpose tagging**: `kyc_documents.purpose`/`kyc_face_verifications.purpose` (`onboarding` | `vip_upgrade`) let the same two tables, and the same Smile ID job-handling machinery, serve both an in-onboarding VIP signup (if ever exposed) and a post-active VIP upgrade — the webhook router needs to know which flow a completed job belongs to, since an upgrading user's `account_state` stays `active` throughout (unlike onboarding, it never moves through the `pending_*` states at all).
- **`vip_subscriptions`**: tracks the paid-upgrade lifecycle (`pending_payment` → `awaiting_kyc` → `active`, or `cancelled`/`expired`/`failed`) independently of `account_state`, against a Stitch payment reference.

## What's already real and tested

Migration `ee91b3f2d954` (the four schema changes above); the onboarding fork (`test_onboarding_service.py`, `test_api_onboarding.py`); the login fork including a real single-factor session issuance path (`test_auth_service.py`, `test_api_auth.py`).

## Not yet built (tracked in `docs/SECURITY_GAPS.md`)

- `VipUpgradeService` itself (payment initiation → KYC → tier flip) — the schema and KYC-purpose tagging exist to support it, but the service, its API routes, and the Stitch payment adapter are the next slice.
- The stated VIP privacy feature (hiding phone number from non-Circle/non-VIP viewers).
- VIP-to-VIP automatic trusted messaging ("private space").
- A visible verified badge anywhere in the UI.

## Consequences

- Every existing test that exercises the KYC-required onboarding/login path now has to opt a test user into `account_tier="vip"` explicitly (either via a direct DB write in a fixture, or a future `VipUpgradeService` call) — real signups can no longer reach those states by default. This is intentional: it makes "this test is exercising VIP-only behavior" visible in the test itself rather than implicit.
- `pending_kyc_document`/`pending_kyc_liveness` are, for now, unreachable from any public API (no signup path sets `account_tier="vip"` before phone confirmation) — they remain fully implemented and tested, ready for `VipUpgradeService` to reuse the exact same `OnboardingService` methods once that service exists, or for a future "choose VIP at signup" flow if that's ever wanted.
