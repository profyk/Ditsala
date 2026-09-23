"""seed meetings_governance:view/:action and revenue:view permissions

Revision ID: c7d3a5f8e2b1
Revises: b4f7c1a9e6d2
Create Date: 2026-09-23 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d3a5f8e2b1"
down_revision: str | Sequence[str] | None = "b4f7c1a9e6d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Meeting governance (viewing every live/scheduled Conference Room
# meeting platform-wide, extending or ending one that isn't the admin's
# own) is a real operational-control action — granted to super_admin and
# trust_safety (the role that already handles reports/moderation; ending
# an abusive live meeting fits that same mandate), not the other two
# launch roles. Revenue is financial data — super_admin only, same
# "touches real money" precedent d3b8a1e4f7c9 already established for
# billing_plans.
_GOVERNANCE_PERMISSIONS = ("meetings_governance:view", "meetings_governance:action")
_GOVERNANCE_ROLES = ("super_admin", "trust_safety")
_REVENUE_PERMISSIONS = ("revenue:view",)
_REVENUE_ROLES = ("super_admin",)


def _seed(permissions: tuple[str, ...], roles: tuple[str, ...]) -> None:
    for name in permissions:
        op.execute(
            f"""
            INSERT INTO admin_permissions (id, name)
            VALUES (gen_random_uuid(), '{name}')
            ON CONFLICT (name) DO NOTHING
            """
        )
        for role in roles:
            op.execute(
                f"""
                INSERT INTO admin_role_permissions (id, role_id, permission_id)
                SELECT gen_random_uuid(), r.id, p.id
                FROM admin_roles r, admin_permissions p
                WHERE r.name = '{role}' AND p.name = '{name}'
                ON CONFLICT (role_id, permission_id) DO NOTHING
                """
            )


def upgrade() -> None:
    _seed(_GOVERNANCE_PERMISSIONS, _GOVERNANCE_ROLES)
    _seed(_REVENUE_PERMISSIONS, _REVENUE_ROLES)


def downgrade() -> None:
    all_names = _GOVERNANCE_PERMISSIONS + _REVENUE_PERMISSIONS
    names_sql = ", ".join(f"'{n}'" for n in all_names)
    op.execute(
        "DELETE FROM admin_role_permissions WHERE permission_id IN "
        f"(SELECT id FROM admin_permissions WHERE name IN ({names_sql}))"
    )
    op.execute(f"DELETE FROM admin_permissions WHERE name IN ({names_sql})")
