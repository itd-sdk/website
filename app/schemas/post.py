from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.services.db import Base

if TYPE_CHECKING:
    from app.schemas.comment import Comment


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    post_id: Mapped[UUID] = mapped_column(unique=True)
    author_id: Mapped[UUID] = mapped_column(index=True)
    created_at: Mapped[datetime | None]
    edited_at: Mapped[datetime | None]
    content: Mapped[str] = mapped_column(Text, default="")
    spans: Mapped[list] = mapped_column(JSONB, default=list)
    attachments: Mapped[list] = mapped_column(JSONB, default=list)
    likes_count: Mapped[int] = mapped_column(default=0)
    comments_count: Mapped[int] = mapped_column(default=0)
    views_count: Mapped[int] = mapped_column(default=0)
    poll_question: Mapped[str | None] = mapped_column(Text)
    poll_options: Mapped[list | None] = mapped_column(JSONB)
    poll_multiple: Mapped[bool | None]
    dominant: Mapped[str | None]  # dominant emoji
    original_post_id: Mapped[UUID | None] = mapped_column(
        index=True
    )  # posts.post_id, for reposts
    wall_recipient_id: Mapped[UUID | None] = mapped_column(index=True)

    # top-level comments only, replies are available via Comment.replies
    comments: Mapped[list["Comment"]] = relationship(
        primaryjoin="and_(Post.post_id == Comment.post_id, Comment.parent_id.is_(None))",
        order_by="Comment.created_at",
        viewonly=True
    )
