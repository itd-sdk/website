"""add posts exists

Revision ID: b8e4f0a2d3c5
Revises: a7d3e9f1c2b4
Create Date: 2026-10-17

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8e4f0a2d3c5"
down_revision: Union[str, Sequence[str], None] = "a7d3e9f1c2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column("exists", sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("posts", "exists")
