from datetime import datetime
from uuid import UUID

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.services.db import Base


class UserProfileSnapshot(Base):
    """Username, name, clan, bio and banner at a point in time, written on change"""

    __tablename__ = "user_profile_snapshots"
    __table_args__ = (UniqueConstraint("user_id", "recorded_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(index=True)  # users.user_id
    recorded_at: Mapped[datetime]
    # only the fields that were known: old backups have no bio and banner
    data: Mapped[dict] = mapped_column(JSONB)
