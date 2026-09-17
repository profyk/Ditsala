"""seed admin_users:view / admin_users:action permissions

Revision ID: c1c1b8e6f0a2
Revises: 9ed2db722f97
Create Date: 2026-09-17 21:25:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1c1b8e6f0a2"
down_revision: str | Sequence[str] | None = "9ed2db722f97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The in-panel "manage admins" screen — granted to super_admin only, not
# the other three launch roles (mirrors 7a3f2e9c1b4d's seeding pattern).
_PERMISSIONS = ("admin_users:view", "admin_users:action")


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
               "(SELECT id FROM admin_permissions WHERE name IN ('admin_users:view', 'admin_users:action'))")
    op.execute("DELETE FROM admin_permissions WHERE name IN ('admin_users:view', 'admin_users:action')")
