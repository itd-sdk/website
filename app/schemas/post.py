from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ARRAY, Text, func, true
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
    created_at: Mapped[datetime | None] = mapped_column(index=True)
    edited_at: Mapped[datetime | None]
    found_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    content: Mapped[str] = mapped_column(Text, default="")
    red_pens: Mapped[list] = mapped_column(JSONB, default=list)
    red_pen_authors: Mapped[list[str]] = mapped_column(ARRAY(Text))
    correctors: Mapped[list] = mapped_column(JSONB, default=list)
    spans: Mapped[list] = mapped_column(JSONB, default=list)
    attachments: Mapped[list] = mapped_column(JSONB, default=list)
    # indexed for the popular feed sorts
    likes_count: Mapped[int] = mapped_column(default=0, index=True)
    comments_count: Mapped[int] = mapped_column(default=0, index=True)
    reposts_count: Mapped[int] = mapped_column(default=0, index=True)
    views_count: Mapped[int] = mapped_column(default=0, index=True)
    poll_question: Mapped[str | None] = mapped_column(Text)
    poll_options: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    poll_multiple: Mapped[bool | None]
    dominant: Mapped[str | None]  # dominant emoji
    original_post_id: Mapped[UUID | None] = mapped_column(
        index=True
    )  # posts.post_id, for reposts
    wall_recipient_id: Mapped[UUID | None] = mapped_column(index=True)
    exists: Mapped[bool] = mapped_column(default=True, server_default=true())

    # top-level comments only, replies are available via Comment.replies
    comments: Mapped[list["Comment"]] = relationship(
        primaryjoin="and_(Post.post_id == Comment.post_id, Comment.parent_id.is_(None))",
        order_by="Comment.created_at",
        viewonly=True
    )
