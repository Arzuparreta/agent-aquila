from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(settings.database_url, future=True)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    # ``expire_on_commit=False`` is the SQLAlchemy-recommended setting for async
    # sessions: it prevents attributes from being lazy-reloaded after commit, which
    # would otherwise raise ``MissingGreenlet`` whenever a route commits mid-request
    # and then re-reads an ORM object (very common for routes that auto-create a
    # default row before listing). The codebase already calls ``await db.refresh(...)``
    # explicitly wherever it needs post-commit DB state.
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
