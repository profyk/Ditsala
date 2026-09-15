# ADR 0007: WebRTC calling is real, complete code — unverified on a device

Status: Accepted (Phase 6)

## Context

docs/DITSALA_MASTER_SPEC.md §27 calls for WebRTC voice/video calling, DTLS-SRTP end-to-end, coturn as TURN relay only, group calls out of v1 scope (settled). This sits next to ADR 0005 (the libsignal native-module gap), which drew a hard line: don't build a chat UI against a stub cipher, because it would look like working E2EE without being any such thing. Calls needed a judgment call about whether the same line applies.

## Decision: this is not the same situation as ADR 0005, and the full stack was built

`react-native-webrtc` differs from libsignal in the property that mattered for ADR 0005's decision: nothing here required *writing* cryptographic or native binding code whose correctness this session had no way to verify. `react-native-webrtc` is a mature, complete, correct third-party implementation — using its JS API (`RTCPeerConnection`, `mediaDevices.getUserMedia`, `RTCView`) is the same category of integration as `expo-camera` in Phase 5, just a heavier native module. So the full stack was built for real:

- **Backend** (`domain/calls/service.py`, `/api/v1/calls/*`): real call state machine (ringing/active/ended/missed/declined), WebRTC signaling relay (opaque SDP offer/answer/ICE candidates) over the same realtime WebSocket transport messaging uses, `GET /calls/ice-servers` (Google STUN + the self-hosted coturn from `infra/docker-compose.yml`), and voice<->video switching mid-call (`switch_media`) — all backed by real Postgres integration tests, no mocks of our own code.
- **Mobile**: `lib/call-session.ts` (real `RTCPeerConnection` lifecycle — offer/answer, ICE candidate exchange, local/remote stream wiring, mute, and the voice<->video track add/remove + renegotiation `switch_media` needs), `lib/call-context.tsx` (app-wide incoming-call routing via `lib/messaging-ws.ts`'s shared socket), and real screens (`app/calls/incoming.tsx`, `app/calls/active.tsx` with actual `RTCView` local/remote video).
- `react-native-webrtc` + `@config-plugins/react-native-webrtc` were added as real dependencies and wired into `app.json`'s plugin list (mic/camera permission strings) — not stubbed out.

## What is still unverified, and why that's a different kind of gap than ADR 0005's

Unlike libsignal, there is nothing to write and get wrong here — the risk is only "does the wiring actually run," not "did we fake the cryptography." That's the same runtime-verification boundary every other mobile feature in this project already carries (see CLAUDE.md's "Not runtime-verified" notes since Phase 2): `tsc`, ESLint, and Jest (with `react-native-webrtc` mocked, per `lib/call-session.test.ts`) all pass, but nothing has run on a simulator, device, or EAS build, because this environment has no Xcode, Android Studio, or EAS credentials — the same constraint recorded since Phase 2, not a new one. `react-native-webrtc` specifically needs a native rebuild (`expo prebuild` + a real iOS/Android compile) before it can run at all, which is a heavier ask than the pure-JS Expo modules used so far, but the *code* is complete and correct against the library's real, documented API — verified by reading the installed package's actual `.d.ts` files (not guessed).

`infra/docker-compose.yml`'s `coturn` service was already scaffolded in Phase 0 and is unchanged; it was not run in this environment either (same Docker-not-installed constraint as everything else — see `CLAUDE.md` "Local dev"), so the TURN relay path specifically has never been exercised, only STUN-reachable (same-network) calls would work if this were run today without a running coturn instance.

One real, disclosed simplification: `lib/call-session.ts` does not implement the W3C "Perfect Negotiation" pattern for resolving two simultaneous renegotiation offers colliding. With exactly two participants and `switch_media` (a deliberate, user-triggered action) as the only renegotiation trigger, both sides hitting "switch" in the same round trip is the only scenario this would affect — left for whoever first runs this on a real device, per `docs/SECURITY_GAPS.md`.

## Consequences

- Whoever picks this up next with EAS/Xcode/Android Studio access should run `expo prebuild`, do a real device build, and place a call between two devices before trusting this beyond "the code is complete and internally consistent" — that's the single next verification step, not a rewrite.
- The backend signaling contract (event shapes, REST endpoints) is stable and tested; a native rebuild only needs to prove the mobile half actually drives real audio/video, not renegotiate the protocol.
- Group calls remain explicitly out of v1 scope (settled) — `CallService.initiate_call` enforces `direct`-conversation-only at the backend, so this isn't revisited by accident.
