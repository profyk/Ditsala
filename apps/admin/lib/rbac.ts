/**
 * Mirrors backend/app/domain/admin/rbac.py — client-side only, for
 * showing/hiding nav items and page sections. The backend re-checks
 * every one of these on every request (`require_permission`); this
 * exists purely so a `kyc_reviewer` doesn't see a "Reports" link that
 * would just 403 if clicked, not as a security boundary of its own.
 */

export type Permission =
  | "dashboard:view"
  | "kyc:queue:view"
  | "kyc:queue:action"
  | "users:view"
  | "users:action"
  | "reports:view"
  | "reports:action"
  | "security:view"
  | "invitations:view"
  | "invitations:action"
  | "audit:view"
  | "system_config:view"
  | "system_config:action"
  | "data_subject_requests:view"
  | "data_subject_requests:action"
  | "admin_users:view"
  | "admin_users:action"
  | "billing_plans:view"
  | "billing_plans:action"
  | "meetings_governance:view"
  | "meetings_governance:action"
  | "revenue:view";

const ALL_PERMISSIONS: Permission[] = [
  "dashboard:view",
  "kyc:queue:view",
  "kyc:queue:action",
  "users:view",
  "users:action",
  "reports:view",
  "reports:action",
  "security:view",
  "invitations:view",
  "invitations:action",
  "audit:view",
  "system_config:view",
  "system_config:action",
  "data_subject_requests:view",
  "data_subject_requests:action",
  "admin_users:view",
  "admin_users:action",
  "billing_plans:view",
  "billing_plans:action",
  "meetings_governance:view",
  "meetings_governance:action",
  "revenue:view",
];

export const ROLE_PERMISSIONS: Record<string, Permission[]> = {
  super_admin: ALL_PERMISSIONS,
  kyc_reviewer: ["dashboard:view", "kyc:queue:view", "kyc:queue:action"],
  trust_safety: [
    "dashboard:view",
    "reports:view",
    "reports:action",
    "users:view",
    "users:action",
    "security:view",
    "data_subject_requests:view",
    "data_subject_requests:action",
    "meetings_governance:view",
    "meetings_governance:action",
  ],
  support_readonly: ["dashboard:view", "users:view"],
};

export function roleHasPermission(role: string, permission: Permission): boolean {
  return ROLE_PERMISSIONS[role]?.includes(permission) ?? false;
}
