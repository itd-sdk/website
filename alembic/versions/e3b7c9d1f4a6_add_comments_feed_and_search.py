"""add comments feed columns and content search indexes

Revision ID: e3b7c9d1f4a6
Revises: c1f5a8b3e6d7
Create Date: 2026-10-18

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3b7c9d1f4a6"
down_revision: Union[str, Sequence[str], None] = "c1f5a8b3e6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COMMENT_INDEXED = ("created_at", "found_at", "likes_count", "replies_count")


def upgrade() -> None:
    op.add_column(
        "comments",
        sa.Column(
            "found_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.add_column(
        "comments",
        sa.Column("replies_count", sa.Integer(), server_default="0", nullable=False),
    )
    # stored replies are all replies the scraper saw
    op.execute(
        """
        update comments c set replies_count = r.count
        from (
            select parent_id, count(*) as count from comments
            where parent_id is not null group by parent_id
        ) r
        where r.parent_id = c.comment_id
        """
    )
    for column in COMMENT_INDEXED:
        op.create_index(f"ix_comments_{column}", "comments", [column])

    # trigram indexes make "content ilike '%text%'" usable on big tables
    op.execute("create extension if not exists pg_trgm")
    op.execute(
        "create index ix_posts_content_trgm on posts using gin (content gin_trgm_ops)"
    )
    op.execute(
        "create index ix_comments_content_trgm on comments "
        "using gin (content gin_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_comments_content_trgm", table_name="comments")
    op.drop_index("ix_posts_content_trgm", table_name="posts")
    for column in COMMENT_INDEXED:
        op.drop_index(f"ix_comments_{column}", table_name="comments")
    op.drop_column("comments", "replies_count")
    op.drop_column("comments", "found_at")
