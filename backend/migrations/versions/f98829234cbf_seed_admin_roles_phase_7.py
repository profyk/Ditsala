"""seed admin roles phase 7

Revision ID: f98829234cbf
Revises: ac7e962fd9db
Create Date: 2026-09-16 01:57:04.117741

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f98829234cbf'
down_revision: str | Sequence[str] | None = 'ac7e962fd9db'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# docs/DITSALA_MASTER_SPEC.md §29 launch role set. The role -> permission
# mapping itself lives in app/domain/admin/rbac.py as a Python constant,
# not in admin_role_permissions (see that module's docstring for why) —
# this migration only needs admin_roles to exist so admin_users.role_id
# has something real to point at.
_ROLE_NAMES = ("super_admin", "kyc_reviewer", "trust_safety", "support_readonly")


def upgrade() -> None:
    for name in _ROLE_NAMES:
        op.execute(
            f"""
            INSERT INTO admin_roles (id, name)
            VALUES (gen_random_uuid(), '{name}')
            ON CONFLICT (name) DO NOTHING
            """
        )


def downgrade() -> None:
    names = ", ".join(f"'{name}'" for name in _ROLE_NAMES)
    op.execute(f"DELETE FROM admin_roles WHERE name IN ({names})")
