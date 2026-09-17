/**
 * Backend API client for onboarding (docs/DITSALA_MASTER_SPEC.md §9-15)
 * and the shared HTTP transport every other `lib/*-api.ts` client is
 * built on. Retries transient failures (no response at all, or a 502/503/
 * 504 from something in front of the backend) with backoff — real
 * connectivity on this network is often patchy, and a single dropped
 * packet shouldn't surface as an error the user has to manually retry.
 * Never retries a 4xx (that's a real rejection, not a blip) or a bare 500
 * (the request may have already been processed server-side — retrying a
 * non-idempotent POST blind risks a duplicate side effect).
 */

export const BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const REQUEST_TIMEOUT_MS = 15_000;
const MAX_ATTEMPTS = 3;
const RETRY_DELAYS_MS = [500, 1500];
const RETRYABLE_STATUSES = new Set([502, 503, 504]);

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number
  ) {
    super(message);
  }
}

/** Thrown when a request never got a response at all (offline, timeout,
 * DNS failure) — distinct from `ApiError` so callers can show "check your
 * connection" instead of a server-rejection message. */
export class NetworkError extends Error {
  constructor(message = "No connection. Check your network and try again.") {
    super(message);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; token?: string } = {}
): Promise<T> {
  let lastNetworkError: unknown;

  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
    if (attempt > 0) await sleep(RETRY_DELAYS_MS[attempt - 1]);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    let response: Response;
    try {
      response = await fetch(`${BASE_URL}/api/v1${path}`, {
        method: options.method ?? (options.body === undefined ? "GET" : "POST"),
        headers: {
          "Content-Type": "application/json",
          ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
        },
        body: options.body ? JSON.stringify(options.body) : undefined,
        signal: controller.signal,
      });
    } catch (err) {
      lastNetworkError = err;
      continue; // no response at all — worth a retry
    } finally {
      clearTimeout(timeout);
    }

    if (!response.ok) {
      if (RETRYABLE_STATUSES.has(response.status) && attempt < MAX_ATTEMPTS - 1) {
        continue;
      }
      const body = await response.json().catch(() => ({}));
      const detail = typeof body?.detail === "string" ? body.detail : "Something went wrong.";
      throw new ApiError(detail, response.status);
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }

  throw new NetworkError(
    lastNetworkError instanceof Error && lastNetworkError.name === "AbortError"
      ? "The request timed out. Check your network and try again."
      : undefined
  );
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

/** ADR 0014 — the entire normal-tier signup: phone (E.164) + display name. */
export interface PhoneSignupPayload {
  phone: string;
  display_name: string;
  invite_code?: string | null;
}

export const onboardingApi = {
  signup: (payload: SignupPayload) =>
    request<OnboardingSession>("/onboarding/signup", { body: payload }),

  signupPhone: (payload: PhoneSignupPayload) =>
    request<OnboardingSession>("/onboarding/signup/phone", { body: payload }),

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

/**
 * ADR 0012: `vip` accounts (mandatory KYC) get the two-factor fields
 * populated (`login_token`/`kyc_token`/`job_id` — the DITSALA Code was
 * already checked, a fresh liveness check is still needed). `normal`
 * accounts (the default for every real signup — no KYC at all) get a
 * session directly, since the code alone is the whole login. Exactly
 * one group is populated, selected by `requires_liveness`.
 */
export interface LoginStartResult {
  requires_liveness: boolean;
  login_token: string | null;
  kyc_token: string | null;
  job_id: string | null;
  access_token: string | null;
  refresh_token: string | null;
  device_id: string | null;
}

export interface Device {
  id: string;
  device_name: string;
  platform: string;
  is_trusted: boolean;
  last_seen_at: string;
  revoked_at: string | null;
}

/** ADR 0014: `account_tier` gates tier-specific UI (e.g. hiding logout for
 * `normal`); `identifier` is what `authApi.loginStart` expects — phone for
 * `normal`, email for `vip`. */
export interface CurrentUser {
  id: string;
  display_name: string;
  avatar_url: string | null;
  account_tier: "normal" | "vip";
  identifier: string;
}

export const authApi = {
  getMe: (accessToken: string) =>
    request<CurrentUser>("/auth/me", { method: "GET", token: accessToken }),

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
