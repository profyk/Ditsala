"""enable pgcrypto extension

Revision ID: 9ef27ff365ca
Revises: 
Create Date: 2026-09-15 00:43:47.149225

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9ef27ff365ca'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """
    pgcrypto provides gen_random_uuid(), the default for every table's
    primary key per docs/DITSALA_MASTER_SPEC.md §4. Every later migration
    depends on this being enabled first.
    """
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
