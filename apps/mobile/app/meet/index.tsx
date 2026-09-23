import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Linking, Pressable, Text, TextInput, View } from "react-native";

import { Icon } from "../../components/Icon";
import { Screen } from "../../components/Screen";
import { ApiError } from "../../lib/api";
import { type MeetingResponse, meetingJoinLink, meetingsApi } from "../../lib/meetings-api";
import { getAccessToken } from "../../lib/session";
import { useTheme } from "../../lib/theme-context";

function formatScheduled(meeting: MeetingResponse): string {
  if (!meeting.scheduled_start_at) return "No scheduled time";
  return new Date(meeting.scheduled_start_at).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * "My Meetings" — every meeting this account hosts (GET /meetings already
 * returns exactly that, no local persistence needed). Opening one hands
 * the host off into the Ditsala Meet web app via a short-lived, meeting-
 * scoped token (`POST /meetings/{id}/host-link`) so it opens straight into
 * the live room as host, not the guest-join form.
 */
type ExpandedPanel = "none" | "delete" | "co-host";

export default function MyMeetings() {
  const router = useRouter();
  const { colors } = useTheme();
  const [meetings, setMeetings] = useState<MeetingResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<{ id: string; panel: ExpandedPanel } | null>(null);
  const [coHostPhone, setCoHostPhone] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const accessToken = await getAccessToken();
    if (!accessToken) {
      router.replace("/");
      return;
    }
    try {
      const list = await meetingsApi.list(accessToken);
      list.sort((a, b) => {
        const aTime = a.scheduled_start_at ? new Date(a.scheduled_start_at).getTime() : 0;
        const bTime = b.scheduled_start_at ? new Date(b.scheduled_start_at).getTime() : 0;
        return bTime - aTime;
      });
      setMeetings(list);
    } catch {
      setError("Could not load your meetings.");
    }
  }, [router]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  function toggle(meetingId: string, panel: ExpandedPanel) {
    setError(null);
    setCoHostPhone("");
    setExpanded((current) =>
      current?.id === meetingId && current.panel === panel ? null : { id: meetingId, panel }
    );
  }

  async function handleOpen(meeting: MeetingResponse) {
    setError(null);
    setOpeningId(meeting.id);
    try {
      const accessToken = await getAccessToken();
      if (!accessToken) {
        router.replace("/");
        return;
      }
      const { token } = await meetingsApi.hostJoinLink(accessToken, meeting.id);
      const url = `${meetingJoinLink(meeting.id)}?hj=${encodeURIComponent(token)}`;
      await Linking.openURL(url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not open this meeting.");
    } finally {
      setOpeningId(null);
    }
  }

  async function handleDelete(meetingId: string) {
    setError(null);
    setBusy(true);
    try {
      const accessToken = await getAccessToken();
      if (!accessToken) {
        router.replace("/");
        return;
      }
      await meetingsApi.delete(accessToken, meetingId);
      setExpanded(null);
      setMeetings((current) => current?.filter((m) => m.id !== meetingId) ?? current);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete this meeting.");
    } finally {
      setBusy(false);
    }
  }

  async function handleInviteCoHost(meetingId: string) {
    if (!coHostPhone.trim()) return;
    setError(null);
    setBusy(true);
    try {
      const accessToken = await getAccessToken();
      if (!accessToken) {
        router.replace("/");
        return;
      }
      await meetingsApi.inviteCoHost(accessToken, meetingId, coHostPhone.trim());
      setExpanded(null);
      setCoHostPhone("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not invite that person.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">My meetings</Text>
      <Text className="mb-8 text-base leading-6 text-text-secondary">
        Every meeting you&apos;ve scheduled. Tap one to open it.
      </Text>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      {meetings === null ? (
        <ActivityIndicator color={colors.accent} />
      ) : meetings.length === 0 ? (
        <View className="items-center rounded-xl border border-border bg-surface p-6">
          <Text className="text-center text-text-secondary">
            You haven&apos;t scheduled any meetings yet.
          </Text>
        </View>
      ) : (
        meetings.map((meeting) => {
          const isExpanded = expanded?.id === meeting.id;
          return (
            <View
              key={meeting.id}
              className="mb-2 overflow-hidden rounded-xl border border-border bg-surface"
            >
              <Pressable
                testID={`my-meeting-row-${meeting.id}`}
                onPress={() => handleOpen(meeting)}
                disabled={openingId !== null}
                className="flex-row items-center gap-3 p-4 active:bg-surface-raised"
              >
                <View
                  className="h-9 w-9 items-center justify-center rounded-full"
                  style={{ backgroundColor: colors.accentMuted }}
                >
                  <Icon name="video" size={18} color={colors.accent} />
                </View>
                <View className="flex-1">
                  <Text className="text-base font-medium text-text-primary">{meeting.title}</Text>
                  <Text className="mt-0.5 text-xs text-text-tertiary">
                    {formatScheduled(meeting)} · {meeting.status}
                  </Text>
                  <Text
                    selectable
                    testID={`my-meeting-id-${meeting.id}`}
                    className="mt-0.5 text-xs text-text-tertiary"
                  >
                    ID: {meeting.id}
                  </Text>
                </View>
                {openingId === meeting.id ? (
                  <ActivityIndicator color={colors.accent} />
                ) : (
                  <Icon name="chevron-right" size={16} color={colors.textTertiary} />
                )}
              </Pressable>

              <View className="flex-row gap-2 border-t border-border px-4 py-2">
                <Pressable
                  testID={`my-meeting-invite-cohost-${meeting.id}`}
                  onPress={() => toggle(meeting.id, "co-host")}
                  className="flex-1 items-center rounded-lg py-2 active:bg-surface-raised"
                >
                  <Text className="text-xs font-medium text-accent">Invite co-host</Text>
                </Pressable>
                <Pressable
                  testID={`my-meeting-delete-${meeting.id}`}
                  onPress={() => toggle(meeting.id, "delete")}
                  className="flex-1 items-center rounded-lg py-2 active:bg-surface-raised"
                >
                  <Text className="text-xs font-medium text-danger">Delete</Text>
                </Pressable>
              </View>

              {isExpanded && expanded?.panel === "co-host" ? (
                <View className="gap-2 border-t border-border p-4">
                  <Text className="text-xs text-text-secondary">
                    Enter the co-host&apos;s phone number. They&apos;ll get host-level controls
                    the moment they join.
                  </Text>
                  <TextInput
                    testID={`my-meeting-cohost-phone-input-${meeting.id}`}
                    value={coHostPhone}
                    onChangeText={setCoHostPhone}
                    placeholder="+27..."
                    keyboardType="phone-pad"
                    placeholderTextColor={colors.textTertiary}
                    className="rounded-lg border border-border bg-background px-3 py-2 text-text-primary"
                  />
                  <Pressable
                    testID={`my-meeting-cohost-confirm-${meeting.id}`}
                    onPress={() => handleInviteCoHost(meeting.id)}
                    disabled={busy || !coHostPhone.trim()}
                    className="items-center rounded-lg bg-accent py-2 disabled:opacity-50"
                  >
                    <Text className="text-sm font-medium text-background">
                      {busy ? "Inviting…" : "Send invite"}
                    </Text>
                  </Pressable>
                </View>
              ) : null}

              {isExpanded && expanded?.panel === "delete" ? (
                <View className="gap-2 border-t border-border p-4">
                  <Text className="text-xs text-text-secondary">
                    Delete &quot;{meeting.title}&quot;? This can&apos;t be undone.
                  </Text>
                  <Pressable
                    testID={`my-meeting-delete-confirm-${meeting.id}`}
                    onPress={() => handleDelete(meeting.id)}
                    disabled={busy}
                    className="items-center rounded-lg bg-danger py-2 disabled:opacity-50"
                  >
                    <Text className="text-sm font-medium text-white">
                      {busy ? "Deleting…" : "Yes, delete this meeting"}
                    </Text>
                  </Pressable>
                </View>
              ) : null}
            </View>
          );
        })
      )}
    </Screen>
  );
}
