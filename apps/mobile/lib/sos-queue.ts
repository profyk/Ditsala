/**
 * SOS is the one action in this app that must never silently fail on a
 * network blip (docs/DITSALA_MASTER_SPEC.md §26) — `lib/api.ts`'s
 * `request()` already retries a handful of times over a couple of
 * seconds, but a real emergency can be triggered somewhere with no
 * signal at all for much longer than that. This keeps retrying in the
 * background — by default indefinitely — until it succeeds or the
 * caller explicitly cancels (e.g. the user leaves the SOS screen).
 */

import { sosApi, type SosEvent } from "./sos-api";

export type SosTriggerStatus = "sending" | "retrying" | "sent" | "failed" | "cancelled";

export interface SosTriggerHandle {
  promise: Promise<SosEvent>;
  cancel: () => void;
}

export function triggerSosWithRetry(
  accessToken: string,
  lastKnownLocationRef: string | undefined,
  onStatusChange: (status: SosTriggerStatus, attempt: number) => void,
  options: { maxAttempts?: number; retryDelayMs?: number } = {}
): SosTriggerHandle {
  const maxAttempts = options.maxAttempts ?? Infinity;
  const retryDelayMs = options.retryDelayMs ?? 5000;
  let cancelled = false;

  const promise = (async (): Promise<SosEvent> => {
    let attempt = 0;
    while (!cancelled) {
      attempt++;
      onStatusChange(attempt === 1 ? "sending" : "retrying", attempt);
      try {
        const event = await sosApi.trigger(accessToken, lastKnownLocationRef);
        if (cancelled) {
          onStatusChange("cancelled", attempt);
        } else {
          onStatusChange("sent", attempt);
        }
        return event;
      } catch (err) {
        if (cancelled) {
          onStatusChange("cancelled", attempt);
          throw err;
        }
        if (attempt >= maxAttempts) {
          onStatusChange("failed", attempt);
          throw err;
        }
        await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
      }
    }
    onStatusChange("cancelled", attempt);
    throw new Error("SOS trigger cancelled");
  })();

  return {
    promise,
    cancel: () => {
      cancelled = true;
    },
  };
}
