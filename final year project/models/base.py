import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "")

_engine = None
_async_session_maker = None


class Base(DeclarativeBase):
    pass


def get_db_url() -> str:
    url = DATABASE_URL
    if url and url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def init_db():
    global _engine, _async_session_maker
    url = get_db_url()
    if not url:
        print("WARNING: DATABASE_URL not set — running without DB persistence.")
        return
    _engine = create_async_engine(url, pool_pre_ping=True, echo=False, pool_size=5, max_overflow=10)
    _async_session_maker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("INFO: Database tables created / verified.")


async def close_db():
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
        print("INFO: Database connection closed.")


async def get_session() -> AsyncSession:
    if _async_session_maker is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    async with _async_session_maker() as session:
        yield session
