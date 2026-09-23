# Security Gaps

Living document of features shipped behind an interface because they couldn't yet be built to the docs/DITSALA_MASTER_SPEC.md §7 standard, per the kickoff prompt's Working Rule 6. Not a bug tracker — an explicit register of known, deliberate gaps, closed out as they're resolved.

## Dev-only KYC bypass (test tooling, not a gap)

`KYC_PROVIDER=bypass` (`services/kyc/bypass.py`, selected via `services/factory.py`) auto-passes any KYC/liveness job instead of calling a real vendor — added explicitly to let signup/login/recovery be exercised end to end without a live Smile ID account, since the real blocker (no native Smile ID SDK wired into the mobile app — see the libsignal-style gap below) means no amount of real vendor credentials gets you past the actual document-capture screen anyway.

**This is not a weaker version of KYC shipped silently.** `get_kyc_provider()` raises immediately if `KYC_PROVIDER=bypass` is combined with `ENVIRONMENT=production` — that combination cannot start. Every activation logs a `kyc_bypass_used` warning with the user id and job type, so it's never silently indistinguishable from a real pass in server logs. It exists purely so the rest of the account lifecycle (email/phone verification, next-of-kin, DITSALA Code, two-factor login, logout, session revocation) can be verified for real on a live deployment while the native KYC capture piece remains genuinely unbuildable in this environment.

**Never set `KYC_PROVIDER=bypass` on anything a real user's data could reach.**

## Open

### Admin has no live-call moderation, and message/call content moderation is deliberately impossible

**What's missing:** the new `AdminMeetingGovernanceService` (list/extend/end any Conference Room meeting platform-wide) has no equivalent for `domain/calls` (1:1 voice/video calls) — an admin can't see or force-end a call in progress. The same pattern (an admin-override method with no participant-check, RBAC-gated at the router) would transfer directly; just not built this pass.

**Why:** Out of scope for the session that added meeting governance — calls are a materially different data model (`domain/calls/service.py`'s signaling state machine, not `Meeting`), and adding it without dedicated attention risked doing it hastily.

**Tracked for:** A follow-up pass, mirroring `meetings_governance:view`/`:action`'s exact shape for calls.

**Not a gap, a hard boundary — documented here so it isn't mistaken for an oversight:** "control user messaging" and "voice/video calling" admin requests stop at account-level and metadata actions (suspend/ban already blocks messaging and calling entirely; Reports & Moderation surfaces what's reportable) because §7's E2EE non-negotiable means **no admin path can ever retrieve decrypted message content** — a content-moderation admin feature is not a smaller version of this gap, it's the thing that non-negotiable exists to prevent. Voice/video calls are DTLS-SRTP end-to-end for the same reason (spec's locked "Calls" decision) — admin has never had, and won't have, a way to listen in.

### admin app's Sidebar scroll fix not visually confirmed

**What's missing:** a user report ("fix nav bar to scroll") was addressed by removing a redundant nested `h-screen` (the `<aside>` now uses `h-full`, inheriting the outer layout's already-constrained height) and adding `overscroll-contain` — the standard fix for this exact class of symptom, and the CSS was already using the textbook-correct scrollable-flex-child pattern beforehand. Never reproduced or re-confirmed in an actual browser.

**Why:** The Chrome extension bridge (`mcp__claude-in-chrome__*`) wasn't connected in this session, and the admin app requires a real login (password + TOTP MFA) this session had no credentials for.

**Tracked for:** A quick visual check — shrink the browser window short enough that the nav list (12 items as of this writing) overflows, confirm it scrolls independently of the page.

### Stitch payment adapter is unverified against a live account (ADR 0012)

**What's missing:** `services/billing/stitch.py` (`StitchPaymentProvider`) implements OAuth2 client-credentials auth + a GraphQL payment-initiation mutation + HMAC webhook verification, following Stitch's publicly documented API shape — but the exact mutation/field names and the webhook signature header are unverified against a live Stitch account, the same caveat `services/kyc/smile_id.py` already carries for Smile ID.

**Why:** No Stitch account (real or sandbox) exists in this environment to test against.

**Tracked for:** Before going live — get real Stitch sandbox credentials, re-verify `initiate_payment`'s mutation shape and `verify_and_parse_webhook`'s signature header/algorithm against Stitch's current API reference, then remove this section. `VipUpgradeService` itself (payment → KYC → tier flip) is real and fully tested against a stub `PaymentProvider` — see `app/tests/test_vip_upgrade_service.py`.

