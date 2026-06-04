"""add count suffix

Revision ID: d884d322e1c4
Revises: 3c7ab41cef34
Create Date: 2026-06-04 20:29:17.416843

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d884d322e1c4"
down_revision: Union[str, Sequence[str], None] = "3c7ab41cef34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.alter_column("users", "followers", new_column_name="followers_count")
    op.alter_column("users", "following", new_column_name="following_count")
    op.alter_column("users", "posts", new_column_name="posts_count")


def downgrade():
    op.alter_column("users", "followers_count", new_column_name="followers")
    op.alter_column("users", "following_count", new_column_name="following")
    op.alter_column("users", "posts_count", new_column_name="posts")
