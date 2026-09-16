# DITSALA — Master Production Build Specification

Status: **v1.0 — finalized, all open items resolved. Ready for Phase 0.**
This document is the authoritative product and security specification for DITSALA. It is referenced section-by-section from `DITSALA Claude Code Kickoff Prompt`. Where that kickoff prompt makes a decision, it overrides this spec; where it is silent, this spec governs.

---

## 1. Vision & Product Overview

DITSALA is a mobile-first, end-to-end-encrypted communication app for a **verified circle of real people**, not an open social network. The founding premise: most messaging apps optimize for frictionless growth (anyone can message anyone), which is exactly what makes them fertile ground for scams, catfishing, and unverified strangers reaching vulnerable users. DITSALA inverts this — every account is identity-verified before it can hold a conversation, and every contact relationship passes through explicit trust tiers before location or emergency features unlock.

Primary markets: South Africa and Botswana at launch (hence Smile ID's South African Enhanced KYC product, POPIA, and the Botswana Data Protection Act as the compliance baseline). Primary users: people who want to communicate with family, close friends, and known associates with confidence that the person on the other end is who they claim to be — with particular value to users concerned about personal safety (hence SOS and location-sharing being first-class, not bolted on).

Non-goals: DITSALA is not a public social network, not a business messaging platform, not a dating app, and does not support anonymous or pseudonymous accounts. There is no public discovery of users by search; all relationships are established via explicit invitation or QR/contact exchange.

## 2. Brand & Positioning

(Authoritative; restated from the kickoff prompt for completeness — the kickoff prompt wins on any conflict.)

- Name: **DITSALA** — Setswana for "friends." Wordmark always capitals; "Ditsala" in prose sentences.
- Tagline: **Speak with Confidence.** Supporting line: *Your trusted circle.*
- Product vocabulary: verified contacts are a **Circle**. UI copy: "Add to your Circle," "Circle member," "Share location with your Circle." Never "friends list," never "contacts" as user-facing terminology (the underlying data model may use `contacts`/`circle_relationships` as table names).
- Trust tiers surfaced in UI: **Unverified → Verified → Circle**, plus **Blocked**. Internally `TRUSTED` may remain the enum value backing "Circle."
- The authentication secret a user sets is the **DITSALA Code** — never called a "password" anywhere in UI copy, push notifications, or transactional email.
- Visual identity: dark-first, restrained, private-members'-club aesthetic. Strong typography (a serif or high-contrast grotesk for wordmark/headlines, a clean grotesk for UI), generous whitespace, no illustration mascots, no bubble/rounded playful chrome. Explicitly must not visually resemble WhatsApp, Telegram, or Signal — no green/blue chat-bubble tropes, no default Material/iOS stock chat UI.
- Iconography: geometric, minimal, monochrome-first with a single accent color reserved for calls-to-action and trust-state indicators (e.g., the Circle tier badge).

## 3. System Architecture & Backend Structure

### 3.1 High-level topology

```
apps/mobile (Expo/RN) ──HTTPS/WSS──▶ backend (FastAPI) ──▶ Postgres (Supabase)
                                          │            └─▶ Redis (cache/pubsub/queues)
                                          │            └─▶ S3-compatible storage (encrypted media)
apps/admin (Next.js) ──HTTPS──▶ backend (FastAPI, admin-scoped routes)
mobile ◀──WebRTC (DTLS-SRTP)──▶ mobile      (media path, via coturn for TURN relay)
mobile ◀──WS signalling──▶ backend ──▶ mobile   (call setup only, never media)
```

The backend is the only party that talks to Postgres, Redis, S3, Twilio, the email provider, and Smile ID. The mobile app never holds credentials for any third-party provider directly except the Smile ID mobile SDK's public token (scoped, short-lived, issued by the backend per capture session) and Expo push tokens.

### 3.2 Backend directory structure

```
backend/
  app/
    main.py                     # FastAPI app factory, middleware, startup/shutdown
    core/
      config.py                 # pydantic Settings, env-driven
      security.py                # token signing, hashing (Argon2id for DITSALA Code)
      logging.py
      rate_limit.py
    api/
      v1/
        routers/
          auth.py  onboarding.py  users.py  devices.py
          circle.py  messages.py  conversations.py  media.py
          location.py  sos.py  calls.py  admin/*.py
        deps.py                  # shared FastAPI dependencies (auth, db session)
    domain/                       # pure business logic, framework-agnostic
      accounts/  kyc/  messaging/  circle/  location/  sos/  calls/
    services/
      kyc/
        base.py                  # KycProvider interface
        smile_id.py              # real adapter
        sandbox.py               # SandboxKycProvider using Smile ID's own test mode
      otp/
        base.py                  # OtpProvider interface
        twilio_verify.py
        sandbox.py
      email/
        base.py                  # EmailProvider interface
        resend.py                 # (or ses.py — pick one, see §3.4)
        sandbox.py                 # writes to mailpit in local/dev
      push/
        expo_push.py
      storage/
        s3_client.py
      realtime/
        websocket_manager.py
        redis_pubsub.py
    models/                      # SQLAlchemy ORM models, one module per bounded context
    repositories/                # data-access layer, one per aggregate
    schemas/                     # Pydantic request/response models
    migrations/                  # Alembic
    tasks/                       # background jobs (Redis-queue backed): retention sweeps,
                                 # push fan-out, SOS escalation timers, media cleanup
    tests/
  alembic.ini
  pyproject.toml
```

### 3.3 Layering rule

`api` routers depend on `domain` + `repositories`; `domain` never imports FastAPI or SQLAlchemy directly (keeps business rules testable without a DB or HTTP stack). `services/*` are injected into `domain` via interfaces defined in `domain`, satisfied by adapters in `services/`. This is what makes the `KycProvider`/`OtpProvider`/`EmailProvider` swap (real vs. sandbox) a pure dependency-injection concern driven by environment variables — never an `if env == "test"` branch inside business logic.

### 3.4 Provider selection

| Interface | Real adapter | Sandbox adapter | Selector env var |
|---|---|---|---|
| `KycProvider` | `SmileIdProvider` (Document Verification + Enhanced KYC + SmartSelfie) | `SandboxSmileIdProvider` (Smile ID's own sandbox partner ID/test mode — not a hand-rolled fake) | `KYC_PROVIDER=smile_id\|sandbox` |
| `OtpProvider` | `TwilioVerifyProvider` | `SandboxTwilioProvider` (Twilio Verify test credentials / magic test numbers) | `OTP_PROVIDER=twilio\|sandbox` |
| `EmailProvider` | **Resend** (decision: Resend, for simpler DX and EU/US delivery reputation at our scale; document reconsideration trigger: if/when volume or deliverability requires dedicated IP warmup, revisit SES) | `SandboxEmailProvider` (writes to local Mailpit, or Resend's own test mode in staging) | `EMAIL_PROVIDER=resend\|sandbox` |

No interface ever has a third, hand-rolled "fake" implementation that bypasses the real provider's protocol — the sandbox adapters call the real provider's sandbox/test endpoints so integration bugs surface before production.

## 4. Data Model

All tables below live in Postgres, created exclusively via Alembic migrations. Column lists are the contractual minimum — migrations may add indexes/constraints not enumerated here, but must not omit anything listed. Every table has `id UUID PK default gen_random_uuid()`, `created_at`, `updated_at` unless noted.

### 4.1 Identity & accounts

- **users** — `email`, `email_verified_at`, `phone`, `phone_verified_at`, `display_name`, `date_of_birth`, `national_id_hash` (hashed, never plaintext), `account_state` (see §14), `ditsala_code_hash` (Argon2id), `code_set_at`, `failed_code_attempts`, `locked_until`.
- **kyc_documents** — `user_id FK`, `document_type` (SA ID / passport), `smile_id_job_id` (the *only* pointer to imagery — DITSALA never copies raw document/selfie images into its own storage; see §5, §34), `capture_method` (`camera_live` only — no gallery uploads, enforced client-side and re-validated server-side via Smile ID's liveness signal), `status` (pending/passed/failed/manual_review), `result_summary` (non-reversible fields only: scores, flags, decision — no imagery).
- **kyc_face_verifications** — `user_id FK`, `smile_id_job_id`, `selfie_liveness_score`, `face_match_score`, `status`, `verified_at`.
- **next_of_kin** — `user_id FK`, `full_name`, `relationship`, `phone`, `email` (nullable), `notified_on_sos` boolean default true.
- **email_verifications** / **phone_verifications** — `user_id FK`, `code_ref` (provider-side reference, not the code itself), `channel`, `status`, `expires_at`, `attempt_count`.

### 4.2 Devices, sessions, auth

- **devices** — `user_id FK`, `device_name`, `platform`, `push_token`, `signal_registration_id`, `first_seen_at`, `last_seen_at`, `is_trusted` (post new-device verification), `revoked_at`.
- **sessions** — `user_id FK`, `device_id FK`, `refresh_token_hash`, `access_token_family_id` (for rotation/replay detection), `expires_at`, `revoked_at`, `revoked_reason`.
- **login_attempts** — `user_id FK nullable` (nullable pre-identification), `device_id FK nullable`, `ip_hash`, `stage` (password/code, face liveness), `outcome`, `created_at`.
- **account_recovery_requests** — see §33.

### 4.3 E2EE key material (metadata only — never plaintext key content beyond what the protocol requires the server to hold)

- **identity_keys** — `user_id FK`, `device_id FK`, `public_identity_key`, `registration_id`.
- **signed_prekeys** — `device_id FK`, `key_id`, `public_key`, `signature`, `uploaded_at`, `rotated_at`.
- **one_time_prekeys** — `device_id FK`, `key_id`, `public_key`, `consumed_at nullable`.
- **sender_keys** (groups) — `conversation_id FK`, `device_id FK`, `distribution_message_ref` (opaque; backend relays, never decrypts).

### 4.4 Messaging

- **conversations** — `type` (direct/group), `created_by FK users`, `disappearing_timer_seconds nullable`.
- **conversation_members** — `conversation_id FK`, `user_id FK`, `role` (member/admin for groups), `joined_at`, `muted_until`, `archived_at`, `pinned_at`.
- **messages** — `conversation_id FK`, `sender_device_id FK`, `ciphertext` (opaque blob — server never has plaintext), `content_type` (text/media/voice_note/reaction/system), `client_message_id` (idempotency), `edited_at nullable`, `deleted_at nullable`, `expires_at nullable` (disappearing messages).
- **message_receipts** — `message_id FK`, `user_id FK`, `status` (delivered/read), `at`.
- **media_objects** — `message_id FK nullable` (voice notes/media attachments), `s3_key`, `encrypted_size_bytes`, `content_hash`, `client_side_encrypted` boolean (always true), `expires_at nullable`.

### 4.5 Circle, contacts, invitations

- **contacts** (a.k.a. Circle relationships) — `owner_user_id FK`, `contact_user_id FK`, `tier` (`unverified`/`verified`/`trusted` [= Circle]/`blocked`), `safety_number_verified_at nullable`, `created_at`.
- **contact_requests** — `from_user_id FK`, `to_user_id FK`, `status` (pending/accepted/declined), `channel` (qr/invite_link/phone_match).
- **invitations** — `inviter_user_id FK`, `invite_code`, `channel` (sms/link), `status` (sent/redeemed/expired), `redeemed_by_user_id FK nullable`. Governed by `system_config.invite_only_mode` (§28).
- **blocks** — `blocker_user_id FK`, `blocked_user_id FK`, `reason nullable`.
- **reports** — `reporter_user_id FK`, `reported_user_id FK`, `reason`, `context_ref` (metadata only, never decrypted message content), `status` (open/reviewed/actioned), `reviewed_by_admin_id FK nullable`.

### 4.6 Location & SOS

- **location_shares** — `sharer_user_id FK`, `recipient_user_id FK` (must be `trusted` tier), `starts_at`, `expires_at`, `revoked_at nullable`.
- **location_pings** — `location_share_id FK`, `lat`, `lng`, `accuracy_m`, `recorded_at` (short retention — see `DATA_RETENTION.md`).
- **location_access_log** — `location_share_id FK`, `accessed_by_user_id FK`, `accessed_at` (visible to the sharer — "who viewed your location").
- **sos_events** — `user_id FK`, `triggered_at`, `cancel_window_seconds` (default configurable, e.g. 10s), `cancelled_at nullable`, `status` (armed/cancelled/escalated/resolved), `last_known_location_ref`.
- **sos_notifications** — `sos_event_id FK`, `notified_user_id FK` (Circle members and/or next-of-kin), `notified_at`, `channel`.

### 4.7 Calls

- **calls** — `conversation_id FK nullable`, `initiator_user_id FK`, `type` (voice/video), `status` (ringing/active/ended/missed/declined), `started_at`, `ended_at`.
- **call_participants** — `call_id FK`, `user_id FK`, `joined_at nullable`, `left_at nullable`, `ice_relay_used` boolean.

### 4.8 Admin & audit

- **admin_users** — `email`, `password_hash`, `role_id FK`, `mfa_enrolled` boolean, `last_login_at`.
- **admin_roles** / **admin_permissions** / **admin_role_permissions** — see §29.
- **audit_log** — `actor_type` (admin/system/user), `actor_id`, `action`, `target_type`, `target_id`, `metadata_json` (never message plaintext), `created_at` — **append-only**, no UPDATE/DELETE grants at the DB role level.
- **system_config** — key/value table for admin-tunable flags (`invite_only_mode`, `sos_cancel_window_seconds`, feature flags), each change itself audit-logged.

### 4.9 Push

- **push_tokens** — `device_id FK`, `expo_push_token`, `active` boolean.

## 5. Data Classification & Boundaries

Every field above is tagged into one of four classes. This tagging drives DB role grants, RLS policies, retention rules, and what may ever appear in `audit_log.metadata_json`.

| Class | Examples | Handling rule |
|---|---|---|
| **P0 — Cryptographic secrets** | `ditsala_code_hash`, refresh/access token material, Signal private key material (never leaves device) | Never logged, never in audit_log, never readable by admin role, hashed/encrypted at rest, no plaintext ever transits the backend for private keys. |
| **P1 — Biometric & KYC** | selfie images, ID document images, liveness/face-match scores, `national_id_hash` | Raw imagery is **never persisted at rest in DITSALA-controlled infrastructure** — required by POPIA §14 (retention limitation) applied to special personal information under POPIA §26/27. Images exist only transiently in webhook/SDK-response handling and are discarded immediately after the result fields (scores, decision) are extracted; the image of record lives solely in Smile ID's systems, governed by the DPA between DITSALA and Smile ID (§34). DITSALA's DB holds only `smile_id_job_id` + `result_summary`, which is what makes "no retention window to justify" the actual compliance posture rather than a TTL to defend. Any admin view of P1 detail (§28 KYC review queue) proxies live to Smile ID's job API per-view and is itself logged — never a local cache. |
| **P2 — Message content & location** | `messages.ciphertext`, `media_objects`, `location_pings` | Backend stores/relays ciphertext and encrypted blobs only; plaintext never touches backend or admin DB roles; **no admin path may ever decrypt this class** (hard constraint, §7). |
| **P3 — Operational metadata** | who messaged whom and when (not content), device list, login attempts, account state, audit log | Visible to appropriately-scoped admin roles; still access-logged and retention-bounded. |

Enforcement mechanisms:
- Separate Postgres roles: `app_backend` (full P1-P3 read/write per above, zero P0 plaintext access — P0 is hashed before it ever reaches a query), `app_admin_readonly` (P3 + gated P1 access), `app_admin_kyc_reviewer` (P1 KYC review only). No role can `SELECT` `messages.ciphertext` and also decrypt it — decryption keys never exist server-side.
- Row-Level Security (RLS) policies on `messages`, `conversation_members`, `location_shares`, `location_pings` scoping visibility to participants, enforced even though the primary access path is the backend service role (defense in depth against a compromised/misconfigured query).
- Column-level encryption (pgcrypto or application-layer AES-GCM with keys in a KMS, not in Postgres) for `national_id_hash` inputs before hashing and for any P1 pointer metadata that includes names.

## 6. Cryptography & E2EE Design

- **Protocol**: Signal Protocol via **libsignal** (official Rust core; Swift bindings for iOS, Kotlin/JNI for Android), wrapped in a native Expo module with an Expo config plugin. No JavaScript-only crypto, no reimplementation of X3DH/Double Ratchet/Sender Keys logic in TS.
- **Key hierarchy**: per-device identity key pair generated on-device at first launch, never leaves the device (Keychain / Android Keystore-backed). Signed prekeys rotated periodically (e.g., every 7 days) and re-uploaded; one-time prekeys replenished when the pool on the server drops below a threshold.
- **1:1 sessions**: X3DH key agreement, Double Ratchet for forward secrecy + post-compromise security.
- **Groups**: Sender Keys (as used by Signal for groups) — one sender key per device per group, distributed via pairwise-encrypted 1:1 sessions, rotated on membership change.
- **Media**: encrypted client-side with a per-attachment symmetric key before upload; the key is transmitted only inside the encrypted message envelope; the backend/S3 sees only ciphertext bytes and never the key.
- **Local storage**: message plaintext (post-decryption, for local search/display) is stored on-device in an encrypted local database (SQLCipher or platform equivalent), keyed by a key derived from device secure storage, never derivable from anything the backend holds.
- **What the backend is allowed to see**: sender, recipient(s), timestamps, message size, delivery/read receipts, ciphertext bytes it cannot decrypt. This is the entirety of the trust model — restated as a non-negotiable in §7.

## 7. Security Non-Negotiables

1. No custom cryptography, anywhere. Libsignal for E2EE, well-known audited libraries/KMS for everything else (hashing, token signing, TLS).
2. No plaintext DITSALA Codes, tokens, or biometric templates stored, ever.
3. No admin path — UI, API, or direct DB access — that can retrieve decrypted message content. This must remain true even for law-enforcement or support-escalation scenarios; document the operational consequence (support cannot "read the last message") in `SECURITY.md`.
4. Every external integration behind an interface with a real adapter and a provider-sandbox adapter (§3.4). No conditionally-mocked business logic.
5. Every schema change via Alembic migration; no manual DDL against any environment including local dev.
6. Any feature that cannot yet be built safely is isolated behind an interface and documented as an open item in `docs/SECURITY_GAPS.md` rather than shipped with a weaker fallback silently.
7. Secrets only via environment variables / secrets manager; `.env.example` (no real values) required in every app; `.env*` and all key material gitignored before first commit.

## 8. API Conventions

- REST + JSON over HTTPS for all request/response flows; a single authenticated WebSocket per active device session for realtime (message delivery, typing, receipts, call signalling).
- Versioned under `/api/v1/`. OpenAPI schema is the source of truth for `packages/shared-types` (generated, not hand-written, on both mobile and admin).
- AuthN: short-lived JWT access tokens (e.g., 15 min) + rotating opaque refresh tokens stored hashed server-side, refresh token family tracked for reuse/replay detection (auto-revoke the whole family on detected reuse).
- AuthZ: every admin route checks role/permission via the RBAC layer (§29); every user route checks resource ownership/membership (e.g., conversation membership) at the repository layer, not just the router.
- Idempotency keys required on message-send and payment-adjacent (none at launch) endpoints.
- Standard error envelope: `{ "error": { "code": "...", "message": "...", "request_id": "..." } }`; `request_id` ties to structured logs.

## 9. Onboarding Overview

Sequenced flow (each step gated on the previous; account_state advances per §14):

1. Email entry → email verification (magic code).
2. Personal information (name, DOB) → required for KYC matching.
3. Phone entry → Twilio Verify OTP.
4. Smile ID Document Verification — SA ID or passport, **camera capture only**, client blocks gallery picker at the OS permission/UI layer and the backend independently validates the Smile ID capture metadata indicates a live camera session, not an uploaded file.
5. Smile ID SmartSelfie liveness + face match against the captured document.
6. Next-of-kin details.
7. DITSALA Code creation (with strength rules; confirmed twice; hashed with Argon2id, never transmitted again after set — only verified).
8. Device registration + Signal identity key generation completes onboarding; account transitions to `active`.

Any step failing KYC (document unreadable, liveness failure, face mismatch) routes to `manual_review` (§14) rather than a hard reject on first failure, with a bounded retry count before escalating to admin review queue (§28).

## 10–13. Verification Sub-flows

- **§10 Email verification**: 6-digit code via `EmailProvider`, 10-minute expiry, rate-limited to 5 sends/hour/address.
- **§11 Phone verification**: Twilio Verify handles code generation/validation entirely (we never see or store the code itself, only Twilio's verification SID and status).
- **§12 KYC (Smile ID)**: server creates a scoped Smile ID job (Document Verification + Enhanced KYC job type for SA IDs) and returns a short-lived SDK token to the mobile app; mobile SDK drives capture UX natively; results land via Smile ID webhook, verified via signature, and update `kyc_documents`/`kyc_face_verifications`.
- **§13 Next of kin**: at least one required; used only for SOS notification (§26) and high-assurance recovery (§33) attestation — never sold, shared, or used for marketing.

## 14. Account State Machine

States: `pending_email` → `pending_phone` → `pending_kyc_document` → `pending_kyc_liveness` → `pending_next_of_kin` → `pending_code` → `active` | `manual_review` | `suspended` | `deactivated` | `banned`.

Rules:
- `manual_review` is reachable from any `pending_kyc_*` state on repeated verification failure, and from `active` if a report (§4.5) is actioned by an admin pending investigation.
- `suspended` is admin-initiated, reversible, blocks login but preserves data.
- `deactivated` is user-initiated (self-service "pause my account"), reversible within a grace window defined in `DATA_RETENTION.md`.
- `banned` is admin-initiated following policy violation, not user-reversible; triggers the deletion/retention pipeline per `DATA_RETENTION.md` after the legal hold window.
- Every transition is written to `audit_log` with actor (`system` for automatic KYC-driven transitions, admin id for manual ones).

## 15. DITSALA Code & Credential Design

- Minimum 8 characters, at least one number, rejected against a common-password/breach-corpus check at signup.
- Hashed with Argon2id (memory/time cost tuned per current OWASP guidance, re-tunable via config without a migration).
- Never used alone for login — see §17, always paired with device biometric or Smile ID liveness depending on context.
- Rate-limited and lockout-backed (`failed_code_attempts`, `locked_until` on `users`); lockout durations escalate on repeated failure.

## 16. Session & Device Management

- Each physical device = one row in `devices`, one Signal identity keypair, one push token.
- New-device login requires: DITSALA Code + Smile ID liveness re-check (not just device biometric, since the device biometric enrollment is itself device-local trust that a new device hasn't earned yet) before the device is marked `is_trusted`.
- Device list is user-visible and revocable ("log out this device" / "log out everywhere"), which invalidates the `sessions` row and the associated Signal session material for that device (forces re-establishment of E2EE sessions with peers, which is expected Signal Protocol behavior on device change).

## 17. Two-Factor Login Flow

"Face then code": on an already-trusted device, routine unlock uses platform biometrics (Face ID / BiometricPrompt) guarding a locally-held credential — this never leaves the device and is not a substitute for the DITSALA Code server-side. Full server-side authentication (new device, recovery, after logout) requires DITSALA Code **and** Smile ID SmartSelfie liveness, i.e., true two-factor: something you know (Code) + something you are, freshly re-verified (live face match), not just something you have (a trusted device's stored biometric enrollment).

## 18–21. Messaging Feature Set

Built in this order per the execution phases: 1:1 text (X3DH + Double Ratchet) → delivery/read receipts, typing indicators (over authenticated WebSocket, payload metadata only) → group messaging (Sender Keys) → media (client-encrypted upload, signed short-lived S3 URLs for retrieval by conversation members only) → voice notes → replies/reactions → edit/delete (tombstone rows, `edited_at`/`deleted_at`, ciphertext replaced/cleared) → disappearing messages (`expires_at`, swept by a background task) → pin/mute/archive (per-member, `conversation_members` flags) → block (removes messaging capability bidirectionally, independent of Circle tier) → local search (executes against the on-device decrypted store only — never a backend search index over plaintext).

## 22. Circle, Contacts & Invitation System

- Relationship establishment: QR code scan (in-person, strongest trust signal) or invite link (SMS/share sheet) or phone-number match against existing verified users (opt-in discoverability, off by default).
- Every new relationship starts at `unverified` tier (can exchange contact requests but not yet message) → `verified` (basic messaging unlocked once both sides accept) → `trusted`/Circle (unlocked via explicit safety-number verification, §23 — required before location sharing or SOS visibility to that contact).
- **Invite-only mode**: admin-configurable system flag (`system_config.invite_only_mode`). When on, new account creation requires a valid, unredeemed `invitations` row; when off, onboarding (§9) is open (still fully gated by KYC regardless of this flag — invite-only controls *who can start onboarding*, not *whether KYC is required*).
- Invitation abuse controls: per-inviter rate limit on invitations sent per day, invite codes single-use and time-bounded.

## 23. Trust Tiers & Safety Number Verification

- "Safety number" (a human-readable fingerprint derived from both parties' Signal identity keys, Signal-protocol standard practice) displayed to both users; matching it in person or via a secondary channel and confirming in-app is what promotes a `verified` contact to `trusted`/Circle.
- QR-code-based verification is equivalent to safety-number comparison and is the primary UX (scan each other's in-app QR at the moment of establishing the relationship).
- Any subsequent identity-key change for a contact (e.g., they reinstalled or added a new device) surfaces a non-dismissible "safety number changed" warning, consistent with Signal Protocol norms — DITSALA does not silently trust re-keyed contacts.

## 24. Block & Report

- Blocking is unilateral, immediate, and hides the blocker from the blocked user's Circle/contact list without notifying them; it also silently drops any pending contact request.
- Reporting captures only P3 metadata (§5) and a user-written free-text reason — never message plaintext (the app cannot forward what it cannot decrypt; if evidence is needed, the reporting user is prompted to voluntarily attach a local screenshot, which is then P1/P2-classified media, access-controlled the same as any user-submitted media).

## 25. Location Sharing

- Off by default; sharing requires an explicit, time-bounded grant (`location_shares.expires_at`) to a specific `trusted`-tier contact — never to `verified` or `unverified`.
- Live location updates as `location_pings`, short retention (see `DATA_RETENTION.md`) with only the most recent ping plus a bounded trail needed for the "route so far" UX kept beyond a rolling window.
- **Access transparency**: every time a recipient opens a shared location, it's recorded in `location_access_log` and surfaced to the sharer ("Thabo viewed your location at 14:02") — no silent surveillance even within a granted share.
- Revocable at any time by the sharer; auto-expires at `expires_at` with no renewal without a fresh explicit grant.

## 26. SOS / Emergency

- One-tap SOS trigger creates an `sos_events` row in `armed` state with a cancellation window (default configurable via `system_config.sos_cancel_window_seconds`, e.g., 10 seconds) to absorb accidental triggers.
- If not cancelled, escalates: notifies all `trusted`-tier Circle members and all `next_of_kin` rows via push + SMS fallback (SMS specifically because a Circle member may not have the app open), sharing last-known location regardless of any standing `location_shares` grant. **Legal basis**: this override is not a gap in the consent model — it is processing "necessary to protect a legitimate interest of the data subject" (POPIA §11(1)(d); the Botswana DPA's equivalent public-interest/vital-interest ground), the recognized lawful basis for exactly this scenario — emergency processing on behalf of a data subject who cannot themselves navigate a consent flow. It is documented as an explicit, narrow exception (triggered only by the user's own SOS action, never by a third party, and only for the duration of the `armed`→`escalated` event) in `PRIVACY_POLICY.md` and `SECURITY.md`, not left as an undocumented backdoor.
- `sos_events.status` progression is itself auditable and visible to the triggering user's own history (so they can see who was notified and when), never editable by any party after the fact.

## 27. Calls (WebRTC)

- 1:1 voice and video first; group calls are out of scope for the initial build (revisit post-launch).
- Signalling (offer/answer/ICE candidates) travels over the same authenticated WebSocket as messaging — itself just more metadata the backend relays without needing to understand call content.
- Media path is DTLS-SRTP end-to-end between peers; **self-hosted coturn** provides TURN relay only for NAT traversal, never has access to decrypted media (SRTP keys are exchanged via DTLS directly between peers, not via the TURN server).
- `calls`/`call_participants` capture metadata (who, when, duration, whether a TURN relay was needed) for history/UX — never content.

## 28. Admin Panel

Next.js (App Router) + TypeScript + Tailwind, `apps/admin`. Sections:

1. **Dashboard** — signups, KYC funnel conversion, active accounts, open reports, system health.
2. **KYC Review Queue** — manual_review accounts, showing Smile ID result summary (scores, flags) with a documented, logged "reason for access" required before any P1 detail is rendered (§5); reviewer actions: approve / reject / request-recapture.
3. **Users** — search by non-content metadata (email/phone/name/account state — never by message content, which doesn't exist server-side to search anyway), view account state history, force state transitions with required reason.
4. **Reports & Moderation** — queue from `reports`, action buttons (warn / suspend / ban), always audit-logged.
5. **Security Dashboard** — login-attempt anomalies, lockout counts, device-churn outliers, active sessions count.
6. **Invitations** — invite-only mode toggle, invitation issuance/redemption stats, abuse flags.
7. **Audit Log** — immutable, filterable, exportable view over `audit_log`; this section itself generates no writes to `audit_log` beyond the read-access entries for KYC (P1) views.
8. **System Configuration** — `system_config` key/value editor (SOS cancel window, invite-only mode, feature flags), every change audit-logged with before/after value and admin id.

**Hard constraint restated**: no section, no query, no export function anywhere in the admin panel can produce decrypted message content or media. This is enforced architecturally (§5, §7), not by admin-panel-level access control alone.

## 29. Admin RBAC

Roles (extensible via `admin_roles`/`admin_permissions` many-to-many, but these are the launch set):

| Role | Scope |
|---|---|
| `super_admin` | Full access including system configuration and RBAC management itself. |
| `kyc_reviewer` | KYC queue only; can view P1 KYC data with logged access; cannot touch reports, users list beyond KYC context, or system config. |
| `trust_safety` | Reports/moderation, user account-state actions, security dashboard; no KYC document access, no system config. |
| `support_readonly` | Users list (P3 metadata only) and account-state history, read-only; cannot action anything. |

All admin accounts require MFA enrollment before first use (TOTP at minimum). Every admin session is itself logged (login, logout, and every P1-classified data view) to `audit_log`.

## 30. Audit Logging & Observability

- `audit_log` is insert-only at the DB grant level (no `UPDATE`/`DELETE` privilege for `app_admin_*` roles).
- Structured application logs (JSON) correlate to `request_id`; no P0/P1/P2 field ever logged in cleartext at any log level, enforced by a logging-layer redaction allowlist (log fields must be explicitly allowlisted, not denylisted, to fail safe on new fields).
- Metrics/alerting on: KYC failure-rate spikes, login-lockout spikes, SOS trigger volume, WebSocket connection health, queue depth for background tasks.

## 31. Push Notifications

- Expo Notifications → APNs/FCM. Payload is always generic — e.g., "New DITSALA message", "SOS alert from a Circle member" (no sender name/content in the push payload itself, to avoid leaking metadata to the OS notification tray / lock screen beyond what's unavoidable); full detail loads only after in-app authentication.

## 32. Rate Limiting, Abuse & Fraud Controls

- Per-IP and per-account rate limits on: OTP sends, email verification sends, login attempts, invitation issuance, contact requests sent, SOS triggers (protect against griefing via repeated false SOS — still always allow genuine triggers through, tuned conservatively).
- Upload validation: content-type/magic-byte checks on any client-declared media type, size caps, and SSRF protection on any server-side fetch of a client-supplied URL (there should be very few such paths; enumerate and allowlist in `SECURITY.md`).

## 33. Account Recovery

High-assurance recovery for a user who has lost their device and cannot use routine biometric unlock:

1. Recovery request initiated via email + phone re-verification (§10/§11).
2. Fresh Smile ID **SmartSelfie Authentication** (1:1 match) against the user's existing Smile ID-enrolled identity, addressed by `smile_id_job_id`/partner user reference — **not** a document re-capture, and not DITSALA supplying or re-transmitting any stored image, since none is stored (§5, §34). The match happens entirely within Smile ID's system on Smile ID-held enrollment data; DITSALA receives only the pass/fail + score. This proves "same face as the verified identity" (the actual security property recovery needs) while keeping DITSALA's own retention posture at zero raw imagery.
3. Next-of-kin attestation step: the recovery flow notifies the registered next-of-kin (§13) that a recovery is in progress, giving them a window to flag it as suspicious via a simple link (not a hard blocker on recovery, but a logged signal reviewed by `trust_safety` if flagged).
4. On success: new device registered, new DITSALA Code set, all prior devices/sessions revoked, all Signal sessions with existing Circle contacts require re-establishment (expected — this is the correct Signal Protocol behavior for a lost-device scenario, and existing contacts see the "safety number changed" warning per §23, which is the intended detection mechanism against a fraudulent recovery).
5. Every recovery attempt (success or failure) is written to `account_recovery_requests` and `audit_log`.

## 34. Compliance & Regulatory

### 34.1 Lawful basis by processing activity

| Activity | Lawful basis | Citation |
|---|---|---|
| KYC document + biometric capture | Explicit, opt-in consent, separately captured (not bundled into general T&Cs) before the Smile ID SDK opens; purpose strictly limited to identity verification and stated as such in the consent copy. Biometric data is "special personal information" (POPIA) and requires this heightened consent, not the ordinary-processing consent used elsewhere in onboarding. | POPIA §26–27 (special personal information); Botswana DPA equivalent (sensitive personal data) |
| Account data generally (email, phone, name, DOB) | Consent + contractual necessity (processing required to provide the service the user is signing up for) | POPIA §11(1)(a)/(b) |
| SOS location disclosure to Circle/next-of-kin during an armed/escalated event, overriding standing share settings | Protection of a legitimate/vital interest of the data subject — the one designed exception to explicit per-share consent, scoped narrowly to the SOS event window only (§26) | POPIA §11(1)(d); Botswana DPA public/vital-interest ground |
| Security logging, fraud/abuse rate-limiting, audit_log | Legitimate interest in service integrity and accountability, no special-category data involved | POPIA §11(1)(f) |

### 34.2 Data minimization & retention (POPIA §14 / Botswana DPA storage-limitation principle)

- **Biometric/KYC imagery**: zero retention in DITSALA-controlled storage, at any time, for any purpose (§5, §33) — the strongest defensible position under the §14 requirement that records not be kept longer than necessary for the purpose, since "necessary" here is fully served by Smile ID's own job record plus our stored `result_summary`. DITSALA's contract with Smile ID caps *their* retention of the enrollment image to the lifetime of the DITSALA account plus a bounded post-deletion window (target: ≤30 days after account hard-delete), specified as a Data Processing Agreement term, not left to Smile ID's default.
- **`location_pings`**: retained only for the duration of the active `location_shares` grant plus 24 hours (covers the `location_access_log` transparency use case, §25), then hard-deleted by a scheduled task. Exception: pings attached to an `sos_events` record are retained 90 days post-event (legitimate interest in safety follow-up / potential legal process, POPIA §11(1)(f)), then hard-deleted.
- **`audit_log`**: retained 5 years (accountability/dispute-resolution legitimate interest; contains no P1/P2 content so carries materially lower privacy risk, and the multi-year window is itself the norm for security/audit trails under both POPIA and Botswana DPA guidance on legitimate-interest retention).
- **`account_recovery_requests` / `login_attempts`**: retained 12 months (fraud-pattern detection), then hard-deleted.
- **Account deletion cascade**: `deactivated` → 30-day self-service grace window (reversible) → hard-delete of all P0–P2 data on expiry; `banned` → immediate soft-delete, hard-delete after any applicable legal hold expires (default: no hold, so effectively the same 30-day operational window unless trust_safety flags an active investigation). `audit_log` entries recording that a deletion occurred are themselves P3 and outlive the deletion (they contain no personal content beyond an account id reference, which is retained under the audit-log schedule above).
- These figures are the concrete numbers `DATA_RETENTION.md` (§36.2) must implement; they are binding on the schema (e.g., `location_pings` sweep interval, `audit_log` archive tier) and not just narrative policy.

### 34.3 Cross-border transfer (POPIA §72 / Botswana DPA equivalent)

Smile ID, Twilio, and the transactional email provider (§3.4) all involve personal information leaving South Africa/Botswana to processor infrastructure elsewhere. POPIA §72 permits this only where the recipient is subject to a law/binding agreement providing adequate, POPIA-equivalent protection, or the data subject has consented, or the transfer is necessary for contract performance. Compliance mechanism, applied uniformly to all three: (1) a signed Data Processing Agreement with each vendor incorporating GDPR-standard Standard Contractual Clauses or an equivalent adequacy mechanism, executed before that vendor is enabled in production; (2) the transfer and named vendor disclosed in `PRIVACY_POLICY.md` at the point of consent capture, satisfying the consent alternative as a backstop. This is a **launch blocker**, not a Phase 8 cleanup item — the DPAs must exist before Phase 2 (KYC/OTP) goes live against production credentials, tracked in `docs/SECURITY_GAPS.md` until signed.

### 34.4 Data subject rights

Access, correction, and deletion requests are implemented as backend endpoints (§28 admin can action them) with a **30-calendar-day response SLA**, documented in `PRIVACY_POLICY.md` — aligned to South Africa's PAIA default response period and safely within Botswana DPA norms, adopted as a single global SLA rather than jurisdiction-conditional logic.

### 34.5 Third-party processor disclosure

Smile ID (biometric/KYC processing), Twilio (phone verification), and the email provider must be named explicitly in `PRIVACY_POLICY.md` as sub-processors, with their role, the categories of data they receive, and (per §34.3) the cross-border transfer safeguard in place for each.

## 35. Infrastructure, Environments & Deployment

- Environments: `local` (docker-compose: Postgres, Redis, coturn, Mailpit), `staging`, `production`.
- `infra/docker-compose.yml` brings up the full local backend dependency stack; `apps/mobile/eas.json` holds EAS build profiles (`development`, `preview`, `production`) — development builds from day one, Expo Go is never a target per the locked decisions.
- CI (per Phase 0): lint + type-check + test for backend (pytest), mobile (Jest/RNTL), admin (Vitest + Playwright for critical flows), run on every PR.
- Dependency scanning (e.g., `pip-audit`/`npm audit`/Dependabot) wired in before Phase 8 hardening, but the CI hook itself is a Phase 0 concern.

## 36. Policy Documents

The following live in `docs/` and are written/maintained as part of Phase 8 (though drafted early where they constrain design decisions sooner — e.g., `DATA_RETENTION.md` retention windows affect the `location_pings` schema in §4.6):

1. **PRIVACY_POLICY.md** — what's collected (identity, biometric, location, next-of-kin, device/usage metadata), why, third-party processors (Smile ID, Twilio, email provider), user rights, POPIA + Botswana DPA framing.
2. **DATA_RETENTION.md** — implements the concrete retention windows fixed in §34.2 (KYC imagery: zero DITSALA-side retention; `location_pings`: share duration + 24h, or 90 days if SOS-linked; `audit_log`: 5 years; `login_attempts`/`account_recovery_requests`: 12 months) and the account-deletion cascade timelines (§14, §34.2) — this document operationalizes those numbers, it does not re-derive them.
3. **SECURITY.md** — the non-negotiables from §7 restated for an external audience, responsible-disclosure contact/process, summary of the E2EE architecture (§6) at a level appropriate for public trust communication without exposing exploitable detail.
4. **KYC_POLICY.md** — Smile ID processing detail, biometric consent language, manual review process, appeal path for a rejected/manual_review account.
5. **ACCOUNT_RECOVERY.md** — user-facing explanation of §33's flow, expectations set (why re-verification is required, why existing contacts see a safety-number-changed warning post-recovery).
6. **DOCUMENTATION.md** — local setup (docker-compose, env vars per app's `.env.example`), architecture overview (links back to this spec), deployment runbook for staging/production.

Also maintained: **`docs/SECURITY_GAPS.md`** — living document of any feature shipped behind an interface because it could not yet be built to the §7 standard, per Working Rule 8 of the kickoff prompt. Empty at Phase 0; expected to gain entries as edge cases surface (e.g., initial group-call support deferred per §27 is *not* a security gap, just a scope decision — logged in an ADR instead, `docs/adr/`).

---

## Resolved per legal review (previously open items)

The compliance-sensitive judgment calls from the prior draft are now resolved against POPIA and the Botswana DPA rather than left as founder calls:

- **KYC/biometric retention** (was: §36.2 "pending legal input") — resolved to zero DITSALA-side retention of raw imagery, POPIA §14/§26-27 driven (§5, §34.2). `kyc_documents` schema (§4.1) updated accordingly: `raw_result_ref` replaced with `result_summary` (scores/decision only, no imagery pointer).
- **Recovery liveness match** (was: §33 step 2 "match against original capture") — resolved to Smile ID SmartSelfie *Authentication* against Smile ID's own enrollment record, consistent with the zero-retention posture above; DITSALA never holds or re-supplies the original image (§33).
- **SOS overriding standing consent** (was: §26 "confirm you're comfortable") — resolved as a documented lawful-basis exception (POPIA §11(1)(d), legitimate/vital interest of the data subject), not an ad hoc override (§26).
- **Cross-border transfer of KYC/OTP/email data to foreign processors** — newly identified as a POPIA §72 requirement not covered in the prior draft; added as §34.3, and flagged as a **launch blocker**: signed DPAs with SCCs (or equivalent) for Smile ID, Twilio, and the email provider must exist before Phase 2 goes live against production credentials.

## Settled (final)

- **§3.4** — **Resend** stands as the `EmailProvider` for launch. Rationale: simpler DX and fast integration at launch scale, and the choice is fully interface-isolated (§3.4), so switching to SES later is a new adapter, not a rearchitecture — there is no lock-in cost to defer optimizing this further.
- **§27** — **Group calls are out of scope for v1**, confirmed. 1:1 voice/video ships first; group calls are a post-launch roadmap item, not a security or compliance gap, and require no entry in `SECURITY_GAPS.md`.

All prior open items are now resolved. This document is considered final for Phase 0 kickoff.