### LiveKit RoomService/Egress calls unverified against a live LiveKit server (DITSALA_MEET_SPEC.md §9 Phase 2)

**What's missing:** `services/meet/livekit.py`'s `LiveKitRoomProvider.remove_participant`/`set_participant_can_publish`/`broadcast_data`/`start_recording`/`stop_recording` all make real HTTP calls to LiveKit's RoomService/EgressService, using method signatures and protobuf field names confirmed via live Python introspection of the installed `livekit-api` package — but never exercised against an actual running LiveKit server (no Docker in this environment, no LiveKit Cloud project provisioned). `create_access_token` (pure local JWT signing, no network call) is real and fully verified — see `app/tests/test_meeting_service.py`. `MeetingService`'s own logic (waiting-room admission, host/co-host authorization, recording bookkeeping, chat/poll/Q&A/breakout-room state) is tested against real Postgres with a `StubRoomProvider` standing in for the network-calling methods only.

**Why:** No LiveKit account or self-hosted `livekit-server` instance exists in this environment to test against — same class of gap as the Stitch/Smile ID adapters above.

**Tracked for:** Before going live — provision a real LiveKit Cloud project (or self-hosted instance), re-verify each RoomService/EgressService call against it, and remove this section. Also worth adding then: LiveKit's egress-completion webhook, so a recording's `status` moves from `processing` to a confirmed terminal state asynchronously rather than only being known from `stop_recording`'s own synchronous response.

**Update:** this was the actual root cause of a real user-reported "can't join the meeting, host or guest" bug — `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` were still unset on the live Railway deployment (the `wss://localhost:7880` default, unreachable from any real client), confirming this gap was never closed before going live as flagged. The user has since provisioned a real LiveKit Cloud project and set all three variables in Railway. **Still not independently verified from this session** — no browser/credentials access here to confirm an actual join succeeds end-to-end post-configuration; worth a real click-through (host joins, a guest joins, video/audio actually connects) before considering this section fully closed.

### Live in-meeting AI captions/transcription not built — post-meeting pipeline only (DITSALA_MEET_SPEC.md §6, §9 Phase 3)

