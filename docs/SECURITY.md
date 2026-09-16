# DITSALA Security

*Public-facing summary of DITSALA's security architecture and practices, restating docs/DITSALA_MASTER_SPEC.md §7's non-negotiables at a level appropriate for external trust communication — without exposing exploitable detail.*

## 1. Our non-negotiables

1. No custom cryptography, anywhere. We use established, widely-reviewed primitives (the Signal Protocol for messaging, Argon2id for password-equivalent secrets, TLS in transit) rather than anything we designed ourselves.
2. No plaintext DITSALA Codes, tokens, or biometric templates are ever stored.
3. **No admin path, ever, can retrieve decrypted message content** — this is an architectural fact, not a policy we could be pressured into changing, because our servers never hold the keys needed to decrypt.
4. Every external identity/communications provider (KYC, phone verification, email) sits behind an internal interface with a real production adapter and a separate sandbox adapter for testing, selected only by server configuration — never a hand-rolled bypass in a production code path.
5. Every database schema change goes through a reviewed migration. There is no manual, undocumented database surgery.
6. Anything we can't yet build to this standard is isolated behind an interface and tracked publicly in our internal gap register, rather than shipped as a silently weaker version of the real thing.

## 2. End-to-end encryption

DITSALA messaging uses the **Signal Protocol** — the same cryptographic design used by Signal and WhatsApp — via the `libsignal` reference implementation. Each device generates its own key material on-device; the server relays public key material and encrypted messages it cannot read. Key elements:

- **X3DH** key agreement establishes a shared secret between two devices without either ever transmitting a private key.
- **The Double Ratchet** algorithm derives a fresh encryption key for every message, so compromising one message's key does not expose past or future messages (forward secrecy and post-compromise security).
- **Group messaging** uses Signal's Sender Key mechanism, distributed peer-to-peer through the same relay.
- **Voice/video calls** use WebRTC with DTLS-SRTP, meaning call media itself is also end-to-end encrypted between participants; our infrastructure only relays call *signaling* (who's calling whom) and, when needed, network traffic via a TURN relay for connectivity — never the decrypted media stream.

## 3. Identity verification

Every account is verified against a real, government-issued ID and a biometric liveness check before it can message anyone, via our identity-verification partner. **We never store the document photo or the liveness selfie** — only the verification outcome. See `KYC_POLICY.md` for detail.

## 4. Account security

- Your account secret (the "DITSALA Code") is hashed with **Argon2id**, a memory-hard algorithm designed specifically to resist large-scale offline cracking attempts, and is never logged or displayed after you set it.
- Every full login requires your DITSALA Code *and* a fresh biometric liveness check — never one alone. Routine app unlock on a device you've already logged into uses your device's own local biometrics (Face ID/fingerprint) to protect a locally-stored session token; that check never leaves your device and never re-authenticates against our servers.
- Repeated failed login attempts lock an account with escalating delays, and repeated attempts from the same network address are separately rate-limited, so that abuse targeting one account or spread across many accounts is both throttled.

## 5. Data classification and access control

Internally, every field in our database is classified by sensitivity (cryptographic secrets, biometric/KYC data, message/location content, or operational metadata), and our database enforces this with role-level permissions — a support or moderation action literally cannot query fields it has no legitimate reason to see, regardless of what the application code intends. Every admin action is logged in an append-only audit trail, and any access to KYC detail additionally requires a logged, non-empty justification before the record is shown, not after.

## 6. Media and file handling

Media you send (photos, voice notes, etc.) is encrypted on your device before it ever leaves it. Our storage layer holds only ciphertext behind short-lived, signed download URLs — it cannot inspect, preview, or scan the content, by the same architectural guarantee described in §2. This means traditional server-side upload validation (checking a file's actual bytes match its claimed type, virus scanning, etc.) cannot meaningfully apply to message media: the server only ever sees encrypted bytes indistinguishable from random data, regardless of what's actually inside. Validation for encrypted media instead happens on the *sending* device before encryption, and object size limits are enforced server-side to prevent storage abuse — but content inspection of message media is not a control DITSALA's server-side architecture can offer, as a direct consequence of never being able to read message content at all (§7.3 of our engineering spec). Any other upload path we introduce that *isn't* pre-encrypted client-side media (for example, admin-facing file uploads, if added in future) would need conventional content-type and size validation, and any such path will be enumerated here before it ships.

## 7. Reporting a security issue

If you believe you've found a security vulnerability in DITSALA, please report it through the in-app support channel rather than disclosing it publicly. We ask that you:

- Give us a reasonable window to investigate and address the issue before any public disclosure.
- Avoid accessing, modifying, or deleting other users' data while investigating.
- Avoid actions that could degrade the service for other users (e.g., load testing without coordination).

We commit to acknowledging reports promptly and keeping you informed of remediation progress.
