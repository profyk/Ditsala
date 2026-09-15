# Security Gaps

Living document of features shipped behind an interface because they couldn't yet be built to the docs/DITSALA_MASTER_SPEC.md §7 standard, per the kickoff prompt's Working Rule 6. Not a bug tracker — an explicit register of known, deliberate gaps, closed out as they're resolved.

## Open

### libsignal native module not built (spec §6) — headline gap

**What's missing:** The actual Signal Protocol implementation — X3DH key agreement, the Double Ratchet, Sender Key encryption/decryption — via libsignal's native Rust core with Swift/Kotlin bindings, wrapped in an Expo config plugin. No message composer or chat UI exists on mobile yet either; see ADR 0005 for why building either without the other would be actively misleading (a chat screen that *looks* encrypted without a real cipher behind it is worse than no chat screen).

**Why:** This environment has no Xcode, Android Studio, Rust toolchain, or EAS build access — there is no way to write, compile, or verify native iOS/Android binding code here at all, not even to the "code-complete but unverified" standard the Smile ID/Twilio adapters were held to.

**What's already done and doesn't need to change:** The entire backend for Phase 4 — key registration/prekey-bundle endpoints, message relay, group Sender Key distribution, media presigned URLs, the WebSocket transport — is real, fully tested code, because the backend never decrypts anything by design (§7.3) and is therefore crypto-library-agnostic. A native module integration should be able to sit directly behind `lib/messaging-api.ts` and `lib/messaging-ws.ts` on the mobile side without backend changes.

**Tracked for:** This is the single highest-priority item for whoever picks up this codebase next with native build tooling available. See `docs/adr/0005-e2ee-native-module-gap.md` for the full architectural reasoning.

### Local S3-compatible storage (e.g. MinIO) not run in this environment (spec §3)

**What's missing:** `services/storage/sandbox.py` (`SandboxStorageProvider`) is code-complete and shares the exact same client code as the real S3 adapter, differing only in endpoint/credentials — but no local MinIO instance was run here to actually exercise a presigned upload/download round-trip. `domain/messaging/service.py`'s media methods are tested against a stub `StorageProvider` instead (see `app/tests/test_messaging_service.py`).

**Why:** Deliberate, not a capability gap — this session already runs a portable Postgres and Mailpit, and adding a third local service risked the same low-memory conditions flagged mid-session (see `CLAUDE.md`).

**Tracked for:** Add a MinIO service (or point `SANDBOX_S3_*` at any other local S3-compatible endpoint) and exercise one real presigned upload before trusting the media flow beyond stub-level testing. `infra/docker-compose.yml` doesn't include one yet — the original Phase 0 scope only called for Postgres/Redis/coturn/Mailpit.

### DITSALA Code breach-corpus check (spec §15)

**What's missing:** §15 calls for rejecting DITSALA Codes found in a common-password/breach-corpus dataset at signup. `core/security.py::validate_ditsala_code_strength` currently only checks structural rules (length ≥ 8, contains a digit) — it does not check against any breach corpus.

**Why:** No such dataset or service is wired up. A real implementation needs either a local breach-corpus wordlist (e.g., a filtered subset of Have I Been Pwned's Pwned Passwords list) or a k-anonymity API call to a service like HIBP — both require infrastructure/vendor decisions not yet made, and using a live third-party API to check a value derived from a not-yet-hashed secret needs care (HIBP's k-anonymity model, sending only a truncated hash prefix, is the only acceptable approach — never send or log the plaintext code to a third party).

**Tracked for:** Phase 2 follow-up or Phase 8 hardening, whichever lands first. Close this entry by wiring `validate_ditsala_code_strength` to a real breach-corpus check and removing this section.

### Smile ID adapter field/endpoint accuracy (spec §12)

**What's missing:** `services/kyc/smile_id.py` implements Smile ID's documented HMAC partner-signing scheme faithfully, but exact endpoint paths and response field names (`ResultCode`, `PartnerParams`, etc.) have not been verified against a live Smile ID account or current API reference — this was written without vendor credentials (see `CLAUDE.md` "Phase 2" notes).

**Why:** No Smile ID partner account exists in this environment to test against, and Smile ID's API has product-specific variations (Document Verification, Enhanced KYC, SmartSelfie Authentication/Registration) that may differ from what's modeled.

**Tracked for:** Before Phase 2 goes live against production or sandbox credentials — re-verify every field/endpoint against Smile ID's current partner API docs, then remove this section.

### Smile ID webhook HTTP endpoint not exercised by any test with a real payload (spec §12, §17)

**What's missing:** `POST /webhooks/smile-id` (`api/v1/routers/onboarding.py`) — the signature-verification step and the request/response shape at the actual HTTP boundary — has no test coverage. Everything *behind* a valid webhook (job lookup, state transitions, `AuthService.record_login_liveness_result`) is fully tested by calling those methods directly with a constructed `KycWebhookResult`, which is fine for that logic but never exercises `SmileIdProvider.verify_and_parse_webhook`'s actual HMAC check against a realistic payload.

**Why:** No live Smile ID account to generate a real signed webhook payload from (same root cause as the field/endpoint-accuracy gap above). A synthetic payload signed with a placeholder key would test the HMAC comparison logic in isolation but wouldn't validate the payload shape assumptions.

**Tracked for:** Same milestone as the Smile ID field/endpoint-accuracy gap above — before Phase 2/3 go live against real credentials, add a test that POSTs a properly-signed payload (using real or sandbox Smile ID credentials) to `/webhooks/smile-id` and asserts the full path end to end.

## Resolved

_(none yet)_
