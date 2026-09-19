"use client";

import { useEffect, useRef, useState } from "react";

import {
  ApiError,
  type MeetingDocumentResponse,
  type RecordingResponse,
  meetingsApi,
  uploadFileToPresignedUrl,
} from "@/lib/api";

/**
 * Real in-call tools, rendered alongside LiveKit's stock <VideoConference />
 * rather than replacing it (docs/DITSALA_MEET_SPEC.md §9) — recording for
 * the host/co-host, and a documents panel every participant (including
 * guests with no DITSALA account) can see. `hostToken` is the short-lived
 * meet-host token from the `?hj=` handoff; it's the only bearer credential
 * this page ever has, since apps/meet has no session of its own — recording
 * controls simply don't render without it.
 */

interface MeetingToolsBarProps {
  meetingId: string;
  participantId: string;
  role: string;
  hostToken: string | null;
}

const HOST_ROLES = new Set(["host", "co_host"]);

export function MeetingToolsBar({ meetingId, participantId, role, hostToken }: MeetingToolsBarProps) {
  const isHost = HOST_ROLES.has(role) && hostToken !== null;
  const [panel, setPanel] = useState<"none" | "documents">("none");

  return (
    <div className="fixed right-3 top-3 z-50 flex flex-col items-end gap-2">
      <div className="flex gap-2">
        {isHost ? <RecordingControl meetingId={meetingId} hostToken={hostToken!} /> : null}
        <button
          type="button"
          onClick={() => setPanel(panel === "documents" ? "none" : "documents")}
          className="rounded bg-surface px-3 py-1.5 text-sm text-text-primary border border-border hover:bg-surface-raised"
        >
          Documents
        </button>
      </div>
      {panel === "documents" ? (
        <DocumentsPanel
          meetingId={meetingId}
          participantId={participantId}
          canUpload={isHost}
          hostToken={hostToken}
        />
      ) : null}
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
