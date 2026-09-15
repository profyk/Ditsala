# ADR 0005: The libsignal native module is not built — what that does and doesn't mean

Status: Accepted (Phase 4)

## Context

docs/DITSALA_MASTER_SPEC.md §6 requires the Signal Protocol via libsignal (the official Rust core, with Swift/Kotlin bindings) wrapped in a native Expo module with a config plugin — explicitly ruling out "JS-only or hand-rolled crypto." This is the correct call: E2EE is the entire trust basis of the product, and a JS reimplementation of X3DH/Double Ratchet/Sender Keys would be exactly the kind of custom cryptography §7.1 forbids.

This environment has no Xcode, no Android Studio, no Rust toolchain, and no EAS build access. There is no way to write, compile, or verify a native iOS/Android binding here — not even to the "code-complete but unverified" standard the Smile ID and Twilio adapters were held to in Phases 2-3, because there's no way to write plausible native Swift/Kotlin/Rust glue code without a compiler to catch mistakes, let alone test it.

## Decision

**Everything on the backend for Phase 4 is built completely and normally**, because the backend's role in the Signal Protocol is inherently crypto-agnostic: it stores and relays public key material (identity keys, signed prekeys, one-time prekeys, Sender Key distribution messages) and opaque ciphertext, and never decrypts anything, by design (§7.3). `domain/messaging/service.py`, the `/messaging/*` REST routes, and the WebSocket transport are all real, fully tested code — not placeholders — because none of it depends on which cryptography library eventually generates the bytes it stores.

**What is explicitly not built**: the native Expo module itself (the actual libsignal bindings — X3DH key agreement, the Double Ratchet, Sender Key encryption/decryption) and the mobile screens that would call it (conversation/chat UI, message composition). Building chat *screens* that call a stubbed or fake "encrypt" function would be worse than not building them: it would look like working E2EE messaging without being any such thing, in an app whose entire value proposition is trustworthy communication. That is precisely the "weaker fallback shipped silently" Working Rule 6 prohibits — so this gap is isolated and documented instead, not papered over with mobile screens that create the appearance of encryption.

**Mobile Phase 4 scope is therefore limited to the non-crypto plumbing**: the REST API client methods for key upload/prekey-bundle retrieval, conversation/message CRUD, and a WebSocket client wrapper — all real HTTP/WS code a future native-module integration will sit behind. No message composer or chat thread UI is built in this phase.

## Consequences

- The single highest-priority next step for a developer with native build tooling is: build the Expo config plugin + native module wrapping libsignal (per §6), then wire it to the already-complete backend endpoints documented here. Nothing on the backend should need to change to support that integration — the REST/WS contract is the integration point.
- `docs/SECURITY_GAPS.md` carries this as the headline open item — it is the largest and most consequential gap in the codebase at this point, more so than the KYC/OTP vendor-credential gaps, because it blocks the product's core function rather than one onboarding step.
- The WebSocket transport (`services/realtime/websocket_manager.py`) is in-memory/single-process. Redis pub/sub (already locked in for "cache/realtime/queues", §3) is the documented evolution path once this needs to fan out across multiple backend instances — not built now because a single process is all this phase's actual scope requires, and building the distributed version first would be solving a problem that doesn't exist yet.
- `purge_expired_messages` (disappearing messages, §21) is domain logic only — no scheduler wires it up to run periodically yet. That's Phase 8's job (background task infrastructure), consistent with `tasks/README.md`'s existing scope note.
