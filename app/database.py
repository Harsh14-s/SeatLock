from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.config import settings

# Create async engine with robust connection pooling
# In interviews, pool_size and max_overflow are crucial topics when discussing concurrency!
engine = create_async_engine(
    settings.async_database_url,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False,  # Set to True if you want to inspect raw SQL queries
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an independent database session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
