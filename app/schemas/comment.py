from datetime import datetime
from uuid import UUID

from sqlalchemy import Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.services.db import Base


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    comment_id: Mapped[UUID] = mapped_column(unique=True)
    post_id: Mapped[UUID] = mapped_column(index=True)  # posts.post_id
    parent_comment_id: Mapped[UUID | None] = mapped_column(
        nullable=True, index=True
    )  # comments.comment_id, set for replies
    author_id: Mapped[UUID] = mapped_column(index=True)
    reply_to_id: Mapped[UUID | None] = mapped_column(
        nullable=True
    )  # user being replied to
    found_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime | None]
    content: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[list] = mapped_column(JSONB, default=list)
    likes_count: Mapped[int] = mapped_column(default=0)
    replies_count: Mapped[int] = mapped_column(default=0)
    exists: Mapped[bool] = mapped_column(default=True)
