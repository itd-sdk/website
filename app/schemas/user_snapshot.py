from datetime import datetime
from uuid import UUID

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.services.db import Base


class UserSnapshot(Base):
    """User counters at a point in time, written only when something changed"""

    __tablename__ = "user_snapshots"
    # importing the same backup twice must not duplicate points
    __table_args__ = (UniqueConstraint("user_id", "recorded_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(index=True)  # users.user_id
    recorded_at: Mapped[datetime]
    followers_count: Mapped[int]
    following_count: Mapped[int]
    posts_count: Mapped[int]
    exists: Mapped[bool]
