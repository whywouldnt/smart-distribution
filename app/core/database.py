import os
from dotenv import load_dotenv

# .env dosyasını belleğe yükle
load_dotenv()

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./smart_distribution.db")
IS_DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Supabase genellikle postgresql:// veya postgres:// bağlantısı verir.
# SQLAlchemy'nin asenkron çalışması için bunu postgresql+asyncpg:// formatına çevirmemiz, 
# senkron çalışan init_db.py için ise postgresql+psycopg2:// formatına çevirmemiz gerekiyor.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL.startswith("postgresql://"):
    ASYNC_DB_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    SYNC_DB_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
else:
    ASYNC_DB_URL = DATABASE_URL
    SYNC_DB_URL = DATABASE_URL.replace("+aiosqlite", "")

# Sadece SQLite için thread check kapatılmalı
connect_args = {}
if "sqlite" in ASYNC_DB_URL:
    connect_args = {"check_same_thread": False}

async_engine = create_async_engine(
    ASYNC_DB_URL,
    connect_args=connect_args,
    echo=IS_DEBUG,
)

engine = create_engine(
    SYNC_DB_URL,
    connect_args=connect_args,
    echo=IS_DEBUG,
)

AsyncSessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    bind=async_engine,
    class_=AsyncSession,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    bind=engine,
)


class Base(DeclarativeBase):
    pass


async def get_async_db():
    async with AsyncSessionLocal() as session:
        yield session


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
