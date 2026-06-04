from os import getenv
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import Session

Base = declarative_base()
SessionLocal = None


def create_db() -> None:
    global SessionLocal
    engine = create_engine(getenv("DATABASE_URL", ""), pool_size=10, max_overflow=20)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    assert SessionLocal, "create db first"
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
