"""add data_subject_requests.export_storage_key

Revision ID: f1a9c4e7b2d5
Revises: c7d3a5f8e2b1
Create Date: 2026-09-23 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a9c4e7b2d5"
down_revision: str | Sequence[str] | None = "c7d3a5f8e2b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "data_subject_requests",
        sa.Column("export_storage_key", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("data_subject_requests", "export_storage_key")
