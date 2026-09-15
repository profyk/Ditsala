# Security Gaps

Living document of features shipped behind an interface because they couldn't yet be built to the docs/DITSALA_MASTER_SPEC.md §7 standard, per the kickoff prompt's Working Rule 6. Not a bug tracker — an explicit register of known, deliberate gaps, closed out as they're resolved.

## Open

### libsignal native module not built (spec §6) — headline gap

**What's missing:** The actual Signal Protocol implementation — X3DH key agreement, the Double Ratchet, Sender Key encryption/decryption — via libsignal's native Rust core with Swift/Kotlin bindings, wrapped in an Expo config plugin. No message composer or chat UI exists on mobile yet either; see ADR 0005 for why building either without the other would be actively misleading (a chat screen that *looks* encrypted without a real cipher behind it is worse than no chat screen).

**Why:** This environment has no Xcode, Android Studio, Rust toolchain, or EAS build access — there is no way to write, compile, or verify native iOS/Android binding code here at all, not even to the "code-complete but unverified" standard the Smile ID/Twilio adapters were held to.

**What's already done and doesn't need to change:** The entire backend for Phase 4 — key registration/prekey-bundle endpoints, message relay, group Sender Key distribution, media presigned URLs, the WebSocket transport — is real, fully tested code, because the backend never decrypts anything by design (§7.3) and is therefore crypto-library-agnostic. A native module integration should be able to sit directly behind `lib/messaging-api.ts` and `lib/messaging-ws.ts` on the mobile side without backend changes.

**Tracked for:** This is the single highest-priority item for whoever picks up this codebase next with native build tooling available. See `docs/adr/0005-e2ee-native-module-gap.md` for the full architectural reasoning.

### WebRTC calling not runtime-verified on a device (spec §27)

**What's missing:** `react-native-webrtc` (real dependency, real API usage — see `lib/call-session.ts`) has never actually run: no `expo prebuild` + native compile, no simulator/device, no EAS build. This is a different kind of gap than the libsignal one above — see `docs/adr/0007-calls-native-module-verification-gap.md` for why the full stack (backend signaling, `CallSession`, `call-context.tsx`, the incoming/active-call screens) was built for real rather than left as plumbing-only, and exactly what "unverified" means here (the code is complete and correct against the library's documented API; it just hasn't been proven to actually carry audio/video on a real device yet).

**Why:** Same environment constraint as libsignal — no Xcode/Android Studio/EAS credentials — but `react-native-webrtc` itself needed no code this session had to get cryptographically right, unlike libsignal.

**Also not run:** the self-hosted coturn TURN server (`infra/docker-compose.yml`, scaffolded since Phase 0) — same Docker-not-installed constraint as the rest of local dev. Without it running, only same-network (STUN-reachable) calls would actually connect if this were tested today.

**Also not implemented:** W3C "Perfect Negotiation" glare resolution for two simultaneous renegotiation offers colliding (`lib/call-session.ts`). With exactly two participants and `switch_media` as the only renegotiation trigger, this only matters if both sides hit "switch" in the same round trip.

**Tracked for:** Whoever next has EAS/Xcode/Android Studio access — run a real device build and place a call between two devices before trusting this beyond "code review passed." See the ADR for the full reasoning.

### Circle QR code generation and safety-number display gaps carried over from Phase 5

See the two entries below this one for the pre-existing Circle gaps (QR rendering, safety-number fingerprint display) — unchanged by Phase 6.

### Location sharing is foreground-only (spec §25)

**What's missing:** `app/location/index.tsx` acquires real GPS via `expo-location` and posts real pings while the screen is open, but no background location task is registered — closing or backgrounding the app stops the pings, even though the `location_shares` grant is still active server-side until it expires or is revoked.

**Why:** Registering a background location task (`expo-location`'s `startLocationUpdatesAsync` + a defined task via `expo-task-manager`) is a larger platform-permissions surface (Android's background-location rationale flow, iOS's "Always" authorization) that wasn't in scope to add sight-unseen in this pass.

**Tracked for:** Add `expo-task-manager` + a registered background location task once this is being verified on a real device anyway (see the WebRTC gap above — that verification pass is the natural place to also confirm background location permissions prompts render correctly).

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

### Circle QR code generation (spec §22-23)

**What's missing:** `app/circle/add.tsx` can *scan* a QR code (via `expo-camera`'s barcode scanner, real and working) and can *share* the user's own add-contact link (`ditsala://circle/add?userId=<id>`, via React Native's built-in `Share` sheet — also real and working), but cannot *render* its own link as a scannable QR code image. A second DITSALA user has no on-screen QR code to point their camera at yet.

**Why:** Deliberate, not a capability gap. Rendering a QR image needs a QR-generation library (e.g. `react-native-qrcode-svg`), which isn't in the dependency tree — this session already flagged the host machine's real memory constraints (3.84GB RAM) mid-Phase-4 and has been conservative about new native dependencies since. Link-sharing covers the same flow end to end without one.

**Tracked for:** Add a QR-generation library and render the link from `handleShare` (already computed there via `Linking.createURL`) as an image, then remove this section. Low risk, no architecture change — `extractContactUserId` (`lib/circle-link.ts`) already parses whatever a camera scans, so the scanning half needs no changes.

### Safety-number display is not rendered (spec §23)

**What's missing:** §23's safety number is "a human-readable fingerprint derived from both parties' Signal identity keys" — a real cryptographic value the Signal Protocol produces from real `IdentityKey` material. `app/circle/index.tsx`'s "Verify in person" action calls the real `POST /circle/safety-number/verify` endpoint and really does promote a contact to `trusted` server-side, but the screen never displays the two-sided fingerprint string a user is supposed to compare — because there's no real value to show.

**Why:** Same root cause and same principle as ADR 0005 (the libsignal native module isn't built in this environment). Fabricating a fingerprint-looking string from non-cryptographic data would be indistinguishable from real E2EE verification in the UI while providing none of its guarantees — exactly the "weaker fallback shipped silently" Working Rule 6 forbids. The backend-state half of trust-tier promotion is real and safe to ship; the display half isn't, so it was left out rather than faked.

**Tracked for:** Once the native libsignal module exists (see ADR 0005) and mobile holds real `IdentityKey` material, compute and display the actual safety number (Signal's standard 60-digit/12-group fingerprint format) on this screen before calling `verifySafetyNumber` — the API call itself needs no changes.

### Smile ID webhook HTTP endpoint not exercised by any test with a real payload (spec §12, §17)

**What's missing:** `POST /webhooks/smile-id` (`api/v1/routers/onboarding.py`) — the signature-verification step and the request/response shape at the actual HTTP boundary — has no test coverage. Everything *behind* a valid webhook (job lookup, state transitions, `AuthService.record_login_liveness_result`) is fully tested by calling those methods directly with a constructed `KycWebhookResult`, which is fine for that logic but never exercises `SmileIdProvider.verify_and_parse_webhook`'s actual HMAC check against a realistic payload.

**Why:** No live Smile ID account to generate a real signed webhook payload from (same root cause as the field/endpoint-accuracy gap above). A synthetic payload signed with a placeholder key would test the HMAC comparison logic in isolation but wouldn't validate the payload shape assumptions.

**Tracked for:** Same milestone as the Smile ID field/endpoint-accuracy gap above — before Phase 2/3 go live against real credentials, add a test that POSTs a properly-signed payload (using real or sandbox Smile ID credentials) to `/webhooks/smile-id` and asserts the full path end to end.

## Resolved

_(none yet)_