**What's missing:** the parent spec's §6 describes a LiveKit Agents worker joining each meeting as a hidden participant, tapping every track in real time to feed Deepgram's streaming API — live captions and continuously-updating notes during the meeting. That worker needs `livekit-agents` plus the `livekit` core WebRTC client (`livekit-rtc`), which requires native (non-pure-Python) bindings for audio/video codecs and ICE — the same category of native-module constraint as ADR 0005 (libsignal) and ADR 0007 (react-native-webrtc), but here compounded by this dev machine's resources at the time of writing (1.2GB disk, 0.5GB RAM free), which made installing `livekit-agents` unsafe to attempt (see the repeated RAM/disk crises logged elsewhere in this project's history).

**What's real instead:** `MeetingIntelligenceService` (`domain/meet_ai/service.py`) transcribes a *finished* recording via Deepgram's prerecorded REST API, then runs it through Claude for structured notes — delivering §15's notes, §17's "what did I miss," and §18's search, just not live during the meeting. Both the Deepgram and Claude adapters are real code against each vendor's genuine, documented API contract (Claude's shape confirmed via live introspection of the installed `anthropic` SDK; Deepgram's via its public API docs), but **neither has been exercised against a live API key** in this environment — same class of gap as Stitch/Smile ID/LiveKit's RoomService above.

**Why:** No Deepgram or Anthropic API key exists in this environment, and the native LiveKit Agents worker couldn't safely be installed given the resource constraints above.

**Tracked for:** Before going live — get real Deepgram/Anthropic API keys and verify `DeepgramTranscriptionProvider`/`ClaudeMeetingIntelligenceProvider` against them; separately, on a machine with adequate RAM/disk (or a dedicated worker host, which is the right place for this anyway — it shouldn't run on the same box as the API server), build and verify the actual `livekit-agents` worker for live captions, upgrading this pipeline from post-meeting to real-time without changing anything downstream (transcript storage, notes, search all already work the same way regardless of when the transcript rows are written).

### Chat: no local offline cache, no media/group-creation UI yet, no multi-device fan-out (ADR 0013)

**What's missing:** the real, working chat UI (`apps/mobile/app/messages/`) — conversation list, chat screen, TweetNaCl E2EE send/receive, wired from Circle's "Message" button — has real gaps beyond ADR 0013's own crypto-design trade-offs: (1) no offline/local cache — every screen open re-fetches and re-decrypts from the server, no `expo-sqlite` ciphertext cache yet (design already decided, see ADR 0013's addendum); (2) no UI to send media/images (the crypto module's `encryptMedia`/`decryptMedia` exist and are tested, nothing calls them from a screen yet); (3) no UI to create a new group conversation (only 1:1, from Circle) or to invite members to an existing group; (4) V1 encrypts to a single device per recipient (`get_primary_device_id`, the most-recently-registered one) — a recipient with multiple devices only receives new messages on whichever one registered keys last, not on every device they're signed into.

**Why:** Time-boxed to ship the core send/receive flow for real first; each of the above is additive, not a redesign.

**Tracked for:** Local cache and media UI are the natural next increments (crypto support already exists for media). Multi-device fan-out needs `encryptOutgoingMessage` to loop over every one of a recipient's registered devices (via a new "list all devices for user" endpoint, not just the primary one) rather than a design change.

### Mobile Meet scheduling: no native date picker, no Fraunces display font (DITSALA_MEET_SPEC.md §9 Phase 4)

**What's missing:** `apps/mobile/app/meet/schedule.tsx` (schedule a call, set a password, share the generated `https://ditsala-meet.vercel.app/{id}` link — `apps/meet` is live, see `docs/CI_CD.md` §6a) uses a hand-built, dependency-free calendar/time picker (`components/ScheduleDateTimePicker.tsx`) instead of `@react-native-community/datetimepicker` — this dev machine's resources at the time (~1.1GB disk, ~0.5-0.6GB RAM free) made adding a new native dependency risky, and mobile UI here is unverifiable beyond `tsc`/ESLint/Jest either way (no simulator/device in this environment, same boundary as every other mobile phase). Also real but unwired: the brand's Fraunces display serif (`packages/ui-tokens`' `fontFamily.display`) has no font-asset loading set up in the RN app, so headline text uses the system font's bold weight instead of silently claiming an unloaded typeface.

**Why:** Same class of environment constraint as the LiveKit Agents worker gap above (RAM/disk).

**Tracked for:** Swap in the native date picker and wire real font loading (`expo-font` + Fraunces/Inter assets) once resources allow.

**A real bug in this picker was found and fixed since the paragraph above was written:** `ScheduleDateTimePicker`'s popup Modal (and `CountryCodePicker`'s, same root cause) rendered with every `bg-surface`/`text-text-primary`/etc. class resolving to nothing — a fully transparent sheet with default-color text overlapping whatever screen was behind it, unreadable. Cause: `lib/theme-context.tsx`'s `ThemeProvider` sets NativeWind's theme CSS variables via `vars()` as an inline `style` on its wrapping `<View>`; React Native's `<Modal>` portals its children into a separate native root (a new window on iOS, a new Dialog on Android) that isn't a native descendant of that `<View>`, so the variables never reach it even though the Modal's content is still a React-tree descendant. Fixed by a new `useThemeVars()` hook (same file) that either Modal now spreads onto its own outermost `<View>`, re-establishing the variables inside the portaled tree. Verified via `tsc --noEmit`, ESLint, and the existing Jest suite (all clean) — **not visually confirmed on a simulator/device**, same boundary as everything else mobile in this project; worth a quick visual check the next time someone has a working Expo dev client.

### Conference Room plans (Free/Pro/Premium/Enterprise) have no self-serve checkout yet

**What's missing:** the four `conference_*` plans (migration `b4f7c1a9e6d2`, `app/domain/billing/conference_plans.py`) are real, seeded, and enforced (`MeetingService` clamps meeting duration/guest count to the host's plan and gates recording/breakout-rooms/analytics behind `conference.tools`) — but a user can't buy one. `PlanService.set_user_conference_plan` (`PUT /admin/billing/users/{id}/conference-plan`, `apps/admin`'s Conference Plans page) is admin-only, same "admin sets it, no default by design" precedent VIP pricing already established in ADR 0012 before its own Stitch flow existed.

