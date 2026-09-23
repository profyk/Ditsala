import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Linking, Pressable, Text, TextInput, View } from "react-native";

import { Icon } from "../../components/Icon";
import { Screen } from "../../components/Screen";
import { meetingJoinLink } from "../../lib/meetings-api";
import { formatPrice, plansApi, type Plan } from "../../lib/plans-api";
import { getAccessToken } from "../../lib/session";
import { useTheme } from "../../lib/theme-context";

const PRODUCT_LABEL: Record<Plan["product"], string> = {
  free: "Free",
  vip: "VIP",
  business: "Business",
  conference: "Conference Room",
};

function formatEntitlement(entitlement: { key: string; value: unknown }): string {
  const label = entitlement.key.replace(/_/g, " ");
  if (entitlement.value === true) return label;
  if (entitlement.value === false) return `No ${label}`;
  return `${label}: ${String(entitlement.value)}`;
}

/**
 * Conference Room hub — reached from Settings. Three real, working
 * things live here rather than three separate settings rows: opening
 * the room you host (schedule / "My meetings", both existing screens),
 * joining someone else's meeting by its id, and seeing what each plan
 * (`GET /plans`, admin-configured, not hardcoded) actually includes.
 */
export default function ConferenceRoom() {
  const router = useRouter();
  const { colors } = useTheme();
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [myPlanCode, setMyPlanCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [meetingId, setMeetingId] = useState("");
  const [joining, setJoining] = useState(false);

  const load = useCallback(async () => {
    const accessToken = await getAccessToken();
    if (!accessToken) {
      router.replace("/");
      return;
    }
    try {
      const [planList, mine] = await Promise.all([
        plansApi.list(accessToken),
        plansApi.mine(accessToken),
      ]);
      setPlans(planList);
      setMyPlanCode(mine.plan_code);
    } catch {
      setError("Could not load plans right now.");
    }
  }, [router]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  async function handleJoin() {
    const id = meetingId.trim();
    if (!id) return;
    setJoining(true);
    try {
      await Linking.openURL(meetingJoinLink(id));
    } finally {
      setJoining(false);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Conference Room</Text>
      <Text className="mb-8 text-base leading-6 text-text-secondary">
        Host, schedule, and join Ditsala Meet calls — plus what&apos;s included on each plan.
      </Text>

      <View className="mb-6 flex-row gap-2">
        <Pressable
          testID="conference-room-schedule-button"
          onPress={() => router.push("/meet/schedule")}
          className="flex-1 items-center gap-2 rounded-xl border border-border bg-surface p-4 active:bg-surface-raised"
        >
          <Icon name="video" size={22} color={colors.accent} />
          <Text className="text-sm font-medium text-text-primary">Schedule</Text>
        </Pressable>
        <Pressable
          testID="conference-room-my-meetings-button"
          onPress={() => router.push("/meet")}
          className="flex-1 items-center gap-2 rounded-xl border border-border bg-surface p-4 active:bg-surface-raised"
        >
          <Icon name="video" size={22} color={colors.accent} />
          <Text className="text-sm font-medium text-text-primary">My meetings</Text>
        </Pressable>
      </View>

      <Text className="mb-2 text-xs font-medium uppercase tracking-widest text-text-tertiary">
        Join a meeting
      </Text>
      <View className="mb-8 flex-row items-center gap-2">
        <TextInput
          testID="conference-room-meeting-id-input"
          value={meetingId}
          onChangeText={setMeetingId}
          placeholder="Meeting ID"
          placeholderTextColor={colors.textTertiary}
          autoCapitalize="none"
          autoCorrect={false}
          className="flex-1 rounded-xl border border-border bg-surface px-4 py-3 text-base text-text-primary"
        />
        <Pressable
          testID="conference-room-join-button"
          onPress={handleJoin}
          disabled={!meetingId.trim() || joining}
          className="items-center justify-center rounded-xl bg-accent px-5 py-3 disabled:opacity-50"
        >
          {joining ? (
            <ActivityIndicator color="#FFFFFF" />
          ) : (
            <Text className="text-sm font-semibold text-white">Join</Text>
          )}
        </Pressable>
      </View>

      <Text className="mb-2 text-xs font-medium uppercase tracking-widest text-text-tertiary">
        Plans &amp; tools
      </Text>
      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}
      {plans === null ? (
        <ActivityIndicator color={colors.accent} />
      ) : plans.length === 0 ? (
        <Text className="text-sm text-text-tertiary">No plans configured yet.</Text>
      ) : (
        plans.map((plan) => {
          const isMine = plan.code === myPlanCode;
          return (
            <View
              key={plan.id}
              className={`mb-3 rounded-xl border p-4 bg-surface ${
                isMine ? "border-accent" : "border-border"
              }`}
            >
              <View className="mb-1 flex-row items-center justify-between">
                <Text className="text-base font-semibold text-text-primary">{plan.name}</Text>
                {isMine ? (
                  <Text className="text-xs font-medium uppercase tracking-widest text-accent">
                    Your plan
                  </Text>
                ) : null}
              </View>
              <Text className="mb-2 text-xs uppercase tracking-widest text-text-tertiary">
                {PRODUCT_LABEL[plan.product]}
              </Text>
              <Text className="mb-2 text-sm text-text-secondary">
                {plan.prices.length > 0
                  ? plan.prices
                      .map((p) => `${formatPrice(p)} / ${p.billing_interval.replace("_", " ")}`)
                      .join(" · ")
                  : "Free"}
              </Text>
              {plan.entitlements.length > 0 ? (
                <View className="gap-1">
                  {plan.entitlements.map((entitlement) => (
                    <Text key={entitlement.key} className="text-sm text-text-secondary">
                      • {formatEntitlement(entitlement)}
                    </Text>
                  ))}
                </View>
              ) : null}
            </View>
          );
        })
      )}
    </Screen>
  );
}
