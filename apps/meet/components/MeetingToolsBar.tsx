"use client";

import { useEffect, useRef, useState } from "react";

import { ParticipantsPanel } from "@/components/ParticipantsPanel";
import { PollsPanel } from "@/components/PollsPanel";
import { QuestionsPanel } from "@/components/QuestionsPanel";
import { ReactionsBar } from "@/components/ReactionsBar";
import {
  ApiError,
  type MeetingDocumentResponse,
  type MeetingResponse,
  type ParticipantResponse,
  type RecordingResponse,
  meetingsApi,
  uploadFileToPresignedUrl,
} from "@/lib/api";

/**
 * Real in-call tools, rendered alongside LiveKit's stock <VideoConference />
 * rather than replacing it (docs/DITSALA_MEET_SPEC.md §9) — recording,
 * lock, participants/polls/Q&A panels for the host/co-host, a documents
 * panel and reactions/raise-hand for every participant (guests included).
 * `hostToken` is the short-lived meet-host token from the `?hj=` handoff;
 * it's the only bearer credential this page ever has, since apps/meet has
 * no session of its own — every host-only control simply doesn't render
 * without it.
 */

interface MeetingToolsBarProps {
  meetingId: string;
  participantId: string;
  role: string;
  hostToken: string | null;
}

type Panel = "none" | "documents" | "waiting-room" | "participants" | "polls" | "questions";

const HOST_ROLES = new Set(["host", "co_host"]);

export function MeetingToolsBar({ meetingId, participantId, role, hostToken }: MeetingToolsBarProps) {
  const isHost = HOST_ROLES.has(role) && hostToken !== null;
  const [panel, setPanel] = useState<Panel>("none");

  function toggle(next: Panel) {
    setPanel((current) => (current === next ? "none" : next));
  }

  return (
    <>
      <div className="fixed right-3 top-3 z-50 flex flex-col items-end gap-2">
        {isHost ? (
          <div className="flex items-center gap-2">
            <LiveCountdown meetingId={meetingId} hostToken={hostToken!} />
            <WaitingRoomControl meetingId={meetingId} hostToken={hostToken!} />
            <LockControl meetingId={meetingId} hostToken={hostToken!} />
            <EndMeetingControl meetingId={meetingId} hostToken={hostToken!} />
          </div>
        ) : null}
        <div className="flex flex-wrap justify-end gap-2">
          {isHost ? <RecordingControl meetingId={meetingId} hostToken={hostToken!} /> : null}
          {isHost ? (
            <ToolButton active={panel === "waiting-room"} onClick={() => toggle("waiting-room")}>
              Waiting room
            </ToolButton>
          ) : null}
          {isHost ? (
            <ToolButton active={panel === "participants"} onClick={() => toggle("participants")}>
              Participants
            </ToolButton>
          ) : null}
          <ToolButton active={panel === "polls"} onClick={() => toggle("polls")}>
            Polls
          </ToolButton>
          <ToolButton active={panel === "questions"} onClick={() => toggle("questions")}>
            Q&amp;A
          </ToolButton>
          <ToolButton active={panel === "documents"} onClick={() => toggle("documents")}>
            Documents
          </ToolButton>
        </div>
        {panel === "documents" ? (
          <DocumentsPanel
            meetingId={meetingId}
            participantId={participantId}
            canUpload={isHost}
            hostToken={hostToken}
          />
        ) : null}
        {panel === "waiting-room" && isHost ? (
          <WaitingRoomPanel meetingId={meetingId} hostToken={hostToken!} />
        ) : null}
        {panel === "participants" && isHost ? (
          <ParticipantsPanel
            meetingId={meetingId}
            hostToken={hostToken!}
            selfParticipantId={participantId}
          />
        ) : null}
        {panel === "polls" ? (
          <PollsPanel
            meetingId={meetingId}
            participantId={participantId}
            isHost={isHost}
            hostToken={hostToken}
          />
        ) : null}
        {panel === "questions" ? (
          <QuestionsPanel
            meetingId={meetingId}
            participantId={participantId}
            isHost={isHost}
            hostToken={hostToken}
          />
        ) : null}
      </div>
      <ReactionsBar meetingId={meetingId} participantId={participantId} />
    </>
  );
}

function ToolButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded px-3 py-1.5 text-sm border ${
        active
          ? "bg-accent-muted text-accent border-accent"
          : "bg-surface text-text-primary border-border hover:bg-surface-raised"
      }`}
    >
      {children}
    </button>
  );
}

function LockControl({ meetingId, hostToken }: { meetingId: string; hostToken: string }) {
  const [locked, setLocked] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  async function toggle() {
    setBusy(true);
    try {
      const meeting: MeetingResponse = await meetingsApi.lockMeeting(
        meetingId,
        !(locked ?? false),
        hostToken
      );
      setLocked(meeting.locked_at !== null);
    } catch {
      // Leaves the existing state showing — the host can just retry.
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={busy}
      title={locked ? "Unlock meeting" : "Lock meeting"}
      className={`rounded px-3 py-1.5 text-sm border disabled:opacity-50 ${
        locked
          ? "bg-warning/10 text-warning border-warning"
          : "bg-surface text-text-primary border-border hover:bg-surface-raised"
      }`}
    >
      {locked ? "🔒 Locked" : "🔓 Lock"}
    </button>
  );
}

function WaitingRoomControl({ meetingId, hostToken }: { meetingId: string; hostToken: string }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  async function toggle() {
    setBusy(true);
    try {
      const meeting: MeetingResponse = await meetingsApi.setWaitingRoom(
        meetingId,
        !(enabled ?? false),
        hostToken
      );
      setEnabled(meeting.waiting_room_enabled);
    } catch {
      // Leaves the existing state showing — the host can just retry.
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={busy}
      title={
        enabled
          ? "Guests wait to be admitted — click to let them straight in instead"
          : "Guests join straight into the room — click to hold them until admitted instead"
      }
      className={`rounded px-3 py-1.5 text-sm border disabled:opacity-50 ${
        enabled
          ? "bg-accent-muted text-accent border-accent"
          : "bg-surface text-text-primary border-border hover:bg-surface-raised"
      }`}
    >
      {enabled ? "🖐 Hold guests" : "🚪 Let guests in"}
    </button>
  );
}

function EndMeetingControl({ meetingId, hostToken }: { meetingId: string; hostToken: string }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  async function end() {
    setBusy(true);
    try {
      await meetingsApi.endMeeting(meetingId, hostToken);
      window.location.reload();
    } catch {
      setBusy(false);
      setConfirming(false);
    }
  }

  if (confirming) {
    return (
      <div className="flex items-center gap-1 rounded border border-danger bg-danger/10 px-2 py-1">
        <span className="text-xs text-danger">End for everyone?</span>
        <button
          type="button"
          onClick={end}
          disabled={busy}
          className="rounded bg-danger px-2 py-1 text-xs font-medium text-white disabled:opacity-50"
        >
          {busy ? "…" : "Yes"}
        </button>
        <button
          type="button"
          onClick={() => setConfirming(false)}
          className="rounded px-2 py-1 text-xs text-text-secondary hover:bg-surface-raised"
        >
          No
        </button>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setConfirming(true)}
      className="rounded bg-danger px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
    >
      End meeting
    </button>
  );
}

const WAITING_ROOM_POLL_MS = 5000;

function WaitingRoomPanel({ meetingId, hostToken }: { meetingId: string; hostToken: string }) {
  const [waiting, setWaiting] = useState<ParticipantResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function refresh() {
    try {
      setWaiting(await meetingsApi.listWaitingRoom(meetingId, hostToken));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the waiting room.");
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, WAITING_ROOM_POLL_MS);
    return () => clearInterval(id);
  }, [meetingId, hostToken]);

  async function admit(participantId: string) {
    setBusyId(participantId);
    try {
      await meetingsApi.admitParticipant(meetingId, participantId, hostToken);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not admit this participant.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="w-72 rounded border border-border bg-surface p-3 text-sm">
      <p className="mb-2 text-xs font-medium uppercase tracking-widest text-text-tertiary">
        Waiting room
      </p>
      {waiting.length === 0 ? (
        <p className="text-text-tertiary">Nobody is waiting right now.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {waiting.map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-2">
              <span className="truncate text-text-primary">
                {p.guest_display_name || "A participant"}
              </span>
              <button
                type="button"
                onClick={() => admit(p.id)}
                disabled={busyId === p.id}
                className="shrink-0 rounded bg-accent px-2 py-1 text-xs text-background hover:bg-accent-pressed disabled:opacity-50"
              >
                {busyId === p.id ? "Admitting…" : "Bring online"}
              </button>
            </li>
          ))}
        </ul>
      )}
      {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}
    </div>
  );
}

const COUNTDOWN_POLL_MS = 30000;

function formatRemaining(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function LiveCountdown({ meetingId, hostToken }: { meetingId: string; hostToken: string }) {
  const [deadline, setDeadline] = useState<Date | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [extending, setExtending] = useState(false);

  useEffect(() => {
    async function refreshDeadline() {
      try {
        const info = await meetingsApi.joinInfo(meetingId);
        setDeadline(info.live_deadline_at ? new Date(info.live_deadline_at) : null);
      } catch {
        // A poll failing shouldn't make an existing countdown disappear.
      }
    }
    refreshDeadline();
    const id = setInterval(refreshDeadline, COUNTDOWN_POLL_MS);
    return () => clearInterval(id);
  }, [meetingId]);

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  async function extend() {
    setExtending(true);
    try {
      await meetingsApi.extendMeeting(meetingId, 15, hostToken);
      const info = await meetingsApi.joinInfo(meetingId);
      setDeadline(info.live_deadline_at ? new Date(info.live_deadline_at) : null);
    } catch {
      // Leaves the existing countdown showing — the host can just retry.
    } finally {
      setExtending(false);
    }
  }

  if (!deadline) return null;
  const remainingMs = deadline.getTime() - now.getTime();
  const isUp = remainingMs <= 0;

  return (
    <div
      className={`flex items-center gap-2 rounded px-3 py-1.5 text-sm border ${
        isUp
          ? "bg-danger/10 text-danger border-danger"
          : "bg-surface text-text-primary border-border"
      }`}
    >
      <span>{isUp ? "Time's up" : formatRemaining(remainingMs)}</span>
      <button
        type="button"
        onClick={extend}
        disabled={extending}
        className="rounded bg-surface-raised px-2 py-1 text-xs text-text-primary border border-border hover:bg-surface disabled:opacity-50"
      >
        {extending ? "…" : "+15 min"}
      </button>
    </div>
  );
}

function RecordingControl({ meetingId, hostToken }: { meetingId: string; hostToken: string }) {
  const [recording, setRecording] = useState<RecordingResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    meetingsApi
      .listRecordings(meetingId, hostToken)
      .then((recordings) => {
        const active = recordings.find((r) => r.status === "processing");
        if (active) setRecording(active);
      })
      .catch(() => undefined);
  }, [meetingId, hostToken]);

  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      if (recording) {
        const stopped = await meetingsApi.stopRecording(meetingId, recording.id, hostToken);
        setRecording(stopped.status === "processing" ? stopped : null);
      } else {
        setRecording(await meetingsApi.startRecording(meetingId, hostToken));
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update recording.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={toggle}
        disabled={busy}
        className={`rounded px-3 py-1.5 text-sm font-medium border disabled:opacity-50 ${
          recording
            ? "bg-danger text-white border-danger"
            : "bg-surface text-text-primary border-border hover:bg-surface-raised"
        }`}
      >
        {recording ? "● Recording — stop" : "Record"}
      </button>
      {error ? <p className="text-xs text-danger">{error}</p> : null}
    </div>
  );
}

function DocumentsPanel({
  meetingId,
  participantId,
  canUpload,
  hostToken,
}: {
  meetingId: string;
  participantId: string;
  canUpload: boolean;
  hostToken: string | null;
}) {
  const [documents, setDocuments] = useState<MeetingDocumentResponse[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function refresh() {
    try {
      setDocuments(await meetingsApi.listDocuments(meetingId, participantId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load documents.");
    }
  }

  useEffect(() => {
    refresh();
  }, [meetingId, participantId]);

  async function handleDownload(documentId: string) {
    try {
      const { download_url: downloadUrl } = await meetingsApi.documentDownloadUrl(
        meetingId,
        documentId,
        participantId
      );
      window.open(downloadUrl, "_blank", "noopener,noreferrer");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not open this document.");
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !hostToken) return;
    setUploading(true);
    setError(null);
    try {
      const { upload_url: uploadUrl } = await meetingsApi.requestDocumentUpload(
        meetingId,
        hostToken,
        { filename: file.name, content_type: file.type || "application/octet-stream", size_bytes: file.size }
      );
      await uploadFileToPresignedUrl(uploadUrl, file);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not upload this file.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="w-72 rounded border border-border bg-surface p-3 text-sm">
      <p className="mb-2 text-xs font-medium uppercase tracking-widest text-text-tertiary">
        Documents
      </p>
      {documents.length === 0 ? (
        <p className="text-text-tertiary">No documents shared yet.</p>
      ) : (
        <ul className="mb-2 flex flex-col gap-1">
          {documents.map((doc) => (
            <li key={doc.id}>
              <button
                type="button"
                onClick={() => handleDownload(doc.id)}
                className="w-full truncate rounded px-2 py-1 text-left text-accent hover:bg-surface-raised"
                title={doc.filename}
              >
                {doc.filename}
              </button>
            </li>
          ))}
        </ul>
      )}
      {canUpload ? (
        <>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="w-full rounded bg-accent px-3 py-1.5 text-background hover:bg-accent-pressed disabled:opacity-50"
          >
            {uploading ? "Uploading…" : "Share a file"}
          </button>
          <input ref={fileInputRef} type="file" hidden onChange={handleUpload} />
        </>
      ) : null}
      {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}
    </div>
  );
}
