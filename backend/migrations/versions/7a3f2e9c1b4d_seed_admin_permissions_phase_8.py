"""seed admin permissions and role-permission mapping phase 8

Revision ID: 7a3f2e9c1b4d
Revises: 43bc6ded0da2
Create Date: 2026-09-16 12:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a3f2e9c1b4d"
down_revision: str | Sequence[str] | None = "43bc6ded0da2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A frozen snapshot of app/domain/admin/rbac.py's Permission enum and
# ROLE_PERMISSIONS mapping at the moment RBAC became DB-driven (see ADR
# 0011) — not a live import, since a migration must keep producing the
# same result even after that module changes further. Post-launch
# permission changes go through the admin RBAC management screen (once
# built) updating these tables directly, not a new migration per change.
_PERMISSIONS = (
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
)

_ROLE_PERMISSIONS = {
    "super_admin": _PERMISSIONS,  # every permission
    "kyc_reviewer": ("dashboard:view", "kyc:queue:view", "kyc:queue:action"),
    "trust_safety": (
        "dashboard:view",
        "reports:view",
        "reports:action",
        "users:view",
        "users:action",
        "security:view",
        "data_subject_requests:view",
        "data_subject_requests:action",
    ),
    "support_readonly": ("dashboard:view", "users:view"),
}


def upgrade() -> None:
    for name in _PERMISSIONS:
        op.execute(
            f"""
            INSERT INTO admin_permissions (id, name)
            VALUES (gen_random_uuid(), '{name}')
            ON CONFLICT (name) DO NOTHING
            """
        )

    for role_name, permissions in _ROLE_PERMISSIONS.items():
        for permission_name in permissions:
            op.execute(
                f"""
                INSERT INTO admin_role_permissions (id, role_id, permission_id)
                SELECT gen_random_uuid(), r.id, p.id
                FROM admin_roles r, admin_permissions p
                WHERE r.name = '{role_name}' AND p.name = '{permission_name}'
                ON CONFLICT (role_id, permission_id) DO NOTHING
                """
            )


def downgrade() -> None:
    op.execute("DELETE FROM admin_role_permissions")
    names = ", ".join(f"'{name}'" for name in _PERMISSIONS)
    op.execute(f"DELETE FROM admin_permissions WHERE name IN ({names})")
