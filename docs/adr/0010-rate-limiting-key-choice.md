# ADR 0010: Rate limiting is per-account by default; per-IP only pre-auth

Status: Accepted (Phase 8)

## Context

docs/DITSALA_MASTER_SPEC.md §32 asks for "per-IP and per-account rate limits" on: OTP sends, email verification sends, login attempts, invitation issuance, contact requests sent, and SOS triggers. Applying both dimensions to every action uniformly would be the literal reading, but it's the wrong call for two of these actions given where DITSALA operates.

## Decision

**Per-account (or per-target, i.e. the email/phone being contacted) limiting is applied to all six actions.** This is `RateLimiter.hit()` keyed by the account/email/phone/user id, implemented in `OnboardingService`, `RecoveryService`, `CircleService`, and `SosService`.

**Per-IP limiting is added only for the two pre-auth actions where IP is the only identity signal available before the account is known**: `AuthService.start_login` (credential stuffing spread across many different accounts from one IP isn't caught by per-account lockout, since each account only sees a couple of attempts) . Onboarding's `start_signup`/email-code and phone-OTP sends were considered too, but the target email/phone address *is* effectively the account identifier at that point — there's no meaningful "account" identity distinct from it to rate-limit by IP on top of.

**Per-IP limiting is deliberately *not* applied to invitation issuance, contact requests, or SOS triggers.** These are all authenticated, post-login actions — the actor's account is already known and is the meaningful key. Layering a per-IP limit on top would be actively counterproductive in this product's target market: South Africa and Botswana have significant mobile carrier-grade NAT usage, meaning many unrelated legitimate users can share one public IP. A per-IP cap sized to stop abuse from a single account would incidentally rate-limit every other genuine user behind that same NAT — exactly the "still always allow genuine triggers through" requirement §32 states explicitly for SOS, and just as true for invitations/contact requests even though the spec text doesn't repeat it for those.

## Consequences

- SOS's limit (`SOS_TRIGGER_LIMIT = 10` per hour, `domain/sos/service.py`) is intentionally generous — it exists to stop scripted/automated abuse, not to second-guess a distressed person retriggering during an actual emergency.
- If credential-stuffing-style abuse is later observed against invitation/contact-request/SOS endpoints specifically (not just login), the fix is a per-*device* limit (the access token's `device_id` claim), not per-IP — that stays meaningful under carrier NAT since it identifies the actual client, not everyone sharing its network egress.
- The rate limiter itself (`app/domain/ratelimit/interfaces.py`, `app/services/ratelimit/memory.py`) is action-agnostic — it just counts hits against a string key. Every judgment call above lives in the *caller's* choice of key, not in the limiter, so this reasoning can be revisited per-action without touching the limiter itself.
