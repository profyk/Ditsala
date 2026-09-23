"""
Admin RBAC — docs/DITSALA_MASTER_SPEC.md §29. `Permission` is the
canonical set of permission names — every route's `require_permission()`
call references one of these. The role -> permission mapping itself is
DB-driven (`admin_role_permissions`, checked via
`AdminRoleRepository.role_has_permission`) as of ADR 0011 — this module
no longer hardcodes it; migration `7a3f2e9c1b4d` seeds the launch set's
initial mapping as a one-time data snapshot, not a live source of truth.
"""

from enum import StrEnum


class Permission(StrEnum):
    DASHBOARD_VIEW = "dashboard:view"
    KYC_QUEUE_VIEW = "kyc:queue:view"
    KYC_QUEUE_ACTION = "kyc:queue:action"
    USERS_VIEW = "users:view"
    USERS_ACTION = "users:action"
    REPORTS_VIEW = "reports:view"
    REPORTS_ACTION = "reports:action"
    SECURITY_VIEW = "security:view"
    INVITATIONS_VIEW = "invitations:view"
    INVITATIONS_ACTION = "invitations:action"
    AUDIT_VIEW = "audit:view"
    SYSTEM_CONFIG_VIEW = "system_config:view"
    SYSTEM_CONFIG_ACTION = "system_config:action"
    DATA_SUBJECT_REQUESTS_VIEW = "data_subject_requests:view"
    DATA_SUBJECT_REQUESTS_ACTION = "data_subject_requests:action"
    ADMIN_USERS_VIEW = "admin_users:view"
    ADMIN_USERS_ACTION = "admin_users:action"
    BILLING_PLANS_VIEW = "billing_plans:view"
    BILLING_PLANS_ACTION = "billing_plans:action"
    MEETINGS_GOVERNANCE_VIEW = "meetings_governance:view"
    MEETINGS_GOVERNANCE_ACTION = "meetings_governance:action"
    REVENUE_VIEW = "revenue:view"
    CALLS_GOVERNANCE_VIEW = "calls_governance:view"
    CALLS_GOVERNANCE_ACTION = "calls_governance:action"
