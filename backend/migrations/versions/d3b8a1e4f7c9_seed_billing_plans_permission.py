"""seed billing_plans:view / billing_plans:action permissions

Revision ID: d3b8a1e4f7c9
Revises: a0f6c64d7375
Create Date: 2026-09-21 00:05:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3b8a1e4f7c9"
down_revision: str | Sequence[str] | None = "a0f6c64d7375"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Plan/pricing management touches real money — super_admin only, not the
# other three launch roles (mirrors c1c1b8e6f0a2's seeding pattern).
_PERMISSIONS = ("billing_plans:view", "billing_plans:action")


def upgrade() -> None:
    for name in _PERMISSIONS:
        op.execute(
            f"""
            INSERT INTO admin_permissions (id, name)
            VALUES (gen_random_uuid(), '{name}')
            ON CONFLICT (name) DO NOTHING
            """
        )
        op.execute(
            f"""
            INSERT INTO admin_role_permissions (id, role_id, permission_id)
            SELECT gen_random_uuid(), r.id, p.id
            FROM admin_roles r, admin_permissions p
            WHERE r.name = 'super_admin' AND p.name = '{name}'
            ON CONFLICT (role_id, permission_id) DO NOTHING
            """
        )


def downgrade() -> None:
    op.execute("DELETE FROM admin_role_permissions WHERE permission_id IN "
               "(SELECT id FROM admin_permissions WHERE name IN ('billing_plans:view', 'billing_plans:action'))")
    op.execute("DELETE FROM admin_permissions WHERE name IN ('billing_plans:view', 'billing_plans:action')")