**Why:** No org/seat model exists yet for Business/Conference plan resolution (a real, separately-documented gap — see `PlanService.resolve_plan_code_for_user`'s own docstring), and wiring a second product through the existing Stitch `VipUpgradeService`/`StitchPaymentProvider` flow (itself still unverified against a live Stitch account, see above) is real, scoped work of its own rather than something to guess at here.

**Tracked for:** Once Stitch is live-verified, extend `VipUpgradeService`'s pattern (or a sibling service) to cover a Conference plan purchase/upgrade, replacing the admin-assignment path as the primary route (keeping it available as a support/override tool).

### VIP privacy/messaging perks not yet built (ADR 0012)

**What's missing:** the tier split, `VipUpgradeService`, and Stitch adapter are all real (see above and `docs/adr/0012-normal-vip-tier-split.md`). Still not built: hiding a VIP's phone number from non-Circle contacts, and VIP-to-VIP automatic trusted messaging ("private space").

**Why:** Scoped out of this pass to land the payment/KYC upgrade path first — these are the next real increment, not a fundamental blocker like the Stitch verification above.

**Tracked for:** Phone-number visibility touches Circle's contact-lookup responses and admin user search (which should keep seeing it, for moderation); VIP-to-VIP auto-trust touches `MessagingService.start_direct_conversation`'s Circle-tier gate.

### Admin TOTP secret stored plaintext (spec §29)

**What's missing:** `admin_users.mfa_secret` (the base32 TOTP seed) is stored in the clear — unlike passwords/refresh tokens, it must be read back to compute the current code, so it can't be a one-way hash, but it should still be encrypted at rest via a KMS-backed key.

**Why:** No KMS or envelope-encryption infrastructure is provisioned anywhere in this stack; adding one for a single column for a v1 admin panel with a handful of accounts was judged out of proportion for now. See `docs/adr/0008-admin-rbac-and-mfa-design.md`.

**Tracked for:** Before a real admin population exists at scale — envelope-encrypt `mfa_secret`, decrypted only inside `AdminAuthService`.

### Admin panel not verified in a real browser (spec §28)

**What's missing:** The Next.js admin panel (`apps/admin`) was verified via `tsc`, ESLint, Vitest (all passing), and a real `next dev` server that successfully compiled and served the login page (HTTP 200) against the real FastAPI backend — but no visual/interactive verification happened in an actual browser, since this session's Chrome extension bridge wasn't connected. Playwright E2E (per the kickoff prompt's "Admin: Vitest + Playwright" working rule) was not attempted at all, for the same reason plus this host's tight memory/disk margins.

**Why:** No browser automation bridge was available in this environment for this pass, and the host machine's resource constraints (see CLAUDE.md's "Local dev" notes) make running a second heavy toolchain (Playwright + browser binaries) risky without more headroom.

**Tracked for:** Open the app in a real browser and walk through each of the 8 sections end to end (login/MFA enrollment, dashboard, KYC review with a real `manual_review` account, users search, report actions, security dashboard, invitations toggle, audit log filters, system config edit) before trusting this beyond "the code compiles and serves." Add Playwright E2E coverage for the login/MFA flow and RBAC-gated navigation once that's done.

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

### Data subject access requests are tracked, not auto-fulfilled (spec §34.4)

**What's missing:** `domain/compliance/service.py` (`ComplianceService`) implements full request-tracking against the 30-day SLA — filing, listing, admin mark-in-progress/complete/reject with resolution notes — for all three request types (access, correction, deletion). Completing a **deletion** request genuinely triggers the real deletion cascade (delegates to `AccountLifecycleService.request_deactivation`, same code path as self-service deactivation, ADR 0009). Completing an **access** request does not generate an actual data-export bundle (a file containing everything DITSALA holds about that user across all P0-P3 tables) — the admin records how it was fulfilled in `resolution_notes`, but no code assembles that export.

