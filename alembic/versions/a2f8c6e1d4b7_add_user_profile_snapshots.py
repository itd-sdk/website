"""add user profile snapshots

Revision ID: a2f8c6e1d4b7
Revises: e5a1c7d0b9f2
Create Date: 2026-11-26

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2f8c6e1d4b7"
down_revision: Union[str, Sequence[str], None] = "e5a1c7d0b9f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_profile_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "recorded_at"),
    )
    op.create_index(
        "ix_user_profile_snapshots_user_id", "user_profile_snapshots", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_profile_snapshots_user_id", table_name="user_profile_snapshots"
    )
    op.drop_table("user_profile_snapshots")
