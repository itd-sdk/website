"""add user snapshots

Revision ID: e5a1c7d0b9f2
Revises: c41d2e9f8a7b
Create Date: 2026-10-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5a1c7d0b9f2"
down_revision: Union[str, Sequence[str], None] = "c41d2e9f8a7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("followers_count", sa.Integer(), nullable=False),
        sa.Column("following_count", sa.Integer(), nullable=False),
        sa.Column("posts_count", sa.Integer(), nullable=False),
        sa.Column("exists", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "recorded_at"),
    )
    op.create_index("ix_user_snapshots_user_id", "user_snapshots", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_snapshots_user_id", table_name="user_snapshots")
    op.drop_table("user_snapshots")
