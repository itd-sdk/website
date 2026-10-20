"""add deleted_at to users, posts and comments

Revision ID: a4c9e2f7b1d3
Revises: f6a2d8c4b0e9
Create Date: 2026-10-18

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4c9e2f7b1d3"
down_revision: Union[str, Sequence[str], None] = "f6a2d8c4b0e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("users", "posts", "comments")


def upgrade() -> None:
    # rows deleted before this column existed keep it empty, the time is unknown
    for table in TABLES:
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "deleted_at")
