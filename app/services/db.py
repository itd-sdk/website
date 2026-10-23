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
    engine = create_engine(
        getenv("DATABASE_URL", ""),
        pool_size=3,
        max_overflow=10,
        pool_recycle=900,
        # drop connections broken by a postgres restart instead of failing requests
        pool_pre_ping=True
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)


def new_session() -> Session:
    assert SessionLocal, "create db first"
    return SessionLocal()


def get_db() -> Generator[Session, None, None]:
    db = new_session()
    try:
        yield db
    finally:
        db.close()
