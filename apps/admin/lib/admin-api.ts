import { request } from "./api";

// --- auth ---

export interface LoginStartResult {
  status: "mfa_enroll_required" | "mfa_code_required";
  mfa_enroll_token?: string;
  provisioning_uri?: string;
  login_token?: string;
}

export interface AdminSession {
  access_token: string;
  email: string;
  role: string;
}

export interface AdminMe {
  email: string;
  role: string;
}

export const authApi = {
  loginStart: (email: string, password: string) =>
    request<LoginStartResult>("/admin/auth/login/start", { body: { email, password } }),

  enrollMfa: (enrollToken: string, code: string) =>
    request<AdminSession>("/admin/auth/mfa/enroll", {
      body: { enroll_token: enrollToken, code },
    }),

  completeLogin: (loginToken: string, code: string) =>
    request<AdminSession>("/admin/auth/login/complete", {
      body: { login_token: loginToken, code },
    }),

  logout: (token: string) =>
    request<void>("/admin/auth/logout", { method: "POST", token }),

  me: (token: string) => request<AdminMe>("/admin/auth/me", { method: "GET", token }),
};

// --- dashboard ---

export interface DashboardSummary {
  signups_today: number;
  signups_this_week: number;
  active_accounts: number;
  manual_review_count: number;
  open_reports_count: number;
  pending_invitations: number;
}

// --- users ---

export interface UserSummary {
  id: string;
  email: string;
  phone: string;
  display_name: string;
  account_state: string;
  created_at: string;
}

export interface AuditLogEntry {
  id: string;
  created_at: string;
  actor_type: string;
  actor_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  metadata_json: Record<string, unknown> | null;
}

// --- reports ---

export interface Report {
  id: string;
  reporter_user_id: string;
  reported_user_id: string;
  reason: string;
  context_ref: string | null;
  status: string;
  created_at: string;
}

// --- security ---

export interface SecuritySummary {
  locked_accounts: number;
  failed_logins_last_24h: number;
  active_sessions: number;
  new_devices_last_24h: number;
}

// --- invitations ---

export interface InvitationStats {
  sent: number;
  redeemed: number;
  expired: number;
  top_inviters: { inviter_user_id: string; sent_count: number }[];
}

// --- system config ---

export interface SystemConfigEntry {
  key: string;
  value: Record<string, unknown>;
  updated_at: string;
  updated_by_admin_id: string | null;
}

// --- KYC review ---

export interface KycDocument {
  id: string;
  document_type: string;
  status: string;
  result_summary: Record<string, unknown> | null;
  created_at: string;
}

export interface KycFaceVerification {
  id: string;
  selfie_liveness_score: number | null;
  face_match_score: number | null;
  status: string;
  verified_at: string | null;
}

export interface KycDetail {
  user: UserSummary;
  documents: KycDocument[];
  face_verifications: KycFaceVerification[];
}

export const adminApi = {
  // dashboard
  getDashboard: (token: string) =>
    request<DashboardSummary>("/admin/dashboard", { method: "GET", token }),

  // users
  searchUsers: (
    token: string,
    params: { q?: string; account_state?: string; limit?: number; offset?: number } = {}
  ) => request<UserSummary[]>("/admin/users", { method: "GET", token, params }),

  getUser: (token: string, userId: string) =>
    request<UserSummary>(`/admin/users/${userId}`, { method: "GET", token }),

  getUserHistory: (token: string, userId: string) =>
    request<AuditLogEntry[]>(`/admin/users/${userId}/history`, { method: "GET", token }),

  forceAccountState: (token: string, userId: string, newState: string, reason: string) =>
    request<UserSummary>(`/admin/users/${userId}/state`, {
      token,
      body: { new_state: newState, reason },
    }),

  // reports
  listReports: (token: string, status = "open") =>
    request<Report[]>("/admin/reports", { method: "GET", token, params: { status } }),

  actionReport: (
    token: string,
    reportId: string,
    action: "warn" | "suspend" | "ban",
    reason: string
  ) =>
    request<Report>(`/admin/reports/${reportId}/action`, { token, body: { action, reason } }),

  // security
  getSecuritySummary: (token: string) =>
    request<SecuritySummary>("/admin/security", { method: "GET", token }),

  // invitations
  getInviteOnlyMode: (token: string) =>
    request<{ enabled: boolean }>("/admin/invitations/invite-only-mode", {
      method: "GET",
      token,
    }),

  setInviteOnlyMode: (token: string, enabled: boolean, reason: string) =>
    request<void>("/admin/invitations/invite-only-mode", { token, body: { enabled, reason } }),

  getInvitationStats: (token: string) =>
    request<InvitationStats>("/admin/invitations/stats", { method: "GET", token }),

  // audit log
  listAuditLog: (
    token: string,
    params: {
      actor_id?: string;
      action?: string;
      target_type?: string;
      target_id?: string;
      limit?: number;
      offset?: number;
    } = {}
  ) => request<AuditLogEntry[]>("/admin/audit-log", { method: "GET", token, params }),

  // system config
  listSystemConfig: (token: string) =>
    request<SystemConfigEntry[]>("/admin/system-config", { method: "GET", token }),

  setSystemConfig: (
    token: string,
    key: string,
    value: Record<string, unknown>,
    reason: string
  ) =>
    request<SystemConfigEntry>(`/admin/system-config/${key}`, {
      method: "PUT",
      token,
      body: { value, reason },
    }),
};

export const kycApi = {
  listQueue: (token: string) =>
    request<UserSummary[]>("/admin/kyc/queue", { method: "GET", token }),

  getDetail: (token: string, userId: string, reason: string) =>
    request<KycDetail>(`/admin/kyc/${userId}`, { method: "GET", token, params: { reason } }),

  approve: (token: string, userId: string, reason: string) =>
    request<UserSummary>(`/admin/kyc/${userId}/approve`, { token, body: { reason } }),

  reject: (token: string, userId: string, reason: string) =>
    request<UserSummary>(`/admin/kyc/${userId}/reject`, { token, body: { reason } }),

  requestRecapture: (token: string, userId: string, reason: string) =>
    request<UserSummary>(`/admin/kyc/${userId}/request-recapture`, { token, body: { reason } }),
};
