from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from app.services.db import Base


class SearchPrefix(Base):
    __tablename__ = "search_prefixes"

    prefix: Mapped[str] = mapped_column(unique=True, primary_key=True)
    checked_at: Mapped[datetime | None]
    found_count: Mapped[int] = mapped_column(default=0)
