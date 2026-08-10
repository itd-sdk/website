from sqlalchemy.orm import Mapped, mapped_column

from app.services.db import Base


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    search_cursor: Mapped[str] = mapped_column(default="aa")
