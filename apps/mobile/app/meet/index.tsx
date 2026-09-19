import { dark } from "@ditsala/ui-tokens";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Linking, Pressable, Text, View } from "react-native";

import { Icon } from "../../components/Icon";
import { Screen } from "../../components/Screen";
import { ApiError } from "../../lib/api";
import { type MeetingResponse, meetingJoinLink, meetingsApi } from "../../lib/meetings-api";
import { getAccessToken } from "../../lib/session";

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
export default function MyMeetings() {
  const router = useRouter();
  const [meetings, setMeetings] = useState<MeetingResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openingId, setOpeningId] = useState<string | null>(null);

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

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">My meetings</Text>
      <Text className="mb-8 text-base leading-6 text-text-secondary">
        Every meeting you&apos;ve scheduled. Tap one to open it.
      </Text>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      {meetings === null ? (
        <ActivityIndicator color={dark.accent} />
      ) : meetings.length === 0 ? (
        <View className="items-center rounded-xl border border-border bg-surface p-6">
          <Text className="text-center text-text-secondary">
            You haven&apos;t scheduled any meetings yet.
          </Text>
        </View>
      ) : (
        meetings.map((meeting) => (
          <Pressable
            key={meeting.id}
            testID={`my-meeting-row-${meeting.id}`}
            onPress={() => handleOpen(meeting)}
            disabled={openingId !== null}
            className="mb-2 flex-row items-center gap-3 rounded-xl border border-border bg-surface p-4 active:bg-surface-raised"
          >
            <View
              className="h-9 w-9 items-center justify-center rounded-full"
              style={{ backgroundColor: dark.accentMuted }}
            >
              <Icon name="video" size={18} color={dark.accent} />
            </View>
            <View className="flex-1">
              <Text className="text-base font-medium text-text-primary">{meeting.title}</Text>
              <Text className="mt-0.5 text-xs text-text-tertiary">
                {formatScheduled(meeting)} · {meeting.status}
              </Text>
            </View>
            {openingId === meeting.id ? (
              <ActivityIndicator color={dark.accent} />
            ) : (
              <Icon name="chevron-right" size={16} color={dark.textTertiary} />
            )}
          </Pressable>
        ))
      )}
    </Screen>
  );
}
