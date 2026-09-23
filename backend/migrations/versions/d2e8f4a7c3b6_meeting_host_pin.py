"""meeting host pin

Revision ID: d2e8f4a7c3b6
Revises: a8e3f6c1d9b4
Create Date: 2026-09-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2e8f4a7c3b6"
down_revision: str | Sequence[str] | None = "a8e3f6c1d9b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("host_pin_hash", sa.String(length=256), nullable=True))


def downgrade() -> None:
    op.drop_column("meetings", "host_pin_hash")
