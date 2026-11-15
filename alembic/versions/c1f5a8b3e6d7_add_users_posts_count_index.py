"""add users posts_count index

Revision ID: c1f5a8b3e6d7
Revises: b8e4f0a2d3c5
Create Date: 2026-10-17

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1f5a8b3e6d7"
down_revision: Union[str, Sequence[str], None] = "b8e4f0a2d3c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # posts tasks pick the user with the most posts first
    op.create_index("ix_users_posts_count", "users", ["posts_count"])


def downgrade() -> None:
    op.drop_index("ix_users_posts_count", table_name="users")
