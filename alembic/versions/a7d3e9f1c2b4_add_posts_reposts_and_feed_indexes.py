"""add posts reposts_count and feed indexes

Revision ID: a7d3e9f1c2b4
Revises: 36c1d99b27dd
Create Date: 2026-10-17

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d3e9f1c2b4"
down_revision: Union[str, Sequence[str], None] = "36c1d99b27dd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXED = (
    "created_at",
    "found_at",
    "likes_count",
    "comments_count",
    "reposts_count",
    "views_count",
)


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column("reposts_count", sa.Integer(), server_default="0", nullable=False),
    )
    for column in INDEXED:
        op.create_index(f"ix_posts_{column}", "posts", [column])


def downgrade() -> None:
    for column in INDEXED:
        op.drop_index(f"ix_posts_{column}", table_name="posts")
    op.drop_column("posts", "reposts_count")
