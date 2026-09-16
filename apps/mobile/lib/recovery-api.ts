/**
 * Backend API client for account recovery (docs/DITSALA_MASTER_SPEC.md
 * §33) — used when a person has lost their device and needs to regain
 * access from a new one. See docs/ACCOUNT_RECOVERY.md for the user-facing
 * explanation of why this flow re-verifies as much as it does.
 */

import { request } from "./api";

export interface RecoveryRequest {
  id: string;
  status: string;
  created_at: string;
}

export interface RecoveryKycSdkToken {
  token: string;
  job_id: string;
}

export interface RecoverySessionResult {
  access_token: string;
  refresh_token: string;
  device_id: string;
}

export const recoveryApi = {
  start: (email: string, phone: string) =>
    request<RecoveryRequest>("/recovery/start", { body: { email, phone } }),

  confirmEmail: (recoveryRequestId: string, code: string) =>
    request<void>("/recovery/email/confirm", {
      body: { recovery_request_id: recoveryRequestId, code },
    }),

  confirmPhone: (recoveryRequestId: string, code: string) =>
    request<void>("/recovery/phone/confirm", {
      body: { recovery_request_id: recoveryRequestId, code },
    }),

  startLiveness: (recoveryRequestId: string) =>
    request<RecoveryKycSdkToken>("/recovery/liveness/start", {
      body: { recovery_request_id: recoveryRequestId },
    }),

  complete: (payload: {
    recoveryRequestId: string;
    newDitsalaCode: string;
    deviceName: string;
    platform: "ios" | "android";
    pushToken: string | null;
  }) =>
    request<RecoverySessionResult>("/recovery/complete", {
      body: {
        recovery_request_id: payload.recoveryRequestId,
        new_ditsala_code: payload.newDitsalaCode,
        device_name: payload.deviceName,
        platform: payload.platform,
        push_token: payload.pushToken,
      },
    }),
};