**Why:** A full data-export pipeline is a materially larger, separate feature than request tracking — it needs to enumerate every table touching a user (30+ tables as of Phase 8), decide a sensible export format, and handle P1 data (KYC result summaries) and P2 data (the user's own message metadata, never content — §7.3 forbids that regardless) with care. Building it well deserves its own design pass rather than a rushed pass bolted onto the request-tracking feature.

**Tracked for:** Add an export-generation job (likely triggered the same way the scheduled sweeps in `app/tasks/scheduler.py` are, given it may take a while for a user with a lot of history) that gathers a user's P0(-hash-only)/P1(-summary-only)/P3 data into a downloadable bundle, then wire `ComplianceService.complete` to produce and deliver it automatically for `request_type == "access"`.

### Rate limiting and scheduled sweeps are in-process, single-instance (spec §32, §34.2)

**What's missing:** `InMemoryRateLimiter` (`services/ratelimit/memory.py`) and the APScheduler-based sweeps (`app/tasks/scheduler.py`) both hold their state/scheduling in the one backend process — correct for a single instance, but running more than one backend process would give each its own independent rate-limit counters (an attacker could get `N ×` the intended limit by hitting `N` instances) and would run every scheduled sweep once per instance (wasteful, though harmless since every sweep is idempotent).

**Why:** No Redis binary is available in this environment (`docker compose up` was never run — see CLAUDE.md's "Local dev" notes) to back either with the shared, cross-instance state the production-shaped design calls for. Both are isolated behind a `Protocol` (`RateLimiter`, and the scheduler's own module boundary) specifically so this swap doesn't touch call sites later — see `docs/adr/0010-rate-limiting-key-choice.md` and `app/tasks/README.md`.

**Tracked for:** Before running more than one backend instance — replace `InMemoryRateLimiter` with a Redis-backed sliding-window implementation of the same `RateLimiter` Protocol, and either move the scheduled sweeps to a proper distributed scheduler or add a Redis-backed leader-election lock so only one instance runs them.

### CI/CD deploy infrastructure is written but not provisioned or build-tested (spec §35)

**What's actually verified now:** the backend, `apps/admin`, `apps/meet`, and `apps/mobile`'s web export all auto-deploy for real on every push to `main`, via Railway's and Vercel's own native GitHub integrations (no GitHub Actions workflow or secret involved — see `docs/CI_CD.md` §1 and the "Resolved" note below). `GET /api/v1/health` returns 200 live at `https://ditsala-production.up.railway.app`, and the live OpenAPI schema reflects the exact code from the latest push, confirming `entrypoint.sh`'s `alembic upgrade head` runs against the real Supabase database on every deploy, not just once manually.

**What's still missing:** AWS ECS (the replica/backup path) and EAS submit (app store submission) remain genuinely unprovisioned and unexercised — no AWS account/IAM role or App Store Connect/Google Play credentials wired in this environment. Neither blocks the live product; ECS is a deliberate backup path and EAS submit is only needed for native app store releases.

**Tracked for:** Follow `docs/CI_CD.md` §4 (AWS ECS) and §6 (EAS submit) for their one-time setup whenever a backup deploy path or a native app store release is actually needed.

## Resolved

### Admin RBAC is a hardcoded Python mapping, not DB-driven (spec §29)

Resolved in Phase 8 — see `docs/adr/0011-admin-rbac-db-driven.md`. `require_permission()` now queries `admin_role_permissions` directly; migration `7a3f2e9c1b4d` seeds it with the prior hardcoded mapping so behavior is unchanged (verified: all 11 `test_api_admin.py` RBAC tests pass unmodified).

### DITSALA Code breach-corpus check (spec §15)

Resolved in Phase 8 — `core/security.py::is_breached_code` calls Have I Been Pwned's Pwned Passwords k-anonymity API (only a 5-character SHA-1 prefix ever leaves the process, never the code itself), wired into both onboarding's `set_ditsala_code` and recovery's `complete`. Fails open on any network/API problem so signup/recovery availability never depends on a third party's uptime. Verified with real calls to the live HIBP API in tests (a known-breached password correctly flagged, a random string correctly allowed) — not mocked.

### Redundant, secret-less GitHub Actions deploy workflows kept CI permanently red

`backend-deploy-railway.yml`, `admin-deploy.yml`, and `mobile-vercel-deploy.yml` duplicated deploy behavior Railway/Vercel's own native GitHub integrations already performed, and none of their required secrets (`RAILWAY_SERVICE_ID`, `VERCEL_TOKEN`, etc.) were ever set — every push showed 2-3 failing workflow runs alongside the real, working native deploys. Also surfaced and fixed in the same pass: `ci.yml`'s `ruff check .` (the whole `backend/` directory, not just `app/`) had been failing since the first Alembic migration using the default `Union[...]` template syntax was committed — nobody had run `ruff check .` locally, only `ruff check app`. Removed the three redundant workflows (native integrations already cover the same deploys with no secrets needed) and ran `ruff check . --fix` across every migration file. `docs/CI_CD.md` rewritten to match.
