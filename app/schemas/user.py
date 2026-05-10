from datetime import datetime
from uuid import UUID

from sqlalchemy import func, Column, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import ARRAY

from app.services.db import Base


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[UUID] = mapped_column(unique=True)
    found_at: Mapped[datetime] = mapped_column(server_default=func.now())

    created_at: Mapped[datetime] = mapped_column(nullable=True)
    username: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[str]
    followers: Mapped[int]
    following: Mapped[int]
    posts: Mapped[int]
    verified: Mapped[bool]
    following_users: Mapped[str]
    followed_by_users: Mapped[str]
    avatar: Mapped[str] = mapped_column(default='?')
