# ADR 0013: NaCl-based E2EE instead of native libsignal, to ship a real chat UI now

Status: Accepted — supersedes ADR 0005's "wait for a native build environment" conclusion for the *client-side crypto choice* only. ADR 0005 remains an accurate record of why libsignal specifically wasn't buildable here; this ADR is the explicit, user-approved decision to stop waiting on it.

## Context

The backend's messaging domain (`domain/messaging/service.py`, all of `/api/v1/messaging/*`) has been real and fully tested since Phase 4: it relays ciphertext, key material, and Sender Key distribution messages, and never decrypts anything, by design. What was missing was the client half — actually running the cryptography — because the locked decision (`CLAUDE.md`: "E2EE | Signal Protocol via libsignal, native Expo module") requires a native module that doesn't exist as an off-the-shelf React Native package: Signal's own `libsignal-client` ships Kotlin bindings (Android) and Swift bindings (iOS) separately, with no unified RN JS bridge. Writing one is real, substantial, specialized native-module engineering — Kotlin + Swift + a JS bridge — realistically weeks of work, and this dev environment has no Xcode/Android Studio to write or verify that code against locally (installing Android Studio here was evaluated and rejected: this machine had ~1.1-2GB disk and well under 1GB RAM free, an order of magnitude short of what Android Studio + SDK + Gradle needs, and it wouldn't have been sufficient by itself anyway — EAS already handles cloud native builds, the actual missing piece is the bridge code itself).

The user explicitly asked for a real, working, end-to-end messaging platform now, not a further-deferred one, and was given the honest trade-off (see the conversation this ADR comes from): keep waiting on libsignal, start the native bridge as a multi-session background effort, or adopt a JS-only public-key crypto library today. **The user chose the JS-only path.**

## Decision

Client-side E2EE now uses **TweetNaCl** (`tweetnacl` + `tweetnacl-util`, pure JavaScript, audited, no native compilation) plus `react-native-get-random-values` (a small, widely-used polyfill providing a real CSPRNG-backed `crypto.getRandomValues` — RN has no built-in one). No backend changes were needed: the existing `identity_keys`/`signed_prekeys`/`one_time_prekeys`/`sender_keys` tables and REST/WS routes are protocol-agnostic (opaque `bytes`/blobs), so this is a pure client swap.

**Key material** (`apps/mobile/lib/crypto/e2ee.ts`), per device:
- One long-term **Ed25519 signing keypair** (`nacl.sign.keyPair()`) — the device's identity. Its public key is what's authenticated out-of-band (this is the value a future safety-number UI would fingerprint).
- One long-term **X25519 identity keypair** (`nacl.box.keyPair()`) — used only as one of two DH terms in session setup (see below), never rotated.
- Both public keys are packed into the single 64-byte `IdentityKey.public_identity_key` field the schema already has (32 bytes X25519 identity public key + 32 bytes Ed25519 signing public key) — no migration needed.
- A rotating **X25519 signed prekey** (medium-term), whose public key is signed with the Ed25519 identity key (`nacl.sign.detached`) before upload — recipients verify this signature against the sender's identity key before ever trusting a prekey, which is exactly what stops a malicious/compromised server from substituting its own key (the same MITM protection Signal's own signed-prekey design provides).
- A batch of single-use **X25519 one-time prekeys**, uploaded via the existing `upload_one_time_prekeys` endpoint, each consumed at most once by `get_prekey_bundle`.

**Session-less, per-message X3DH-lite** for 1:1 messages: rather than caching a Double-Ratchet session, every message derives a fresh symmetric key: the sender generates a **fresh ephemeral X25519 keypair per message**, computes two ECDH terms — `(ephemeral_secret, recipient_prekey_public)` and `(sender_identity_x25519_secret, recipient_prekey_public)` — and hashes both together (SHA-512 via `nacl.hash`) into the final key. The recipient, holding the corresponding prekey secret plus the sender's identity and ephemeral public keys (both travel with the ciphertext), recomputes the same two terms and the same key. The message itself is sealed with `nacl.secretbox` under that key.

