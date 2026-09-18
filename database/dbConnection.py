"""Database connection, pooling, and session management."""
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session

from utils.config import config

engine = create_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,
    future=True,
)

SessionLocal = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
)


def init_db():
    """Create all tables that don't yet exist (idempotent). Prefer sql/schema.sql
    for the authoritative production schema; this is a convenience for local dev."""
    from model import models  # noqa: F401 (registers models on Base.metadata)
    models.Base.metadata.create_all(bind=engine)


@contextmanager
def get_session():
    """Context-managed session: commits on success, rolls back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def db_health_check() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
