from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Text, func, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.services.db import Base


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (
        Index(
            "ix_comments_content_trgm",
            "content",
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"}
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    comment_id: Mapped[UUID] = mapped_column(unique=True)
    post_id: Mapped[UUID] = mapped_column(
        ForeignKey("posts.post_id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("comments.comment_id", ondelete="CASCADE"), index=True
    )  # set for replies
    author_id: Mapped[UUID] = mapped_column(index=True)
    reply_to_id: Mapped[UUID | None] = mapped_column(
        index=True
    )  # user being replied to
    created_at: Mapped[datetime | None] = mapped_column(index=True)
    found_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[list] = mapped_column(JSONB, default=list)
    likes_count: Mapped[int] = mapped_column(default=0, index=True)
    replies_count: Mapped[int] = mapped_column(default=0, index=True)
    exists: Mapped[bool] = mapped_column(default=True, server_default=true())

    replies: Mapped[list["Comment"]] = relationship(
        order_by="Comment.created_at", viewonly=True
    )
