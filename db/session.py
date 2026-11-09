"""Подключение к PostgreSQL и фабрика асинхронных сессий."""

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://studentcv:studentcv@localhost:5432/studentcv",
)

# echo включается переменной SQL_ECHO=1 - полезно при отладке запросов.
SQL_ECHO = os.getenv("SQL_ECHO", "0") not in ("0", "", "false", "False")

engine = create_async_engine(
    DATABASE_URL,
    echo=SQL_ECHO,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Зависимость FastAPI (в этом срезе - генератор для сидов и сервисов).

    pool_pre_ping в engine снимает классическую ошибку InterfaceError
    после restart контейнера с БД.
    """
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Корректно закрыть пул соединений (вызывается в lifespan приложения)."""
    await engine.dispose()
