from uuid import UUID

from sqlalchemy.orm import Mapped, mapped_column

from app.services.db import Base


class Epepuy(Base):
    __tablename__ = "epepuy"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    file_id: Mapped[UUID] = mapped_column(unique=True)
