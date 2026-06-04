from sqlalchemy.orm import Mapped, mapped_column

from app.services.db import Base


class App(Base):
    __tablename__ = "apps"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str]
    token: Mapped[str]
    # task: Mapped[str | None] = mapped_column(nullable=True)  # create | update | delete
    # task_target: Mapped[str | None] = mapped_column(nullable=True)  # user
    # task_target_ids: Mapped[str | None] = mapped_column(nullable=True)

    added: Mapped[int] = mapped_column(default=0)
    refreshed: Mapped[int] = mapped_column(default=0)
