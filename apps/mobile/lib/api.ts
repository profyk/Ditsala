/**
 * Backend API client for onboarding (docs/DITSALA_MASTER_SPEC.md §9-15).
 * Deliberately thin — no retry/caching logic yet, that's a Phase 3+
 * concern once the full session model exists.
 */

const BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number
  ) {
    super(message);
  }
}

async function request<T>(
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
