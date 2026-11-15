"""add comments.exists and users username index

Revision ID: f6a2d8c4b0e9
Revises: e3b7c9d1f4a6
Create Date: 2026-10-18

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a2d8c4b0e9"
down_revision: Union[str, Sequence[str], None] = "e3b7c9d1f4a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comments",
        sa.Column("exists", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_column("comments", "exists")
