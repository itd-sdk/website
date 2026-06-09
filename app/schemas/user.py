from datetime import datetime
from uuid import UUID

from sqlalchemy import ARRAY, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.services.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[UUID] = mapped_column(unique=True)
    found_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    created_at: Mapped[datetime] = mapped_column(nullable=True)
    username: Mapped[str]
    display_name: Mapped[str]
    followers_count: Mapped[int]
    following_count: Mapped[int]
    posts_count: Mapped[int]
    verified: Mapped[bool]
    has_itdp: Mapped[bool] = mapped_column(default=False)
    following: Mapped[list[UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)))
    followers: Mapped[list[UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)))
    avatar: Mapped[str] = mapped_column(default="?")
    exists: Mapped[bool] = mapped_column(default=True)
