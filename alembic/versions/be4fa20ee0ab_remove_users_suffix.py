"""remove users suffix

Revision ID: be4fa20ee0ab
Revises: d884d322e1c4
Create Date: 2026-06-04 20:32:34.107795

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "be4fa20ee0ab"
down_revision: Union[str, Sequence[str], None] = "d884d322e1c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.alter_column("users", "followed_by_users", new_column_name="followers")
    op.alter_column("users", "following_users", new_column_name="following")


def downgrade():
    op.alter_column("users", "followers", new_column_name="followed_by_users")
    op.alter_column("users", "following", new_column_name="following_users")
