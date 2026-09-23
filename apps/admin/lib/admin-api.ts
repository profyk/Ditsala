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

// --- admin user management (super_admin only) ---

export interface AdminUserSummary {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
  mfa_enrolled: boolean;
  last_login_at: string | null;
  created_at: string;
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

  // admin user management
  listAdmins: (token: string) =>
    request<AdminUserSummary[]>("/admin/admin-users", { method: "GET", token }),

  createAdmin: (token: string, email: string, password: string, role: string) =>
    request<AdminUserSummary>("/admin/admin-users", { token, body: { email, password, role } }),

  setAdminActive: (token: string, adminId: string, isActive: boolean) =>
    request<AdminUserSummary>(`/admin/admin-users/${adminId}/active`, {
      token,
      body: { is_active: isActive },
    }),

  changeAdminRole: (token: string, adminId: string, role: string) =>
    request<AdminUserSummary>(`/admin/admin-users/${adminId}/role`, {
      token,
      body: { role },
    }),

  // data subject requests (§34.4)
  listDataSubjectRequests: (token: string, status = "pending") =>
    request<DataSubjectRequest[]>("/admin/data-subject-requests", {
      method: "GET",
      token,
      params: { status },
    }),

  markDataSubjectRequestInProgress: (token: string, requestId: string) =>
    request<DataSubjectRequest>(`/admin/data-subject-requests/${requestId}/in-progress`, {
      token,
    }),

  completeDataSubjectRequest: (token: string, requestId: string, resolutionNotes: string) =>
    request<DataSubjectRequest>(`/admin/data-subject-requests/${requestId}/complete`, {
      token,
      body: { resolution_notes: resolutionNotes },
    }),

  rejectDataSubjectRequest: (token: string, requestId: string, resolutionNotes: string) =>
    request<DataSubjectRequest>(`/admin/data-subject-requests/${requestId}/reject`, {
      token,
      body: { resolution_notes: resolutionNotes },
    }),
};

// --- billing / plans (§27-29) ---

export interface Plan {
  id: string;
  code: string;
  product: "free" | "vip" | "business" | "conference";
  name: string;
  status: "active" | "archived";
}

export interface PlanPrice {
  id: string;
  currency: string;
  amount_cents: number;
  billing_interval: "month" | "year" | "one_time";
  status: "active" | "archived";
  effective_from: string;
  effective_until: string | null;
}

export interface Entitlement {
  key: string;
  value: unknown;
}

export interface DataSubjectRequest {
  id: string;
  user_id: string;
  request_type: string;
  status: string;
  details: string | null;
  due_at: string;
  resolved_at: string | null;
  resolution_notes: string | null;
  created_at: string;
}

export const billingApi = {
  listPlans: (token: string) => request<Plan[]>("/admin/billing/plans", { method: "GET", token }),

  createPlan: (token: string, code: string, product: Plan["product"], name: string) =>
    request<Plan>("/admin/billing/plans", { token, body: { code, product, name } }),

  setPlanStatus: (token: string, planId: string, status: Plan["status"], reason: string) =>
    request<Plan>(`/admin/billing/plans/${planId}/status`, {
      method: "PUT",
      token,
      body: { status, reason },
    }),

  listPlanPrices: (token: string, planId: string) =>
    request<PlanPrice[]>(`/admin/billing/plans/${planId}/prices`, { method: "GET", token }),

  setPlanPrice: (
    token: string,
    planId: string,
    price: { currency: string; amount_cents: number; billing_interval: PlanPrice["billing_interval"]; reason: string }
  ) => request<PlanPrice>(`/admin/billing/plans/${planId}/prices`, { token, body: price }),

  listEntitlements: (token: string, planId: string) =>
    request<Entitlement[]>(`/admin/billing/plans/${planId}/entitlements`, {
      method: "GET",
      token,
    }),

  setEntitlement: (token: string, planId: string, key: string, value: unknown, reason: string) =>
    request<Entitlement>(`/admin/billing/plans/${planId}/entitlements`, {
      method: "PUT",
      token,
      body: { key, value, reason },
    }),

  // Conference Room plan assignment — a separate axis from the plan/price/
  // entitlement CRUD above (see backend app/domain/billing/conference_plans.py):
  // this assigns one *user* to one of the four seeded conference_* plan
  // codes, since there's no self-serve payment flow for them yet.
  setUserConferencePlan: (token: string, userId: string, planCode: string, reason: string) =>
    request<{ user_id: string; conference_plan_code: string }>(
      `/admin/billing/users/${userId}/conference-plan`,
      { method: "PUT", token, body: { plan_code: planCode, reason } }
    ),
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

// --- meetings governance (live/scheduled meetings, platform-wide) ---

export interface AdminMeeting {
  id: string;
  host_user_id: string;
  title: string;
  meeting_type: string;
  status: string;
  scheduled_start_at: string | null;
  scheduled_duration_minutes: number | null;
  actual_start_at: string | null;
  duration_extended_minutes: number;
  max_participants: number | null;
  waiting_room_enabled: boolean;
  locked_at: string | null;
  active_participant_count: number;
}

export interface AdminMeetingParticipant {
  id: string;
  user_id: string | null;
  guest_display_name: string | null;
  role: string;
  admission_status: string;
  joined_at: string | null;
  left_at: string | null;
}

export interface AdminMeetingAnalytics {
  meeting_id: string;
  as_of: string;
  total_participant_rows: number;
  unique_attendees: number;
  guest_attendees: number;
  total_attendance_seconds: number;
  average_attendance_seconds: number;
  peak_concurrent_attendees: number;
  attendees: {
    participant_id: string;
    display_name: string;
    role: string;
    is_guest: boolean;
    joined_at: string | null;
    left_at: string | null;
    attended_seconds: number;
  }[];
}

export const meetingsGovernanceApi = {
  list: (token: string) =>
    request<AdminMeeting[]>("/admin/meetings", { method: "GET", token }),

  listParticipants: (token: string, meetingId: string) =>
    request<AdminMeetingParticipant[]>(`/admin/meetings/${meetingId}/participants`, {
      method: "GET",
      token,
    }),

  getAnalytics: (token: string, meetingId: string) =>
    request<AdminMeetingAnalytics>(`/admin/meetings/${meetingId}/analytics`, {
      method: "GET",
      token,
    }),

  extend: (token: string, meetingId: string, additionalMinutes: number, reason: string) =>
    request<AdminMeeting>(`/admin/meetings/${meetingId}/extend`, {
      token,
      body: { additional_minutes: additionalMinutes, reason },
    }),

  end: (token: string, meetingId: string, reason: string) =>
    request<AdminMeeting>(`/admin/meetings/${meetingId}/end`, { token, body: { reason } }),
};

// --- revenue / subscriptions overview ---

export interface PlanRevenueLine {
  plan_id: string;
  plan_code: string;
  plan_name: string;
  product: string;
  subscriber_count: number;
  price_amount_cents: number | null;
  price_currency: string | null;
  estimated_monthly_cents: number;
}

export interface RevenueOverview {
  lines: PlanRevenueLine[];
  total_estimated_monthly_cents: number;
  total_subscribers: number;
}

export const revenueApi = {
  getOverview: (token: string) =>
    request<RevenueOverview>("/admin/revenue", { method: "GET", token }),
};
