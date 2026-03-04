from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

class Base(DeclarativeBase):
    pass

engine = create_async_engine(settings.database_url, echo=False)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add web_red_social column to existing DBs
        try:
            await conn.execute(
                text("ALTER TABLE businesses ADD COLUMN web_red_social VARCHAR(50)")
            )
        except Exception:
            pass  # column already exists
        # Add web scraping persistence columns to existing DBs
        for col, col_type in [("web_contenido", "TEXT"), ("web_datos_extra", "TEXT")]:
            try:
                await conn.execute(
                    text(f"ALTER TABLE businesses ADD COLUMN {col} {col_type}")
                )
            except Exception:
                pass  # column already exists

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
