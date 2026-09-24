import { useFocusEffect, useRouter } from "expo-router";
import { File, Paths } from "expo-file-system";
import * as Sharing from "expo-sharing";
import { useVideoPlayer, VideoView } from "expo-video";
import { useCallback, useState } from "react";
import { ActivityIndicator, Linking, Modal, Platform, Pressable, Text, View } from "react-native";

import { Icon } from "../../components/Icon";
import { Screen } from "../../components/Screen";
import { ApiError } from "../../lib/api";
import {
  type MyMeetingDocumentResponse,
  type MyRecordingResponse,
  meetingsApi,
} from "../../lib/meetings-api";
import { getAccessToken } from "../../lib/session";
import { useTheme, useThemeVars } from "../../lib/theme-context";

/**
 * "My Recordings" — every recording and document across every meeting
 * this account hosts, not scoped to one meeting (GET /meetings/recordings
 * /mine and /meetings/documents/mine). Reached from the Conference Room
 * hub alongside "My meetings".
 */

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

type Kind = "recording" | "document";

export default function MyRecordings() {
  const router = useRouter();
  const { colors } = useTheme();
  const [recordings, setRecordings] = useState<MyRecordingResponse[] | null>(null);
  const [documents, setDocuments] = useState<MyMeetingDocumentResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [playingUrl, setPlayingUrl] = useState<string | null>(null);

  const load = useCallback(async () => {
    const accessToken = await getAccessToken();
    if (!accessToken) {
      router.replace("/");
      return;
    }
    try {
      const [rec, docs] = await Promise.all([
        meetingsApi.myRecordings(accessToken),
        meetingsApi.myDocuments(accessToken),
      ]);
      setRecordings(rec);
      setDocuments(docs);
    } catch {
      setError("Could not load your recordings.");
    }
  }, [router]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  async function handlePlay(recording: MyRecordingResponse) {
    setError(null);
    setBusyId(recording.id);
    try {
      const accessToken = await getAccessToken();
      if (!accessToken) {
        router.replace("/");
        return;
      }
      const { download_url } = await meetingsApi.recordingDownloadUrl(
        accessToken,
        recording.meeting_id,
        recording.id
      );
      setPlayingUrl(download_url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not open this recording.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleOpenDocument(document: MyMeetingDocumentResponse) {
    setError(null);
    setBusyId(document.id);
    try {
      const accessToken = await getAccessToken();
      if (!accessToken) {
        router.replace("/");
        return;
      }
      const { download_url } = await meetingsApi.documentDownloadUrl(
        accessToken,
        document.meeting_id,
        document.id
      );
      await Linking.openURL(download_url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not open this document.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDownload(
    kind: Kind,
    item: MyRecordingResponse | MyMeetingDocumentResponse,
    filename: string
  ) {
    setError(null);
    setBusyId(item.id);
    try {
      const accessToken = await getAccessToken();
      if (!accessToken) {
        router.replace("/");
        return;
      }
      const { download_url } =
        kind === "recording"
          ? await meetingsApi.recordingDownloadUrl(accessToken, item.meeting_id, item.id)
          : await meetingsApi.documentDownloadUrl(accessToken, item.meeting_id, item.id);
      if (Platform.OS === "web") {
        // A direct presigned link — the browser's own download/save
        // handling takes it from here, same as apps/meet's document panel.
        await Linking.openURL(download_url);
        return;
      }
      // Native: fetch it locally, then hand it to the OS share sheet so
      // the user can save it to Files/Photos — the standard Expo pattern
      // that avoids needing expo-media-library's extra permissions.
      const file = await File.downloadFileAsync(download_url, new File(Paths.cache, filename), {
        idempotent: true,
      });
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(file.uri);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not download this file.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(kind: Kind, item: MyRecordingResponse | MyMeetingDocumentResponse) {
    setError(null);
    setBusyId(item.id);
    try {
      const accessToken = await getAccessToken();
      if (!accessToken) {
        router.replace("/");
        return;
      }
      if (kind === "recording") {
        await meetingsApi.deleteRecording(accessToken, item.meeting_id, item.id);
        setRecordings((current) => current?.filter((r) => r.id !== item.id) ?? current);
      } else {
        await meetingsApi.deleteDocument(accessToken, item.meeting_id, item.id);
        setDocuments((current) => current?.filter((d) => d.id !== item.id) ?? current);
      }
      setConfirmingId(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete this file.");
    } finally {
      setBusyId(null);
    }
  }

  const loading = recordings === null || documents === null;

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">My Recordings</Text>
      <Text className="mb-8 text-base leading-6 text-text-secondary">
        Every recording and document across every meeting you host.
      </Text>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      {loading ? (
        <ActivityIndicator color={colors.accent} />
      ) : (
        <>
          <Text className="mb-2 text-xs font-medium uppercase tracking-widest text-text-tertiary">
            Recordings
          </Text>
          {recordings.length === 0 ? (
            <View className="mb-6 items-center rounded-xl border border-border bg-surface p-6">
              <Text className="text-center text-text-secondary">No recordings yet.</Text>
            </View>
          ) : (
            <View className="mb-6">
              {recordings.map((r) => (
                <RecordingCard
                  key={r.id}
                  recording={r}
                  busy={busyId === r.id}
                  confirming={confirmingId === r.id}
                  onPlay={() => handlePlay(r)}
                  onDownload={() => handleDownload("recording", r, `${r.meeting_title}.mp4`)}
                  onConfirmDelete={() => setConfirmingId(r.id)}
                  onCancelDelete={() => setConfirmingId(null)}
                  onDelete={() => handleDelete("recording", r)}
                />
              ))}
            </View>
          )}

          <Text className="mb-2 text-xs font-medium uppercase tracking-widest text-text-tertiary">
            Documents
          </Text>
          {documents.length === 0 ? (
            <View className="items-center rounded-xl border border-border bg-surface p-6">
              <Text className="text-center text-text-secondary">No documents yet.</Text>
            </View>
          ) : (
            <View>
              {documents.map((d) => (
                <DocumentCard
                  key={d.id}
                  document={d}
                  busy={busyId === d.id}
                  confirming={confirmingId === d.id}
                  onOpen={() => handleOpenDocument(d)}
                  onDownload={() => handleDownload("document", d, d.filename)}
                  onConfirmDelete={() => setConfirmingId(d.id)}
                  onCancelDelete={() => setConfirmingId(null)}
                  onDelete={() => handleDelete("document", d)}
                />
              ))}
            </View>
          )}
        </>
      )}

      {playingUrl ? (
        <RecordingPlayerModal url={playingUrl} onClose={() => setPlayingUrl(null)} />
      ) : null}
    </Screen>
  );
}

function RecordingCard({
  recording,
  busy,
  confirming,
  onPlay,
  onDownload,
  onConfirmDelete,
  onCancelDelete,
  onDelete,
}: {
  recording: MyRecordingResponse;
  busy: boolean;
  confirming: boolean;
  onPlay: () => void;
  onDownload: () => void;
  onConfirmDelete: () => void;
  onCancelDelete: () => void;
  onDelete: () => void;
}) {
  const { colors } = useTheme();
  const isReady = recording.status === "ready";

  return (
    <View className="mb-2 overflow-hidden rounded-xl border border-border bg-surface">
      <View className="flex-row items-center gap-3 p-4">
        <View
          className="h-9 w-9 items-center justify-center rounded-full"
          style={{ backgroundColor: colors.accentMuted }}
        >
          <Icon name="video" size={18} color={colors.accent} />
        </View>
        <View className="flex-1">
          <Text className="text-base font-medium text-text-primary" numberOfLines={1}>
            {recording.meeting_title}
          </Text>
          <Text className="mt-0.5 text-xs text-text-tertiary">
            {formatDate(recording.started_at)}
            {recording.duration_seconds !== null
              ? ` · ${formatDuration(recording.duration_seconds)}`
              : ""}
            {!isReady ? ` · ${recording.status === "processing" ? "Processing…" : "Failed"}` : ""}
          </Text>
        </View>
      </View>

      <View className="flex-row gap-2 border-t border-border px-4 py-2">
        <Pressable
          testID={`recording-play-${recording.id}`}
          onPress={onPlay}
          disabled={!isReady || busy}
          className="flex-1 flex-row items-center justify-center gap-1.5 rounded-lg py-2 active:bg-surface-raised disabled:opacity-40"
        >
          <Icon name="play" size={12} color={colors.accent} />
          <Text className="text-xs font-medium text-accent">Play</Text>
        </Pressable>
        <Pressable
          testID={`recording-download-${recording.id}`}
          onPress={onDownload}
          disabled={!isReady || busy}
          className="flex-1 flex-row items-center justify-center gap-1.5 rounded-lg py-2 active:bg-surface-raised disabled:opacity-40"
        >
          <Icon name="download" size={12} color={colors.textSecondary} />
          <Text className="text-xs font-medium text-text-secondary">Download</Text>
        </Pressable>
        <Pressable
          testID={`recording-delete-${recording.id}`}
          onPress={onConfirmDelete}
          disabled={busy}
          className="flex-1 flex-row items-center justify-center gap-1.5 rounded-lg py-2 active:bg-surface-raised disabled:opacity-40"
        >
          <Icon name="trash" size={12} color={colors.danger} />
          <Text className="text-xs font-medium text-danger">Delete</Text>
        </Pressable>
      </View>

      {confirming ? (
        <View className="gap-2 border-t border-border p-4">
          <Text className="text-xs text-text-secondary">
            Delete this recording? This can&apos;t be undone.
          </Text>
          <View className="flex-row gap-2">
            <Pressable
              onPress={onCancelDelete}
              className="flex-1 items-center rounded-lg border border-border py-2"
            >
              <Text className="text-sm text-text-secondary">Cancel</Text>
            </Pressable>
            <Pressable
              testID={`recording-delete-confirm-${recording.id}`}
              onPress={onDelete}
              disabled={busy}
              className="flex-1 items-center rounded-lg bg-danger py-2 disabled:opacity-50"
            >
              <Text className="text-sm font-medium text-white">
                {busy ? "Deleting…" : "Yes, delete"}
              </Text>
            </Pressable>
          </View>
        </View>
      ) : null}
    </View>
  );
}

function DocumentCard({
  document,
  busy,
  confirming,
  onOpen,
  onDownload,
  onConfirmDelete,
  onCancelDelete,
  onDelete,
}: {
  document: MyMeetingDocumentResponse;
  busy: boolean;
  confirming: boolean;
  onOpen: () => void;
  onDownload: () => void;
  onConfirmDelete: () => void;
  onCancelDelete: () => void;
  onDelete: () => void;
}) {
  const { colors } = useTheme();

  return (
    <View className="mb-2 overflow-hidden rounded-xl border border-border bg-surface">
      <View className="flex-row items-center gap-3 p-4">
        <View
          className="h-9 w-9 items-center justify-center rounded-full"
          style={{ backgroundColor: colors.accentMuted }}
        >
          <Icon name="file" size={18} color={colors.accent} />
        </View>
        <View className="flex-1">
          <Text className="text-base font-medium text-text-primary" numberOfLines={1}>
            {document.filename}
          </Text>
          <Text className="mt-0.5 text-xs text-text-tertiary" numberOfLines={1}>
            {document.meeting_title} · {formatDate(document.created_at)} ·{" "}
            {formatSize(document.size_bytes)}
          </Text>
        </View>
      </View>

      <View className="flex-row gap-2 border-t border-border px-4 py-2">
        <Pressable
          testID={`document-open-${document.id}`}
          onPress={onOpen}
          disabled={busy}
          className="flex-1 items-center rounded-lg py-2 active:bg-surface-raised disabled:opacity-40"
        >
          <Text className="text-xs font-medium text-accent">Open</Text>
        </Pressable>
        <Pressable
          testID={`document-download-${document.id}`}
          onPress={onDownload}
          disabled={busy}
          className="flex-1 flex-row items-center justify-center gap-1.5 rounded-lg py-2 active:bg-surface-raised disabled:opacity-40"
        >
          <Icon name="download" size={12} color={colors.textSecondary} />
          <Text className="text-xs font-medium text-text-secondary">Download</Text>
        </Pressable>
        <Pressable
          testID={`document-delete-${document.id}`}
          onPress={onConfirmDelete}
          disabled={busy}
          className="flex-1 flex-row items-center justify-center gap-1.5 rounded-lg py-2 active:bg-surface-raised disabled:opacity-40"
        >
          <Icon name="trash" size={12} color={colors.danger} />
          <Text className="text-xs font-medium text-danger">Delete</Text>
        </Pressable>
      </View>

      {confirming ? (
        <View className="gap-2 border-t border-border p-4">
          <Text className="text-xs text-text-secondary">
            Delete this document? This can&apos;t be undone.
          </Text>
          <View className="flex-row gap-2">
            <Pressable
              onPress={onCancelDelete}
              className="flex-1 items-center rounded-lg border border-border py-2"
            >
              <Text className="text-sm text-text-secondary">Cancel</Text>
            </Pressable>
            <Pressable
              testID={`document-delete-confirm-${document.id}`}
              onPress={onDelete}
              disabled={busy}
              className="flex-1 items-center rounded-lg bg-danger py-2 disabled:opacity-50"
            >
              <Text className="text-sm font-medium text-white">
                {busy ? "Deleting…" : "Yes, delete"}
              </Text>
            </Pressable>
          </View>
        </View>
      ) : null}
    </View>
  );
}

/**
 * Full-screen HD playback via expo-video — a real <VideoView> (native
 * controls, fullscreen toggle, HTML5 <video> on web), not a custom
 * player. Rendered in a Modal whose own outer View re-applies the theme
 * vars (see lib/theme-context.tsx's useThemeVars docstring) — React
 * Native's Modal portals its children outside the themed root, the same
 * bug ScheduleDateTimePicker/CountryCodePicker already hit and fixed.
 */
function RecordingPlayerModal({ url, onClose }: { url: string; onClose: () => void }) {
  const themeVars = useThemeVars();
  const player = useVideoPlayer(url, (p) => {
    p.play();
  });

  return (
    <Modal
      visible
      animationType="fade"
      presentationStyle="fullScreen"
      onRequestClose={onClose}
    >
      <View style={[{ flex: 1, backgroundColor: "#000000" }, themeVars]}>
        <VideoView style={{ flex: 1 }} player={player} nativeControls contentFit="contain" />
        <Pressable
          testID="recording-player-close"
          onPress={onClose}
          style={{
            position: "absolute",
            top: 48,
            right: 16,
            padding: 8,
            borderRadius: 999,
            backgroundColor: "rgba(0,0,0,0.55)",
          }}
        >
          <Icon name="close" size={20} color="#FFFFFF" />
        </Pressable>
      </View>
    </Modal>
  );
}
