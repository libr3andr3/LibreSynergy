"""Database connection and session management."""

import os
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://libresynergy:libresynergy@localhost:5432/libresynergy",
)

_engine = None
_async_session = None


class Base(DeclarativeBase):
    pass


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)
    return _engine


def _get_sessionmaker():
    global _async_session
    if _async_session is None:
        _async_session = async_sessionmaker(_get_engine(), class_=AsyncSession, expire_on_commit=False)
    return _async_session


async def get_db():
    """Dependency that yields a database session."""
    sessionmaker = _get_sessionmaker()
    async with sessionmaker() as session:
        try:
            yield session
        finally:
            await session.close()


# Use _get_engine() in app.py lifespan instead of importing engine directly
