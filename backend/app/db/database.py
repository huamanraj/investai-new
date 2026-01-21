"""
Database connection and session management
"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings


from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

# Convert postgresql:// to postgresql+asyncpg:// for async driver
# and handle sslmode which asyncpg doesn't support as a query param
def transform_database_url(url: str) -> str:
    if not url:
        return ""
    
    # 1. Replace scheme
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    # 2. Parse URL to handle query parameters
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    
    # asyncpg doesn't support sslmode or channel_binding in the URL
    query.pop('sslmode', None)
    query.pop('channel_binding', None)
    
    # Reconstruct URL without problematic params
    new_query = urlencode(query, doseq=True)
    transformed_url = urlunparse(parsed._replace(query=new_query))
    
    return transformed_url

DATABASE_URL = transform_database_url(settings.DATABASE_URL)

# Create async engine
# For Neon/asyncpg, we often need to specify ssl=True in connect_args
engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Disable verbose SQL logging
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # Avoid "connection was closed in the middle of operation" after long waits
    pool_recycle=1800,   # Recycle connections periodically to avoid stale connections
    connect_args={"ssl": True} if "neon.tech" in DATABASE_URL else {}
)

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    """Base class for all models"""
    pass


async def get_db() -> AsyncSession:
    """Dependency to get database session"""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Initialize database (create tables)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
