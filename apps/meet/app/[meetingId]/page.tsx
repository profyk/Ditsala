"use client";

import { LiveKitRoom, VideoConference } from "@livekit/components-react";
import { AudioPresets, VideoPresets } from "livekit-client";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { MeetingToolsBar } from "@/components/MeetingToolsBar";
import {
  type JoinInfoResponse,
  type JoinMeetingResponse,
  ApiError,
  meetingsApi,
} from "@/lib/api";

/**
 * Join flow (docs/DITSALA_MEET_SPEC.md §9 Phases 1, 2 & 4) — guest join
 * only for now; a DITSALA-account host flow (reusing the same login this
 * app's sibling apps already have) is a separate increment. This page
 * now also gates entry on the meeting's own join-info (§9 Phase 4): a
 * shared link's recipient sees the scheduled time before it's time to
 * join, and a password prompt only when the meeting actually has one —
 * both checked via the public, unauthenticated `/join-info` endpoint
 * before any join attempt is made.
 */

const POLL_INTERVAL_MS = 4000;
const RECHECK_INTERVAL_MS = 30000;

// The real ceiling for *live* video/audio (explicit user ask for "4K
// HDR" — neither is achievable for real-time calling: most cameras
// can't capture it, a 4K upload needs ~15-25Mbps this product's actual
// target networks don't have, and LiveKit has no HDR capture/encode
// path at all — see the matching note on start_recording for the
// recording side of this same ask). h1080 is the practical maximum
// every mainstream video-calling product converges on for exactly
// those reasons. A 3-rung simulcast ladder still lets LiveKit drop a
// weak connection down to h360/h540 automatically — this raises the
// ceiling for good connections without forcing bad ones to fail.
// musicHighQualityStereo (128kbps) is the actual highest-quality audio
// preset this SDK offers.
const ROOM_OPTIONS = {
  adaptiveStream: true,
  dynacast: true,
  videoCaptureDefaults: { resolution: VideoPresets.h1080.resolution },
  audioCaptureDefaults: {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
  publishDefaults: {
    videoSimulcastLayers: [VideoPresets.h360, VideoPresets.h540, VideoPresets.h1080],
    audioPreset: AudioPresets.musicHighQualityStereo,
    dtx: false,
    red: true,
  },
};

type Stage = "loading" | "not-yet" | "form" | "waiting" | "in-call" | "error";

function formatScheduledTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatCountdown(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
  }
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

/**
 * Live countdown to `scheduledStartAt` — shown both before the room's
 * own early-join window opens ("not-yet") and while sitting in the
 * waiting room, since the backend's `auto_promote_waiting_conference_
 * participants` scheduler job (polls every 60s) admits every `waiting`
 * participant the moment this hits zero with no host action required.
 */
function StartCountdown({ scheduledStartAt }: { scheduledStartAt: string }) {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const remainingMs = new Date(scheduledStartAt).getTime() - now.getTime();
  const isDue = remainingMs <= 0;

  return (
    <p
      className={`rounded border px-4 py-3 text-center text-2xl font-semibold tabular-nums ${
        isDue ? "border-accent bg-accent/10 text-accent" : "border-border bg-surface text-text-primary"
      }`}
    >
      {isDue ? "Starting…" : formatCountdown(remainingMs)}
    </p>
  );
}

export default function MeetingRoom() {
  const params = useParams<{ meetingId: string }>();
  const meetingId = params.meetingId;
  const searchParams = useSearchParams();
  // §9 host-link handoff (docs/DITSALA_MEET_SPEC.md) — set by the mobile
  // app's "My Meetings" list, see backend/app/core/security.py's
  // create_meet_host_token. Present only when a host opened this link.
  const urlHostToken = searchParams.get("hj");
  // The Host PIN path (handleHostPinJoin below) has no `?hj=` URL token
  // to fall back on — its own join response carries a freshly-minted one
  // instead. Without this, MeetingToolsBar's `hostToken !== null` check
  // would silently hide every host control (end meeting, lock, record,
  // ...) for anyone who joined via PIN rather than the mobile handoff.
  const [pinHostToken, setPinHostToken] = useState<string | null>(null);
  const hostToken = urlHostToken ?? pinHostToken;

  const [stage, setStage] = useState<Stage>("loading");
  const [joinInfo, setJoinInfo] = useState<JoinInfoResponse | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  // Same-tab alternative to the mobile app's host-link handoff — see
  // meetingsApi.hostPinJoin's docstring.
  const [hostPinMode, setHostPinMode] = useState(false);
  const [hostPin, setHostPin] = useState("");
  const [hostPinSubmitting, setHostPinSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [join, setJoin] = useState<JoinMeetingResponse | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function loadJoinInfo() {
    try {
      const info = await meetingsApi.joinInfo(meetingId);
      setJoinInfo(info);
      setStage(info.joinable_now ? "form" : "not-yet");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "This meeting link isn't valid.");
      setStage("error");
    }
  }

  useEffect(() => {
    if (urlHostToken) {
      // The host bypasses join-info entirely — they always can join their
      // own meeting (server-enforced in _check_joinable's is_host bypass).
      // Keyed on urlHostToken specifically (not the merged hostToken) so
      // a later PIN join setting pinHostToken doesn't re-trigger this.
      meetingsApi
        .hostJoin(meetingId, urlHostToken)
        .then((result) => {
          setJoin(result);
          setStage(result.access ? "in-call" : "waiting");
        })
        .catch((err) => {
          setError(err instanceof ApiError ? err.message : "This meeting link isn't valid.");
          setStage("error");
        });
      return;
    }
    loadJoinInfo();
  }, [meetingId, urlHostToken]);

  // While "not-yet" (too early relative to the scheduled start), quietly
  // recheck every so often — the moment the host's early-join window
  // opens, the recipient shouldn't have to manually refresh.
  useEffect(() => {
    if (stage !== "not-yet") return;
    const id = setInterval(loadJoinInfo, RECHECK_INTERVAL_MS);
    return () => clearInterval(id);
  }, [stage]);

  // While waiting for the host to admit us, poll our own participant
  // status (a stable id, unlike re-calling guest-join, which would mint
  // a brand-new waiting participant on every attempt).
  useEffect(() => {
    if (stage !== "waiting" || !join) return;
    pollRef.current = setInterval(async () => {
      try {
        const result = await meetingsApi.participantStatus(meetingId, join.participant_id);
        if (result.access) {
          setJoin(result);
          setStage("in-call");
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch {
        // A transient network hiccup shouldn't kick the user out of the
        // waiting screen — just try again on the next tick.
      }
    }, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [stage, join, meetingId]);

  async function handleJoin(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await meetingsApi.guestJoin(
        meetingId,
        displayName.trim(),
        password || undefined,
        email.trim() || undefined
      );
      setJoin(result);
      setStage(result.access ? "in-call" : "waiting");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not join this meeting.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleHostPinJoin(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setHostPinSubmitting(true);
    try {
      const result = await meetingsApi.hostPinJoin(meetingId, hostPin.trim());
      setJoin(result);
      setPinHostToken(result.host_token);
      setStage(result.access ? "in-call" : "waiting");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That PIN isn't correct.");
    } finally {
      setHostPinSubmitting(false);
    }
  }

  if (stage === "loading") {
    return (
      <Centered>
        <p className="text-text-secondary">Loading meeting…</p>
      </Centered>
    );
  }

  if (stage === "error") {
    return (
      <Centered>
        <h1 className="font-display text-2xl text-text-primary">Can&apos;t open this link</h1>
        <p className="text-text-secondary">{error}</p>
      </Centered>
    );
  }

  if (stage === "not-yet" && joinInfo) {
    return (
      <Centered>
        <h1 className="font-display text-2xl text-text-primary">{joinInfo.title}</h1>
        <p className="text-text-secondary">This meeting hasn&apos;t started yet.</p>
        {joinInfo.scheduled_start_at ? (
          <>
            <p className="text-sm text-text-secondary">
              Scheduled for {formatScheduledTime(joinInfo.scheduled_start_at)}
            </p>
            <StartCountdown scheduledStartAt={joinInfo.scheduled_start_at} />
          </>
        ) : null}
        <p className="text-sm text-text-tertiary">
          Come back closer to the start time — this page checks automatically.
        </p>
      </Centered>
    );
  }

  if (stage === "waiting") {
    return (
      <Centered>
        <h1 className="font-display text-2xl text-text-primary">You&apos;re in the waiting room</h1>
        {join?.meeting.scheduled_start_at ? (
          <>
            <p className="text-text-secondary">
              You&apos;ll be let in automatically at the scheduled time, or sooner if the host
              admits you.
            </p>
            <StartCountdown scheduledStartAt={join.meeting.scheduled_start_at} />
          </>
        ) : (
          <p className="text-text-secondary">The host will let you in shortly.</p>
        )}
      </Centered>
    );
  }

  if (stage === "in-call" && join?.access) {
    return (
      <LiveKitRoom
        serverUrl={join.access.livekit_url}
        token={join.access.token}
        connect
        options={ROOM_OPTIONS}
        data-lk-theme="default"
        style={{ height: "100vh" }}
        onDisconnected={() => {
          // Best-effort — records that this seat is free again (see
          // MeetingService.mark_participant_left's docstring). A guest
          // has no JWT, so this participant_id-based call is the only
          // way their left_at ever gets set; without it they'd
          // permanently occupy a guest-cap seat even after leaving.
          meetingsApi.leaveAsParticipant(meetingId, join.participant_id).catch(() => undefined);
          setStage("form");
        }}
      >
        <MeetingToolsBar
          meetingId={meetingId}
          participantId={join.participant_id}
          role={join.role}
          hostToken={hostToken}
        />
        <VideoConference />
      </LiveKitRoom>
    );
  }

  if (hostPinMode) {
    return (
      <Centered>
        <h1 className="font-display text-3xl text-text-primary">
          {joinInfo?.title ?? "Join meeting"}
        </h1>
        <p className="max-w-sm text-center text-sm text-text-secondary">
          Enter the meeting's Host PIN — shown once when the meeting was scheduled, and shared
          separately from the meeting link/password. It signs you in with full host controls, no
          name or password needed.
        </p>
        <form className="flex w-full max-w-sm flex-col gap-3" onSubmit={handleHostPinJoin}>
          <input
            value={hostPin}
            onChange={(e) => setHostPin(e.target.value)}
            placeholder="Host PIN"
            inputMode="numeric"
            autoFocus
            required
            className="rounded border border-border bg-surface px-4 py-2 text-center text-2xl tracking-widest text-text-primary outline-none focus:border-accent"
          />
          {error ? <p className="text-sm text-danger">{error}</p> : null}
          <button
            type="submit"
            disabled={hostPinSubmitting || hostPin.trim().length === 0}
            className="rounded bg-accent px-4 py-2 font-medium text-background hover:bg-accent-pressed disabled:opacity-50"
          >
            {hostPinSubmitting ? "Checking…" : "Enter as host"}
          </button>
          <button
            type="button"
            onClick={() => {
              setHostPinMode(false);
              setError(null);
            }}
            className="text-sm text-text-tertiary hover:text-text-secondary"
          >
            ← Back to joining as a guest
          </button>
        </form>
      </Centered>
    );
  }

  return (
    <Centered>
      <h1 className="font-display text-3xl text-text-primary">
        {joinInfo?.title ?? "Join meeting"}
      </h1>
      <form className="flex w-full max-w-sm flex-col gap-3" onSubmit={handleJoin}>
        <input
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="Your name"
          required
          className="rounded border border-border bg-surface px-4 py-2 text-text-primary outline-none focus:border-accent"
        />
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email (optional)"
          type="email"
          className="rounded border border-border bg-surface px-4 py-2 text-text-primary outline-none focus:border-accent"
        />
        {joinInfo?.requires_password ? (
          <div className="relative">
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Meeting password"
              type={passwordVisible ? "text" : "password"}
              required
              className="w-full rounded border border-border bg-surface px-4 py-2 pr-16 text-text-primary outline-none focus:border-accent"
            />
            <button
              type="button"
              onClick={() => setPasswordVisible((v) => !v)}
              className="absolute bottom-0 right-0 top-0 px-3 text-xs font-medium text-accent"
            >
              {passwordVisible ? "Hide" : "Show"}
            </button>
          </div>
        ) : null}
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        <button
          type="submit"
          disabled={submitting || displayName.trim().length === 0}
          className="rounded bg-accent px-4 py-2 font-medium text-background hover:bg-accent-pressed disabled:opacity-50"
        >
          {submitting ? "Joining…" : "Join now"}
        </button>
        <button
          type="button"
          onClick={() => {
            setHostPinMode(true);
            setError(null);
          }}
          className="text-sm text-accent hover:underline"
        >
          Host or co-host? Enter with your PIN instead →
        </button>
      </form>
    </Centered>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-4 text-center">
      {children}
    </main>
  );
}
