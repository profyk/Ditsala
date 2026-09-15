import * as Location from "expo-location";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Text, View } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { sosApi, type SosEvent } from "../../lib/sos-api";
import { triggerSosWithRetry, type SosTriggerHandle, type SosTriggerStatus } from "../../lib/sos-queue";
import { getAccessToken } from "../../lib/session";

const STATUS_LABEL: Record<SosTriggerStatus, string> = {
  sending: "Sending SOS…",
  retrying: "No connection yet — retrying…",
  sent: "SOS sent",
  failed: "Could not send SOS",
  cancelled: "SOS cancelled",
};

/**
 * §26: one-tap SOS with a cancellation window to absorb accidental
 * triggers. The trigger itself is wrapped in `triggerSosWithRetry`
 * (`lib/sos-queue.ts`) — this is the one action in the app that must
 * never silently fail on a network blip, so it keeps retrying in the
 * background rather than surfacing a one-shot error.
 */
export default function Sos() {
  const router = useRouter();
  const [activeEvent, setActiveEvent] = useState<SosEvent | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [triggerStatus, setTriggerStatus] = useState<SosTriggerStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const triggerHandleRef = useRef<SosTriggerHandle | null>(null);
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const escalateTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimers = useCallback(() => {
    if (countdownRef.current) clearInterval(countdownRef.current);
    if (escalateTimerRef.current) clearTimeout(escalateTimerRef.current);
    countdownRef.current = null;
    escalateTimerRef.current = null;
  }, []);

  useEffect(() => clearTimers, [clearTimers]);

  useFocusEffect(
    useCallback(() => {
      return () => {
        // Leaving the screen doesn't cancel a real SOS event — it's a
        // safety trigger, not a form draft — but it does stop a
        // still-retrying *attempt* to send one if the user backs out fast.
        triggerHandleRef.current?.cancel();
      };
    }, [])
  );

  async function handleTrigger() {
    const token = await getAccessToken();
    if (!token) {
      router.replace("/");
      return;
    }
    setError(null);
    setTriggerStatus("sending");

    let lastKnownLocationRef: string | undefined;
    try {
      const position = await Location.getCurrentPositionAsync({});
      lastKnownLocationRef = `${position.coords.latitude},${position.coords.longitude}`;
    } catch {
      // Best-effort — SOS still fires without a location fix.
    }

    const handle = triggerSosWithRetry(token, lastKnownLocationRef, setTriggerStatus);
    triggerHandleRef.current = handle;
    try {
      const event = await handle.promise;
      setTriggerStatus(null);
      setActiveEvent(event);
      startCountdown(event, token);
    } catch {
      // status is already "failed" or "cancelled" via the callback
    }
  }

  function startCountdown(event: SosEvent, token: string) {
    const deadline = Date.now() + event.cancel_window_seconds * 1000;
    setSecondsLeft(event.cancel_window_seconds);
    countdownRef.current = setInterval(() => {
      const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      setSecondsLeft(remaining);
      if (remaining <= 0 && countdownRef.current) {
        clearInterval(countdownRef.current);
        countdownRef.current = null;
      }
    }, 250);
    escalateTimerRef.current = setTimeout(async () => {
      try {
        const escalated = await sosApi.escalate(token, event.id);
        setActiveEvent(escalated);
      } catch {
        setError("Could not confirm escalation — your Circle may not have been notified.");
      }
    }, event.cancel_window_seconds * 1000);
  }

  async function handleCancel() {
    if (!activeEvent) return;
    const token = await getAccessToken();
    if (!token) return;
    clearTimers();
    try {
      const cancelled = await sosApi.cancel(token, activeEvent.id);
      setActiveEvent(cancelled);
    } catch {
      setError("Could not cancel — if this was accidental, tell your Circle directly.");
    }
  }

  if (activeEvent && activeEvent.status === "armed") {
    return (
      <Screen scroll={false}>
        <View className="flex-1 items-center justify-center">
          <Text className="mb-4 text-2xl font-semibold text-danger">SOS triggered</Text>
          <Text className="mb-2 text-6xl font-bold text-text-primary">{secondsLeft}</Text>
          <Text className="mb-12 text-base text-text-secondary">
            Your Circle will be notified automatically unless you cancel.
          </Text>
          <Button testID="sos-cancel-button" label="Cancel SOS" onPress={handleCancel} />
        </View>
      </Screen>
    );
  }

  if (activeEvent && (activeEvent.status === "escalated" || activeEvent.status === "cancelled")) {
    return (
      <Screen>
        <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">
          {activeEvent.status === "escalated" ? "Circle notified" : "SOS cancelled"}
        </Text>
        <Text className="mb-8 text-base text-text-secondary">
          {activeEvent.status === "escalated"
            ? "Your trusted Circle and next of kin have been notified with your last known location."
            : "No one was notified."}
        </Text>
        <Button label="Done" onPress={() => setActiveEvent(null)} />
      </Screen>
    );
  }

  return (
    <Screen scroll={false}>
      <View className="flex-1 items-center justify-center">
        <Text className="mb-2 text-3xl font-semibold text-text-primary">Emergency SOS</Text>
        <Text className="mb-12 max-w-xs text-center text-base text-text-secondary">
          Alerts your trusted Circle and next of kin with your location. You&apos;ll have a
          few seconds to cancel first.
        </Text>

        {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}
        {triggerStatus ? (
          <Text className="mb-4 text-sm text-text-secondary">
            {STATUS_LABEL[triggerStatus]}
          </Text>
        ) : null}

        <Button
          testID="sos-trigger-button"
          label="Trigger SOS"
          onPress={handleTrigger}
          loading={triggerStatus === "sending" || triggerStatus === "retrying"}
        />
      </View>
    </Screen>
  );
}
