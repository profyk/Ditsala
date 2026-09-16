"""
Admin RBAC — docs/DITSALA_MASTER_SPEC.md §29. The launch role set is
fixed here as a Python mapping rather than driven by the
`admin_role_permissions` join table Phase 1 already modeled: §29 does
say roles are "extensible via admin_roles/admin_permissions," which
would need that table populated and a management UI over it, but no
such UI exists yet and the 4 launch roles are fixed by spec text, not by
what an admin configures at runtime. Tracked as a simplification in
docs/SECURITY_GAPS.md, not a silent gap — `admin_roles.name` (a real
column, real FK target from `admin_users.role_id`) is still the source
of truth for *which* role an admin has; only the role -> permission
mapping is hardcoded rather than DB-driven.
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


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "super_admin": frozenset(Permission),
    "kyc_reviewer": frozenset(
        {Permission.DASHBOARD_VIEW, Permission.KYC_QUEUE_VIEW, Permission.KYC_QUEUE_ACTION}
    ),
    "trust_safety": frozenset(
        {
            Permission.DASHBOARD_VIEW,
            Permission.REPORTS_VIEW,
            Permission.REPORTS_ACTION,
            Permission.USERS_VIEW,
            Permission.USERS_ACTION,
            Permission.SECURITY_VIEW,
        }
    ),
    "support_readonly": frozenset({Permission.DASHBOARD_VIEW, Permission.USERS_VIEW}),
}


def role_has_permission(role_name: str, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role_name, frozenset())
