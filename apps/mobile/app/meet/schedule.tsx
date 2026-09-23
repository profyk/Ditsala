import { useRouter } from "expo-router";
import { useState } from "react";
import { Share, Switch, Text, View } from "react-native";

import { Button } from "../../components/Button";
import { ScheduleDateTimePicker } from "../../components/ScheduleDateTimePicker";
import { Screen } from "../../components/Screen";
import { TextField } from "../../components/TextField";
import { ApiError } from "../../lib/api";
import { type MeetingResponse, meetingJoinLink, meetingsApi } from "../../lib/meetings-api";
import { getAccessToken } from "../../lib/session";

/**
 * Schedule a Ditsala Meet call from the mobile app (docs/DITSALA_MEET_SPEC.md
 * §9 Phase 4) — a title, a date/time from the popup calendar below, and a
 * required password (§5.2's "extra security" — every scheduled meeting
 * from this screen is password-protected, not optional). Once created,
 * the generated `meet.ditsala.app` link is ready to share via the native
 * share sheet; a recipient who opens it early sees the scheduled time
 * instead of an empty room (enforced server-side, see the meet web
 * app's join-info gate).
 */
export default function ScheduleMeeting() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [scheduledAt, setScheduledAt] = useState<Date | null>(null);
  const [password, setPassword] = useState("");
  const [waitingRoomEnabled, setWaitingRoomEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState<MeetingResponse | null>(null);

  const canSubmit = title.trim().length > 0 && scheduledAt !== null && password.length >= 4;

  async function handleSchedule() {
    if (!scheduledAt) return;
    setError(null);
    setSubmitting(true);
    try {
      const token = await getAccessToken();
      if (!token) {
        router.replace("/");
        return;
      }
      const meeting = await meetingsApi.create(token, {
        title: title.trim(),
        scheduled_start_at: scheduledAt.toISOString(),
        password,
        waiting_room_enabled: waitingRoomEnabled,
      });
      setCreated(meeting);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not schedule this meeting.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleShare(meeting: MeetingResponse) {
    const link = meetingJoinLink(meeting.id);
    await Share.share({
      message: `Join "${meeting.title}" on DITSALA Meet: ${link}\n\nPassword: ${password}`,
    });
  }

  async function handleShareHostPin(meeting: MeetingResponse) {
    if (!meeting.host_pin) return;
    const link = meetingJoinLink(meeting.id);
    await Share.share({
      message: `You're a co-host for "${meeting.title}" on DITSALA Meet: ${link}\n\nHost PIN: ${meeting.host_pin}\n\nEnter this PIN on the meeting page instead of a name/password — it signs you in with full host controls.`,
    });
  }

  if (created) {
    const link = meetingJoinLink(created.id);
    return (
      <Screen scroll={false}>
        <View className="flex-1 items-center justify-center px-2">
          <View className="mb-5 h-16 w-16 items-center justify-center rounded-full bg-accent-muted">
            <Text className="text-3xl">🎉</Text>
          </View>
          <Text className="mb-2 text-center text-2xl font-semibold text-text-primary">
            Meeting scheduled
          </Text>
          <Text className="mb-6 text-center text-base text-text-secondary">
            {created.scheduled_start_at
              ? new Date(created.scheduled_start_at).toLocaleString(undefined, {
                  weekday: "long",
                  month: "long",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                  hour12: false,
                })
              : ""}
          </Text>
          <View className="mb-6 w-full rounded-lg border border-border bg-surface p-4">
            <Text className="mb-1 text-xs font-medium uppercase tracking-widest text-text-tertiary">
              Meeting link
            </Text>
            <Text selectable className="text-base text-accent">
              {link}
            </Text>
            <View className="my-3 h-px bg-border" />
            <Text className="mb-1 text-xs font-medium uppercase tracking-widest text-text-tertiary">
              Password
            </Text>
            <Text selectable className="text-base text-text-primary">
              {password}
            </Text>
          </View>
          {created.host_pin ? (
            <View className="mb-6 w-full rounded-lg border border-accent bg-accent-muted p-4">
              <Text className="mb-1 text-xs font-medium uppercase tracking-widest text-accent">
                Host PIN
              </Text>
              <Text selectable className="mb-1 text-2xl font-semibold tracking-widest text-text-primary">
                {created.host_pin}
              </Text>
              <Text className="text-xs text-text-secondary">
                Only you and anyone you share this with can enter as host — no password needed.
                Share it with a co-host separately from the meeting link above.
              </Text>
            </View>
          ) : null}
          <View className="w-full">
            <Button label="Share invite" onPress={() => handleShare(created)} />
            <View className="h-3" />
            {created.host_pin ? (
              <>
                <Button
                  label="Share with a co-host"
                  variant="secondary"
                  onPress={() => handleShareHostPin(created)}
                />
                <View className="h-3" />
              </>
            ) : null}
            <Button
              label="View my meetings"
              variant="secondary"
              onPress={() => router.replace("/meet")}
            />
            <View className="h-3" />
            <Button label="Done" variant="secondary" onPress={() => router.replace("/home")} />
          </View>
        </View>
      </Screen>
    );
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Schedule a meeting</Text>
      <Text className="mb-8 text-base leading-6 text-text-secondary">
        Pick a date and time, set a password, then share the link — only people with both can
        join.
      </Text>

      <TextField
        label="Title"
        value={title}
        onChangeText={setTitle}
        placeholder="Weekly check-in"
        testID="meeting-title-input"
      />
      <ScheduleDateTimePicker
        value={scheduledAt}
        onChange={setScheduledAt}
        testID="meeting-datetime-picker"
      />
      <TextField
        label="Password"
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        placeholder="At least 4 characters"
        testID="meeting-password-input"
      />

      <View className="mb-6 flex-row items-center justify-between rounded-xl border border-border bg-surface px-4 py-3">
        <View className="flex-1 pr-3">
          <Text className="text-base text-text-primary">Waiting room</Text>
          <Text className="text-sm text-text-tertiary">
            Admit guests yourself before they can join.
          </Text>
        </View>
        <Switch
          testID="waiting-room-switch"
          value={waitingRoomEnabled}
          onValueChange={setWaitingRoomEnabled}
        />
      </View>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <Button
        testID="schedule-submit-button"
        label="Schedule & get link"
        onPress={handleSchedule}
        loading={submitting}
        disabled={!canSubmit}
      />
    </Screen>
  );
}
