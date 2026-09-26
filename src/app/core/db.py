"""
Database session management for SQLAlchemy
"""

from collections.abc import Callable, Generator
from contextlib import contextmanager

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from sqlalchemy import create_engine, inspect, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.log import logger

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

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models"""


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


def rewrite_scheduler_rows(
    jobstore: SQLAlchemyJobStore,
    transform: Callable[[bytes], bytes | None],
) -> int:
    """Apply an atomic, compare-and-swap transformation to stored job states.

    This is scheduler infrastructure SQL rather than a domain business query;
    the byte-level reference transform remains in ``core.scheduler``.
    """
    table = jobstore.jobs_t
    if not inspect(jobstore.engine).has_table(table.name, schema=table.schema):
        return 0
    updated = 0
    with jobstore.engine.begin() as connection:
        rows = connection.execute(
            select(table.c.id, table.c.job_state).with_for_update()
        ).all()
        for row in rows:
            replacement = transform(row.job_state)
            if replacement is None:
                continue
            result = connection.execute(
                update(table)
                .where(table.c.id == row.id, table.c.job_state == row.job_state)
                .values(job_state=replacement)
            )
            if result.rowcount != 1:
                raise RuntimeError(f"job changed while migrating: {row.id}")
            updated += 1
    return updated
