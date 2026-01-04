#!/usr/bin/env python3
"""
Database session management for SQLAlchemy
"""

from contextlib import contextmanager
from typing import Generator

from app.config import settings
from app.log import logger
from app.models.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Create SQLAlchemy engine with configuration from settings
engine = create_engine(
    settings.DB_URL,
    echo=settings.DB_ECHO,
    connect_args=settings.DB_CONNECT_ARGS,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,  # 验证连接是否有效
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables"""
    try:
        logger.info(f"Initializing database with type: {settings.DATABASE_TYPE}")
        logger.info(
            f"Database URL: {settings.DB_URL.split('@')[-1] if '@' in settings.DB_URL else settings.DB_URL}"
        )
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.

    Usage:
        with get_session() as session:
            user = session.query(User).filter_by(tg_id=123).first()
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_session() -> Session:
    """
    Get a new database session.

    Note: Caller is responsible for closing the session.
    """
    return SessionLocal()
