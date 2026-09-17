# ADR 0014: Phone + PIN signup for normal tier; email + PIN for VIP; no explicit logout for normal

Status: Accepted — a further, explicit narrowing of ADR 0012's normal/VIP split, by direct user instruction.

## Context

ADR 0012 already made normal-tier accounts skip KYC and liveness. The user went a step further: normal-tier signup should be phone-number-only (country code + a PIN), matching how mass-market messaging apps (WhatsApp) onboard — no email, no DITSALA Code as originally shaped (an 8+ character alphanumeric secret), no date of birth, no national ID, no next-of-kin collection at signup. Returning to the app should feel like unlocking a phone (biometrics or a PIN), not "logging in." VIP keeps a heavier, deliberate model: email identifies the account, a PIN plus the existing liveness re-check gates entry, and explicit logout/logout-everywhere stays available — consistent with VIP being the tier that actually promises verified identity.

## Decision

**Schema**: `User.email`, `User.date_of_birth`, `User.national_id_hash` become nullable — a normal-tier phone signup sets none of them. Postgres's unique index on each already tolerates multiple `NULL`s, so no constraint conflict. `national_id_hash`/`date_of_birth` get collected for real the first time a normal account actually needs them: VIP upgrade (which already requires a KYC document capture — the natural place to also ask for what a full identity check needs).

**Normal-tier signup** (`OnboardingService.start_phone_signup`): phone (E.164) → OTP (existing `OtpProvider`, unchanged) → a 6-digit numeric PIN → display name → `active`. Skips `pending_email`, `pending_kyc_document`/`pending_kyc_liveness` (already true per ADR 0012), and now `pending_next_of_kin` too — `add_next_of_kin` already supports being called once `active` (it always has), so next-of-kin becomes a real, but optional, later addition rather than a mandatory gate. **This is a genuine, disclosed safety trade-off**: SOS escalation (§26) notifies next-of-kin by SMS — a normal-tier account with none set only escalates to trusted Circle contacts. Tracked in `docs/SECURITY_GAPS.md`, not hidden.

**PIN validation** (`core/security.py`): a new `validate_pin_strength` (exactly 6 digits) and `is_weak_pin` (rejects sequential runs, all-same-digit, and a small common-PIN blocklist — the numeric equivalent of HIBP breach-checking, which doesn't meaningfully apply to a 6-digit space). `OnboardingService.set_ditsala_code` branches on `account_tier`: `normal` uses the PIN rules above, `vip` keeps the original `validate_ditsala_code_strength` + HIBP check unchanged. The column stays `ditsala_code_hash` — no rename, this is a validation-shape difference, not a new secret type.

**Login is unchanged** — `AuthService.start_login`'s `identifier` already resolves against *either* `email` or `phone` (`get_by_email(identifier) or get_by_phone(identifier)`), and already branches on `requires_liveness` by tier (ADR 0012). No backend change was needed here: a normal-tier user's phone number and a VIP's email both already work as `identifier` today. The mobile login screen accordingly keeps one generic "phone or email" field rather than a tier-aware toggle it has no way to evaluate before the user identifies themselves.

**"Unlock" vs. "login"**: the existing biometric-unlock path (`index.tsx`'s stored-refresh-token + `/auth/refresh`) is unchanged. What's new is a PIN-entry alternative that calls the real `start_login`/`complete_login` flow (phone + PIN) rather than any new endpoint — for a normal-tier account this already returns a session directly (`requires_liveness: false`), so "enter your PIN to get back in" *is* a real, full re-authentication under the hood, just presented as an unlock rather than a form.

**No explicit logout for normal tier**: the mobile settings screen only shows "Log out" / "Log out everywhere" for `vip` accounts. A normal-tier session persists until the same phone number is re-verified on a different device — the existing signup uniqueness check (`start_phone_signup` rejects an already-registered phone) already forces that path through **login**, not a second signup, on the new device; nothing new was needed to make a reinstall/new-phone scenario work like a real "move my account" flow.

**Recovery** (`RecoveryService`): the existing flow (email + phone + SmartSelfie Authentication) assumed every account has an email and a liveness enrollment to check against — true for VIP, false for normal accounts under this ADR. A new `start_phone_recovery(phone)` path (normal tier only) does phone-OTP-only recovery: no email step, no liveness (there's no enrollment to authenticate against), completing once the OTP is confirmed. VIP-tier accounts are explicitly rejected from this path — a lighter recovery flow would undercut the exact "verified identity" promise VIP is sold on — and continue using the original email+phone+liveness recovery unchanged.

## Consequences

- Every test that exercises the old `start_signup`/VIP-shaped recovery already sets `account_tier` explicitly or uses the email-first path — those are unaffected. New tests cover the phone-only signup and recovery paths.
- A normal-tier account genuinely has no email, DOB, or national ID until (if ever) it upgrades to VIP — any code path that assumed otherwise needed auditing (see the PR this ADR ships with) for a `None` it wasn't handling.
- A 6-digit numeric PIN has materially less entropy than the original alphanumeric code — this is an accepted, deliberate trade-off (same one every phone lock-screen and banking app makes), leaned on more heavily by the existing escalating-lockout mechanism (`failed_code_attempts`/`locked_until`, unchanged) and the weak-PIN blocklist above, not by raw keyspace size.
