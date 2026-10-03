from datetime import datetime
from uuid import UUID

from sqlalchemy import Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.services.db import Base


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    post_id: Mapped[UUID] = mapped_column(unique=True)
    author_id: Mapped[UUID] = mapped_column(index=True)
    found_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime | None]
    edited_at: Mapped[datetime | None]
    content: Mapped[str] = mapped_column(Text, default="")
    spans: Mapped[list] = mapped_column(JSONB, default=list)
    attachments: Mapped[list] = mapped_column(JSONB, default=list)
    poll: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    likes_count: Mapped[int] = mapped_column(default=0)
    comments_count: Mapped[int] = mapped_column(default=0)
    reposts_count: Mapped[int] = mapped_column(default=0)
    views_count: Mapped[int] = mapped_column(default=0)
    is_pinned: Mapped[bool] = mapped_column(default=False)
    original_post_id: Mapped[UUID | None] = mapped_column(
        nullable=True, index=True
    )  # posts.post_id, for reposts
    wall_recipient_id: Mapped[UUID | None] = mapped_column(nullable=True)
    exists: Mapped[bool] = mapped_column(default=True)
