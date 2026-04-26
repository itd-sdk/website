from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import Session

Base = declarative_base()
SessionLocal = None

def create_db(url: str) -> None:
    global SessionLocal
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=300)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

def get_db() -> Session:
    assert SessionLocal, 'create db first'
    return SessionLocal()