This gives:
- **Forward secrecy per message** (a fresh ephemeral key each time — arguably *stronger* than caching a session key, at the cost of ~32 bytes of overhead and a cheap DH per message).
- **Sender authentication** (only the real sender's identity secret produces a key the recipient can also derive).
- **MITM resistance on key distribution** (signed prekeys, verified before use).

**What this is not**: Signal's Double Ratchet, so there is no post-compromise security (recovering after a private key is later stolen) the way a full ratchet provides, and no deniability properties Signal's design specifically targets. This is disclosed, not hidden — see "Consequences" below.

**Groups**: Signal-style Sender Keys, using the existing `sender_keys` table as designed — a random 32-byte symmetric key per (conversation, sending device), distributed to every other member individually via the same 1:1 mechanism above, then used with `nacl.secretbox` + an incrementing counter for actual group messages (fan-out-once, not fan-out-per-message).

**Media**: a random per-object symmetric key, `nacl.secretbox`-encrypts the file bytes client-side before upload through the existing `StorageProvider` presigned-URL flow (backend never sees plaintext media, unchanged from the original design), with the object's key delivered the same way a text message's key is.

**Private key storage**: `expo-secure-store` (already the pattern `lib/session.ts` uses for tokens) — never written to plain `AsyncStorage`, never sent to the server.

## Addendum: `react-native-quick-crypto` evaluated and deferred

The user asked about swapping the pure-JS crypto engine for `react-native-quick-crypto` (native C++/JSI, OpenSSL-backed, "hundreds of times faster") plus `expo-sqlite` "configured with SQLCipher" for local chat storage. Both were checked against their real, current state rather than assumed:

- `react-native-quick-crypto` v1.x requires RN's New Architecture, Nitro Modules, and `expo prebuild` — real, but native, meaning (a) it cannot run under Jest, so the crypto layer would lose the exact kind of real, verified round-trip testing this ADR's TweetNaCl implementation has (17 passing tests covering key generation, encryption, tampering, and impostor rejection), with nothing left to check here beyond type-checking; (b) it implements Node's `crypto` API, which has no NaCl-secretbox equivalent, so adopting it means redesigning the symmetric layer around AES-256-GCM or ChaCha20-Poly1305 rather than a drop-in swap; (c) X25519/Ed25519 coverage in its native build is plausible but unconfirmed without a real device.
- `expo-sqlite` does **not** support SQLCipher out of the box — it's plain SQLite. Real whole-file encryption would need a different native SQLite build, a separate and less mainstream integration than "add a config option."

**Decision**: keep TweetNaCl for now — a real, fully-tested implementation beats an unverifiable-here "faster" one, especially for the crypto layer specifically. `react-native-quick-crypto` is a legitimate future swap once a real device/EAS build is in the loop to actually verify the native path; revisit then, not before. For local chat history, the agreed design is a **ciphertext-only** cache in plain `expo-sqlite`, decrypted in memory on read — real "nothing sensitive on disk in plaintext" without SQLCipher or a new native dependency. **Not built this pass** (chat currently fetches from the server each time, no offline cache yet) — the screens themselves were the priority; this is a real, tracked next step in `docs/SECURITY_GAPS.md`, not a silent gap.

## Consequences

- `CLAUDE.md`'s locked-decision table is updated: E2EE is now "TweetNaCl (X25519/Ed25519/XSalsa20-Poly1305), pure JS — see ADR 0013" instead of "Signal Protocol via libsignal, native module."
- A real chat UI (conversation list, message bubbles, media) ships now, against the exact same backend that was already built and tested for this.
- The crypto module itself is unit-tested with real key generation/encrypt/decrypt round trips in Jest (pure JS, no native module needed to test it — a genuine advantage over the native-libsignal path, which could never be exercised in this environment at all).
- If a real Signal Protocol implementation is ever built later (native bridge, or a maintained RN package appears), migrating means a new key-registration version and a transition period where both schemes are understood — not attempted here, and not needed unless the trade-off above stops being acceptable.
- The lack of a ratchet is the one trade-off worth remembering if this product's threat model ever includes "attacker recovers a device's current keys and should still not read future messages after the user takes action" — that specific guarantee is not provided by this design.
