"""store empty red pens and correctors as lists

36c1d99b27dd added the columns with '{}' as the default, posts that existed
then got an empty object instead of an empty list.

Revision ID: b7d1f3a9c5e2
Revises: a4c9e2f7b1d3
Create Date: 2026-10-18

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d1f3a9c5e2"
down_revision: Union[str, Sequence[str], None] = "a4c9e2f7b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ("red_pens", "correctors")


def upgrade() -> None:
    for column in COLUMNS:
        op.execute(f"update posts set {column} = '[]' where {column} = '{{}}'")
        op.alter_column("posts", column, server_default="[]")


def downgrade() -> None:
    # the data stays as lists, only the default goes back
    for column in COLUMNS:
        op.alter_column("posts", column, server_default="{}")
