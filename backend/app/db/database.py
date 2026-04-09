"""Database engine and session setup."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


engine = create_engine(
    settings.sqlite_url,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for request-scoped usage."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
