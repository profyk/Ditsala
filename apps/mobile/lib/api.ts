/**
 * Backend API client for onboarding (docs/DITSALA_MASTER_SPEC.md §9-15).
 * Deliberately thin — no retry/caching logic yet, that's a Phase 3+
 * concern once the full session model exists.
 */

export const BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number
  ) {
    super(message);
  }
}

export async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; token?: string } = {}
): Promise<T> {
  const response = await fetch(`${BASE_URL}/api/v1${path}`, {
    method: options.method ?? (options.body === undefined ? "GET" : "POST"),
    headers: {
      "Content-Type": "application/json",
      ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body?.detail === "string" ? body.detail : "Something went wrong.";
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export type AccountState =
  | "pending_email"
  | "pending_phone"
  | "pending_kyc_document"
  | "pending_kyc_liveness"
  | "pending_next_of_kin"
  | "pending_code"
  | "active"
  | "manual_review"
  | "suspended"
  | "deactivated"
  | "banned";

export interface OnboardingSession {
  onboarding_token: string;
  account_state: AccountState;
}

export interface AccountStateResponse {
  account_state: AccountState;
}

export interface KycSdkToken {
  token: string;
  job_id: string;
}

export interface SignupPayload {
  email: string;
  phone: string;
  display_name: string;
  date_of_birth: string; // YYYY-MM-DD
  national_id: string;
}

export const onboardingApi = {
  signup: (payload: SignupPayload) =>
    request<OnboardingSession>("/onboarding/signup", { body: payload }),

  getStatus: (token: string) =>
    request<AccountStateResponse>("/onboarding/status", { method: "GET", token }),

  resendEmailCode: (token: string) =>
    request<AccountStateResponse>("/onboarding/email/resend", { token }),

  confirmEmail: (token: string, code: string) =>
    request<AccountStateResponse>("/onboarding/email/confirm", { token, body: { code } }),

  requestPhoneCode: (token: string) =>
    request<AccountStateResponse>("/onboarding/phone/request", { token }),

  confirmPhone: (token: string, code: string) =>
    request<AccountStateResponse>("/onboarding/phone/confirm", { token, body: { code } }),

  startKycDocument: (token: string, documentType: "sa_id" | "passport") =>
    request<KycSdkToken>("/onboarding/kyc/document/start", {
      token,
      body: { document_type: documentType },
    }),

  startKycLiveness: (token: string) =>
    request<KycSdkToken>("/onboarding/kyc/liveness/start", { token }),

  addNextOfKin: (
    token: string,
    payload: { full_name: string; relationship: string; phone: string; email: string | null }
  ) => request<AccountStateResponse>("/onboarding/next-of-kin", { token, body: payload }),

  setDitsalaCode: (token: string, code: string) =>
    request<AccountStateResponse>("/onboarding/code", { token, body: { code } }),
};

// --- §16-17: authentication & sessions ---

export interface DeviceRegistration {
  device_name: string;
  platform: "ios" | "android";
  push_token: string | null;
}

export interface SessionResult {
  access_token: string;
  refresh_token: string;
  device_id: string;
}

export interface LoginStartResult {
  login_token: string;
  kyc_token: string;
  job_id: string;
}

export interface Device {
  id: string;
  device_name: string;
  platform: string;
  is_trusted: boolean;
  last_seen_at: string;
  revoked_at: string | null;
}

export const authApi = {
  completeOnboarding: (onboardingToken: string, device: DeviceRegistration) =>
    request<SessionResult>("/auth/complete-onboarding", {
      token: onboardingToken,
      body: device,
    }),

  loginStart: (identifier: string, ditsalaCode: string, device: DeviceRegistration) =>
    request<LoginStartResult>("/auth/login/start", {
      body: { identifier, ditsala_code: ditsalaCode, ...device },
    }),

  loginComplete: (loginToken: string) =>
    request<SessionResult>("/auth/login/complete", { body: { login_token: loginToken } }),

  refresh: (refreshToken: string) =>
    request<{ access_token: string; refresh_token: string }>("/auth/refresh", {
      body: { refresh_token: refreshToken },
    }),

  logout: (refreshToken: string) =>
    request<void>("/auth/logout", { body: { refresh_token: refreshToken } }),

  logoutAll: (accessToken: string) =>
    request<void>("/auth/logout-all", { token: accessToken, body: {} }),

  listDevices: (accessToken: string) =>
    request<Device[]>("/auth/devices", { method: "GET", token: accessToken }),

  revokeDevice: (accessToken: string, deviceId: string) =>
    request<void>(`/auth/devices/${deviceId}`, { method: "DELETE", token: accessToken }),
};
