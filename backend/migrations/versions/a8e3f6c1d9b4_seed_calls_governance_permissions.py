"""seed calls_governance:view/:action permissions

Revision ID: a8e3f6c1d9b4
Revises: f1a9c4e7b2d5
Create Date: 2026-09-23 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8e3f6c1d9b4"
down_revision: str | Sequence[str] | None = "f1a9c4e7b2d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same rationale as c7d3a5f8e2b1's meetings_governance seed: force-ending
# an abusive live call is a real operational-control action that fits
# trust_safety's existing reports/moderation mandate, not just super_admin.
_PERMISSIONS = ("calls_governance:view", "calls_governance:action")
_ROLES = ("super_admin", "trust_safety")


def upgrade() -> None:
    for name in _PERMISSIONS:
        op.execute(
            f"""
            INSERT INTO admin_permissions (id, name)
            VALUES (gen_random_uuid(), '{name}')
            ON CONFLICT (name) DO NOTHING
            """
        )
        for role in _ROLES:
            op.execute(
                f"""
                INSERT INTO admin_role_permissions (id, role_id, permission_id)
                SELECT gen_random_uuid(), r.id, p.id
                FROM admin_roles r, admin_permissions p
                WHERE r.name = '{role}' AND p.name = '{name}'
                ON CONFLICT (role_id, permission_id) DO NOTHING
                """
            )


def downgrade() -> None:
    names_sql = ", ".join(f"'{n}'" for n in _PERMISSIONS)
    op.execute(
        "DELETE FROM admin_role_permissions WHERE permission_id IN "
        f"(SELECT id FROM admin_permissions WHERE name IN ({names_sql}))"
    )
    op.execute(f"DELETE FROM admin_permissions WHERE name IN ({names_sql})")
