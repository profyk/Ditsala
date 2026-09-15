# ADR 0006: Circle gates messaging; block/report move out of MessagingService

Status: Accepted (Phase 5)

## Context

docs/DITSALA_MASTER_SPEC.md §22 states relationships progress "unverified (can exchange contact requests but not yet message) → verified (basic messaging unlocked once both sides accept)." §23 states "any subsequent identity-key change for a contact... surfaces a non-dismissible 'safety number changed' warning... DITSALA does not silently trust re-keyed contacts." §24 gives block fuller effects than a bare row insert: hiding the blocker from the blocked user's list and silently dropping any pending contact request.

Phase 4 (`MessagingService`) shipped `start_direct_conversation` gated only on `Block`, and `block_user`/`unblock_user` living directly on `MessagingService` as a bare `Block` row insert/delete — reasonable given Circle didn't exist yet, but incomplete against §22-24 once it did.

## Decisions

**`MessagingService.start_direct_conversation` now requires a `ContactRepository` row at `verified`/`trusted` tier** between the two users, checked after the existing-conversation lookup (so a conversation already in progress isn't retroactively broken if a tier ever regresses) and after the block check (blocking must still win even absent any Circle relationship). `MessagingService` takes a `contacts: ContactRepository` constructor argument for this — a repository, not `CircleService` itself, keeping messaging's domain layer free of a domain-to-domain import.

**`MessagingService.register_identity_key` now calls `ContactRepository.demote_trusted_contacts_of` when a device's identity key actually changes** (compared against the previously stored key, not merely re-registered) — a bulk UPDATE walking every contact who had this user at `trusted` back to `verified` and clearing `safety_number_verified_at`. This is the concrete enforcement of §23's re-key warning; before this, nothing in the codebase reset a stale trust decision.

**`block_user`/`unblock_user` moved from `MessagingService` to the new `CircleService`.** `CircleService.block_user` now also deletes the blocked user's *reverse* `Contact` row (hides the blocker from their list) and marks any pending `ContactRequest` between the pair `declined` — the full §24 behavior. `MessagingService` keeps its own `BlockRepository` dependency, but only to *read* block state for the messaging-capability check; it no longer owns block's side effects. The `/messaging/block/*` REST endpoints were removed; `/circle/block/*` replaces them.

**Contact rows are created at `unverified` tier on request send, not on accept** — both `from_user` and `to_user` get a row the moment a `ContactRequest` is created, promoted together to `verified` on accept, and deleted (not merely left `unverified`) on decline — so a declined-then-reconsidered pair can send a fresh request later without a stale row blocking `get_pending_between`'s duplicate check.

## Consequences

- Every Phase 4 test that creates a direct conversation had to be updated to first insert a verified `Contact` row (or, in `test_messaging_service.py`, use a new `_connect` helper) — a real, intentional behavior change, not a test-only accommodation. `test_block_and_unblock` and `test_block_prevents_new_conversation` were removed from the messaging test files and re-created against the real `CircleService`/`/circle/*` endpoints instead.
- `list_contacts`/`list_circle`/`list_incoming_requests`/`list_outgoing_requests` return profile-enriched dataclasses (`ContactWithProfile`, `ContactRequestWithProfiles`) rather than bare ORM rows, so the API can surface the other party's `display_name` without the mobile client needing a separate user-lookup endpoint (which doesn't otherwise exist, deliberately — no generic "look up any user by id" endpoint is exposed).
- `GET /auth/me` was added for a related, narrower reason: the mobile client needs its own user id for the Circle add-contact link, and decoding its own JWT client-side for this was judged worse than one small endpoint.
- Not addressed here: the actual safety-number *value* a user compares during §23 verification is still not computed or displayed anywhere (needs real Signal identity keys — see ADR 0005 and `docs/SECURITY_GAPS.md`). `verify_safety_number`'s state change (promoting to `trusted`) is real; the on-screen fingerprint comparison it's supposed to follow is not yet possible to build honestly.
