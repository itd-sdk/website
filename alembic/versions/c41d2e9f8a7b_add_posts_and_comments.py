"""add posts and comments

Revision ID: c41d2e9f8a7b
Revises: 57857fef8adc
Create Date: 2026-10-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c41d2e9f8a7b"
down_revision: Union[str, Sequence[str], None] = "57857fef8adc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("posts_updated_at", sa.DateTime(), nullable=True))
    op.create_index("ix_users_posts_updated_at", "users", ["posts_updated_at"])

    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("edited_at", sa.DateTime(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("spans", postgresql.JSONB(), nullable=False),
        sa.Column("attachments", postgresql.JSONB(), nullable=False),
        sa.Column("likes_count", sa.Integer(), nullable=False),
        sa.Column("comments_count", sa.Integer(), nullable=False),
        sa.Column("views_count", sa.Integer(), nullable=False),
        sa.Column("poll_question", sa.Text(), nullable=True),
        sa.Column("poll_options", postgresql.JSONB(), nullable=True),
        sa.Column("poll_multiple", sa.Boolean(), nullable=True),
        sa.Column("dominant", sa.String(), nullable=True),
        sa.Column("original_post_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("wall_recipient_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("post_id"),
    )
    op.create_index("ix_posts_id", "posts", ["id"])
    op.create_index("ix_posts_author_id", "posts", ["author_id"])
    op.create_index("ix_posts_original_post_id", "posts", ["original_post_id"])
    op.create_index("ix_posts_wall_recipient_id", "posts", ["wall_recipient_id"])

    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("comment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("attachments", postgresql.JSONB(), nullable=False),
        sa.Column("likes_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("comment_id"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.post_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["comments.comment_id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_comments_id", "comments", ["id"])
    op.create_index("ix_comments_post_id", "comments", ["post_id"])
    op.create_index("ix_comments_parent_id", "comments", ["parent_id"])
    op.create_index("ix_comments_author_id", "comments", ["author_id"])


def downgrade() -> None:
    op.drop_index("ix_comments_author_id", table_name="comments")
    op.drop_index("ix_comments_parent_id", table_name="comments")
    op.drop_index("ix_comments_post_id", table_name="comments")
    op.drop_index("ix_comments_id", table_name="comments")
    op.drop_table("comments")

    op.drop_index("ix_posts_wall_recipient_id", table_name="posts")
    op.drop_index("ix_posts_original_post_id", table_name="posts")
    op.drop_index("ix_posts_author_id", table_name="posts")
    op.drop_index("ix_posts_id", table_name="posts")
    op.drop_table("posts")

    op.drop_index("ix_users_posts_updated_at", table_name="users")
    op.drop_column("users", "posts_updated_at")
