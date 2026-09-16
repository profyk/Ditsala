# DITSALA MEET — Architecture & Master Spec (v1.0)

Companion to `docs/DITSALA_MASTER_SPEC.md`, same status: locked decisions below are not to be revisited without asking, exactly like the parent spec's own rule. Ditsala Meet is a professional video-conferencing and AI-meeting-assistant product, integrated into the existing DITSALA ecosystem rather than a disconnected new one — reuses the existing user identity, backend, and infra wherever that's the right call (per this document's own §11 "reuse, don't rewrite" audit), and only introduces new services where the product genuinely needs new capability (a real SFU, an AI pipeline).

## 0. What this is, in one paragraph

A meeting starts a real WebRTC session through a managed SFU (LiveKit), served from a new web app at `meet.ditsala.app`, authenticated with the same DITSALA account every user already has. During the meeting, an AI pipeline (Deepgram for live transcription, Claude for understanding it) builds a running note of decisions, action items, and topics. After the meeting, that becomes a searchable, permanent Meeting Workspace attached to the user's account. Everything below exists to make that one paragraph true end to end, not to chase every feature in this doc's own §55-style feature list at once — see §9's phased plan.

## 1. Product structure & identity (spec §1)

```
apps/
  meet/          NEW — Next.js web app, meet.ditsala.app
backend/app/
  domain/meetings/     NEW — meeting lifecycle, participants, AI pipeline orchestration
  domain/meet_ai/      NEW — transcription + Claude summarization, behind Protocol interfaces
  api/v1/routers/meetings.py   NEW — REST endpoints
  api/v1/routers/meet_ws.py    NEW — Meet-specific realtime events (chat, reactions, raise-hand — NOT media, that's LiveKit's job)
```

**Identity: reused, not rebuilt.** A Meet session authenticates with the exact same access-token JWT `AuthService`/`decode_access_token` already issues (`app/core/security.py`) — `meetings.py`'s routes sit behind the same `CurrentUserDep` every other authenticated DITSALA route uses. There is no separate Meet login. Guests (§35) are the one deliberate exception — see §5.4.

## 2. Realtime/WebRTC architecture (spec §3) — decision: LiveKit

**Decision: LiveKit**, not mediasoup or Janus.

| Criterion | LiveKit | mediasoup | Janus |
|---|---|---|---|
| Client SDKs | Official React, React Native, Swift, Kotlin, JS | None — you build your own client room/track state machine on top of its low-level transport primitives | None official; community bindings, older DX |
| Path to MVP | Hosted (LiveKit Cloud) today, self-host later on the *same* API | Self-host from day one — real ops burden immediately | Self-host, C-level ops burden, plugin architecture |
| AI/agent integration | First-class "Agents" framework — subscribe to any participant's audio track server-side in real time, exactly what live transcription needs | Build the audio-tap pipeline yourself | Build it yourself, less tooling |
| Recording | Built-in Egress service (room→file, or per-track) | Build your own recording pipeline (e.g. via a headless client) | Custom plugin work |
| Adaptive quality | Simulcast + dynacast + built-in bandwidth estimation, on by default | You wire up simulcast yourself | Limited, manual |

This is exactly the "developer productivity + future extensibility + cost efficiency" combination §3 asks for: **MVP cost is a LiveKit Cloud subscription (usage-based, free tier covers early testing), not a provisioned media server fleet.** Scale-up path is self-hosting `livekit-server` (open source, Apache 2.0) on the same AWS infrastructure `docs/CI_CD.md` already sets up for the backend — no client-side rewrite needed, since the SDK talks to the same protocol either way.

**What LiveKit is responsible for**: media transport, SFU routing, simulcast/adaptive bitrate, recording (Egress), and room/participant state (who's in the room, track publish/subscribe). **What it is *not* responsible for**: meeting metadata (who's invited, when it's scheduled), chat/polls/Q&A/whiteboard, or anything AI. Those are DITSALA's own domain — see §4.

## 3. Data model (spec §39)

New tables, `backend/app/models/meetings.py`, following the exact conventions `app/models/` already uses (`UUIDPrimaryKeyMixin`, `TimestampMixin`, `ondelete="CASCADE"` from `meetings.host_user_id`/`meeting_participants.user_id` back to `users.id` — same deletion-cascade guarantee as ADR 0009, no separate cascade logic needed for Meet data):

| Table | Purpose |
|---|---|
| `meetings` | id, host_user_id, livekit_room_name (unique), title, meeting_type (`standard`\|`webinar`\|`classroom`\|`interview`\|`town_hall`\|`conference`), status (`scheduled`\|`live`\|`ended`\|`cancelled`), scheduled_start_at, scheduled_duration_minutes, actual_start_at, actual_end_at, password_hash (nullable — Argon2id, same as `ditsala_code_hash`), waiting_room_enabled, locked_at, recording_enabled |
| `meeting_participants` | meeting_id, user_id (nullable — null means guest), guest_display_name, role (`host`\|`co_host`\|`participant`), joined_at, left_at, livekit_participant_identity |
| `meeting_invites` | meeting_id, invited_user_id (nullable), invited_email (nullable, for non-DITSALA invites), status |
| `meeting_recordings` | meeting_id, storage_key (via the *existing* `StorageProvider` interface — §11), duration_seconds, status (`processing`\|`ready`\|`failed`), started_at |
| `meeting_transcripts` | meeting_id, speaker_user_id (nullable), text_segment, started_at_ms, ended_at_ms — the raw transcript feed, append-only like `audit_log` |
| `meeting_ai_notes` | meeting_id, kind (`summary`\|`decision`\|`action_item`\|`question`\|`topic`), content, source_transcript_range, edited_by_user_id (nullable — §15 "allow users to edit") |
| `meeting_messages` | meeting_id, sender_user_id (nullable for guest), body, sent_at — in-meeting chat, deliberately separate from DITSALA's E2EE `messages` table (§7.3's E2EE guarantee doesn't apply here — see §7 below for why that's an explicit, disclosed tradeoff, not an oversight) |
| `meeting_polls` / `meeting_poll_votes` | poll question, options (JSONB), anonymous flag / one row per vote |
| `meeting_questions` | Q&A: meeting_id, asker_user_id (nullable), body, upvotes, status (`pending`\|`approved`\|`answered`\|`hidden`) |
| `meeting_files` | meeting_id, storage_key, uploaded_by_user_id |
| `meeting_whiteboards` | meeting_id, snapshot (JSONB — the whiteboard's serialized shape data, e.g. tldraw/excalidraw's own document format) |
| `breakout_rooms` / `breakout_room_participants` | parent meeting_id, livekit_room_name (each breakout is its own LiveKit room), name |
| `meeting_analytics` | meeting_id, metric, value, recorded_at — join/leave timestamps, connection-quality samples |
| `meeting_audit_log` | Same append-only, no-FK-to-users shape as the existing `audit_log` (ADR 0009's reasoning applies identically) — host actions (mute-all, remove participant, lock, recording start/stop) |
| `organizations` / `organization_members` | §31 — deferred to Phase 5, modeled here so later phases don't need a schema rewrite, but not built out until then |
| `subscriptions` / `usage_records` | §44 — same treatment: modeled early, built in Phase 5 |

**Why a new `meeting_messages` table instead of reusing DITSALA's E2EE `messages`**: the existing `messages` table's entire design assumes Signal Protocol ciphertext the backend can't read (§7.3) — that's *correct* for 1:1/group DMs, but a meeting's in-call chat needs server-side moderation capability (a host can see and remove a message) and AI summarization access (§15's live notes need to see chat content), both of which are incompatible with true E2EE. This is disclosed here explicitly, not silently downgraded: **Meet chat is transport-encrypted (TLS) but not end-to-end encrypted**, same trust model as the AI transcript itself (the AI reads it, so it isn't E2EE — these are the same tradeoff).

## 4. API architecture (spec §40)

New router `api/v1/routers/meetings.py`, mounted at `/api/v1/meetings`, same `CurrentUserDep`/Pydantic-schema/service-layer conventions as every existing router:

- `POST /meetings` — create (instant or scheduled)
- `GET /meetings` / `GET /meetings/{id}` — list/detail
- `POST /meetings/{id}/join` — returns a **LiveKit access token** (server-mints via the `livekit-server-sdk` Python package, scoped to that room + that participant's identity + role-based grants — a host gets `roomAdmin: true`, a participant doesn't), *not* the LiveKit API secret itself (never sent to any client — §25/§53)
- `POST /meetings/{id}/guest-join` — §35: name only, no DITSALA account, issues a short-lived guest LiveKit token instead of a DITSALA access token
- `POST /meetings/{id}/end`, `/lock`, `/mute-all`, participant actions (mute/remove/promote) — host/co-host only, permission-checked server-side (never trust a client's claimed role)
- `POST /meetings/{id}/recording/start` / `/stop` — triggers LiveKit Egress, writes a `meeting_recordings` row
- Chat/polls/Q&A/whiteboard/breakout-room CRUD, same pattern
- `GET /meetings/{id}/summary`, `POST /meetings/{id}/notes/{note_id}` (edit) — the AI output (§15/§16)
- `GET /meetings/search?q=...` — §18, full-text search across `meetings.title` + `meeting_transcripts.text_segment` (Postgres `tsvector`, no new infra needed for v1 — see §12's cost-control note on why this isn't a dedicated search service yet)

A Meet-specific WebSocket (`api/v1/routers/meet_ws.py`) carries the *non-media* realtime events §41 lists (raise-hand, reactions, poll-created, chat — LiveKit has its own data-channel that could carry some of these instead; the decision to run a parallel DITSALA-side WebSocket rather than LiveKit's data channel is so chat/polls/Q&A persist to Postgres through the same code path as every other write, not two divergent state stores).

## 5. Security & auth architecture (spec §25, §53)

1. **LiveKit API key/secret live only in the backend's environment** (`LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`) — never shipped to any client. Every client (web, mobile) receives only a short-lived, room-and-identity-scoped LiveKit access token, minted server-side per §4.
2. **Meeting passwords**: Argon2id-hashed, identical treatment to `ditsala_code_hash` — never plaintext at rest.
3. **Waiting room**: participants land in a `waiting` sub-state (a `meeting_participants.status` value) before the host admits them — enforced server-side (the LiveKit token isn't minted with room-join grants until admitted), not a client-side gate that could be bypassed.
4. **Rate limiting**: meeting creation, join attempts, and chat messages all go through the *same* `RateLimiter` Protocol already built for DITSALA (`domain/ratelimit/interfaces.py`) — no second rate-limiting system.
5. **Guest join (§35)**: a guest gets a LiveKit token scoped *only* to that one room, valid only until the meeting ends, with no DITSALA account created and no row in `users` — `meeting_participants.user_id` is nullable specifically for this.
6. **Recording consent/visibility (§26)**: every participant's client shows a persistent "recording" / "AI active" / "transcription active" indicator whenever `meetings.recording_enabled` or the AI pipeline is on — driven by real server state via the realtime WebSocket, not a client-side assumption.

## 6. AI architecture (spec §15–18) — decision: Deepgram (live STT) + Claude (understanding)

Two different jobs, two different tools — conflating them would mean picking a worse tradeoff for one to accommodate the other:

- **Deepgram** (streaming speech-to-text): subscribes to each participant's audio track via a **LiveKit Agent** (a small Python worker process using `livekit-agents`, joining the room as a hidden participant), streams audio to Deepgram's real-time API, and writes `meeting_transcripts` rows as text arrives. Chosen for low-latency streaming transcription with per-speaker diarization support — the specific capability live captions need that a batch API (e.g. Whisper's REST endpoint) doesn't provide.
- **Claude** (via the Anthropic API — coherent choice given this codebase's own origin, and Claude's long-context window suits summarizing an hour-plus transcript in one pass): consumes the accumulating `meeting_transcripts` feed to produce `meeting_ai_notes` rows (summary/decision/action_item/question/topic), answers in-meeting questions ("what did we decide about X?" — §15) by querying the transcript-so-far plus prior notes, and generates the post-meeting executive summary/minutes.

Both providers sit behind `domain/meet_ai/interfaces.py` `Protocol`s (`TranscriptionProvider`, `MeetingIntelligenceProvider`), following the exact pattern every other DITSALA external dependency uses — a `Sandbox*` adapter for each is buildable without live credentials (echo/fixture-based), matching how `SandboxKycProvider` etc. work today.

**"What did I miss?" (§17)** and **searchable meetings (§18)** are both just queries over `meeting_transcripts`/`meeting_ai_notes` already being written during the meeting — no separate infrastructure, they're read paths on data the pipeline above already produces.

## 7. What's explicitly *not* end-to-end encrypted, and why that's disclosed, not hidden

DITSALA's core messaging product is E2EE — a hard architectural guarantee (§7.3 of the parent spec). **Meet cannot make the same guarantee and must not claim to**: live transcription and AI summarization both require the *server* (via the LiveKit Agent + Claude) to see meeting audio/chat content — that's the entire feature. This is the same category of disclosed tradeoff as a normal video-conferencing product (Zoom, Meet, Teams all work the same way for their own AI features) and must be stated plainly in Meet's own privacy surface (a `DITSALA_MEET_PRIVACY.md`, written when Phase 3 — AI — actually ships, not before, so it describes what's real rather than what's planned).

## 8. Reuse audit (spec §50) — what's reused vs. new

| Existing DITSALA piece | Reused as-is for Meet? |
|---|---|
| `User` model, JWT access tokens, `CurrentUserDep` | **Yes** — no second identity system (§1) |
| `RateLimiter` Protocol + `InMemoryRateLimiter` | **Yes** — same limiter, new keys |
| `StorageProvider` Protocol (S3-compatible) | **Yes** — recordings/files land in the same storage abstraction messaging media already uses |
| `PushProvider` (Expo push) | **Yes** — meeting-starting/invite notifications (§33) |
| `AuditLogRepository`-style append-only pattern | **Reused as a pattern**, new table (`meeting_audit_log`) — Meet's audit trail shouldn't share a table with account-security audit events, but should look identical in shape |
| Admin panel (`apps/admin`, RBAC) | **Extended, not duplicated** — a `data_subject_requests`-style new section, same `Permission` enum pattern (§43) |
| WebSocket `ConnectionManager` | **Not reused for media** (LiveKit replaces it entirely for anything audio/video) — reused for Meet's own non-media realtime events (§4) |
| Alembic migrations, repository-per-aggregate pattern, data classification registry | **Yes**, unchanged conventions |

## 9. Phased plan (spec §51) — what "Phase 1" means concretely

**Meet Phase 1 (complete):** `meetings`/`meeting_participants` tables + migration; `MeetingService` (create/join/end); LiveKit token minting; `apps/meet` scaffolded with a real join/room screen using LiveKit's React SDK; guest join. This is the smallest slice that is a *real, working* video call — matching this document's own §52 rule against fake functionality.

**Meet Phase 2 (complete, backend):** all real, tested code against real Postgres, live-introspected `livekit-api` calls (RoomService + EgressService), and migrations `8731972a18e2`/`e4f85b2192ae`:

- **Waiting room**: `meeting_participants.admission_status` (`waiting`\|`admitted`\|`removed`) — a non-host joining a `waiting_room_enabled` meeting lands `waiting` and gets no LiveKit token at all (`JoinResult.access_token` is `None`) until a host/co-host calls `admit_participant`; the participant's next `join` call then mints a real token. Enforced server-side the way §5.3 requires — no client-side-only gate.
- **Host/co-host controls**: `remove_participant` (real `RoomProvider.remove_participant`, force-disconnects at the SFU, marks `admission_status="removed"` so a removed user can't silently rejoin), `promote_co_host` (host-only), `set_participant_muted` (real `set_participant_can_publish` revocation — a client can't route around it), `set_locked`/`lock_meeting`.
- **Recording**: `start_recording`/`stop_recording` via real LiveKit Egress (`RoomCompositeEgressRequest` → S3), `meeting_recordings` table. `stop_recording`'s returned status is mapped from LiveKit's own `EgressStatus` enum (`EGRESS_COMPLETE`→`ready`, `EGRESS_FAILED`/`EGRESS_ABORTED`→`failed`) rather than assumed — see `services/meet/livekit.py`. No egress-completion *webhook* is wired (LiveKit supports one; not built this phase), so a recording's terminal status is only known synchronously from the `stop_recording` call itself, not from an async confirmation — tracked in `docs/SECURITY_GAPS.md`.
- **Reactions / raise-hand**: ephemeral, no DB row — relayed via LiveKit's own data channel (`RoomProvider.broadcast_data`), exactly as §4's "no separate WebSocket transport needed for Meet-internal events" describes.
- **In-meeting chat**: `meeting_messages` (broadcast when `recipient_participant_id` is null, private otherwise), also mirrored onto the LiveKit data channel for realtime delivery. TLS-only, not E2EE — see §7 above, same disclosed tradeoff as the AI transcript.
- **Polls**: `meeting_polls`/`meeting_poll_votes` — host/co-host creates, any participant votes (re-voting changes the existing vote, no double-counting), host closes, anyone can read live tallies.
- **Q&A**: `meeting_questions` — any participant asks, any participant upvotes, host/co-host answers or dismisses.
- **Breakout rooms**: `breakout_rooms`/`breakout_room_participants` — each breakout is a genuinely separate LiveKit room (`create_access_token` already takes an arbitrary `room_name`, so no new `RoomProvider` method was needed); host/co-host creates rooms and assigns participants, an assigned participant can mint a token to join their room, host closes all rooms at once. No automatic "move everyone back" beyond that — clients rejoin the main room the same way they joined it originally.

All of the above is exercised against real Postgres, with a `StubRoomProvider` subclassing the real `LiveKitRoomProvider` (keeping its real, network-free `create_access_token`) for the methods that make real HTTP calls to a LiveKit server — no LiveKit server exists in this dev environment (no Docker), so those specific calls are unverified against a live vendor, the same class of gap as `StitchPaymentProvider`. Not built this phase: `meeting_files`, `meeting_whiteboards`, `meeting_analytics`, `meeting_audit_log`, `meeting_invites` (§3's table list) — none of Phase 2's actual feature list (§9's own line above) needed them yet.

**Meet Phase 3:** the AI pipeline (§6) — LiveKit Agent + Deepgram + Claude, transcripts, notes, "what did I miss," search.

**Meet Phase 4:** webinars/conferences (large-audience modes, registration, stage/moderator roles).

**Meet Phase 5:** organizations/teams, billing, enterprise/SSO.

## 10. Environment variables (new)

| Variable | Used by |
|---|---|
| `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_URL` | Backend (token minting) + LiveKit Agent worker |
| `DEEPGRAM_API_KEY` | LiveKit Agent worker (Phase 3) |
| `ANTHROPIC_API_KEY` | `domain/meet_ai`'s Claude adapter (Phase 3) |
| `EXPO_PUBLIC_MEET_API_BASE_URL` (mobile), `NEXT_PUBLIC_MEET_API_BASE_URL` (web) | Client base URLs |

## 11. Cost considerations (spec §49)

**MVP**: LiveKit Cloud's free tier (generous per-minute allowance) covers early testing; Deepgram/Anthropic are both pay-per-use with no fixed cost until Phase 3 actually ships. No new servers to provision for Phase 1/2 beyond the existing Railway backend (new routes on the same service) and a new Vercel project (`apps/meet`) — both already-established, already-billed targets, not new infrastructure line items.

**Scale**: self-hosted LiveKit SFU (on the AWS infra `docs/CI_CD.md` already scaffolds) once usage outgrows LiveKit Cloud's pricing — same client code, no rewrite.

## 12. Testing strategy (spec §47)

Same real-backend-integration convention as the rest of this repo: `MeetingService` tested against real Postgres with a stub `TranscriptionProvider`/`MeetingIntelligenceProvider` and a stub LiveKit token-minting call (the real `livekit-server-sdk` call is a pure function — signs a JWT locally, no network call — so it can be exercised for real, unlike webhook-dependent vendors elsewhere in this repo). Load/scale testing (§47's "50/100 participants") is explicitly **not** attempted in this environment — no infrastructure exists to safely generate that load, and it belongs in a real LiveKit Cloud project's own load-testing tools, not a local dev machine.
