"""Точка входа FastAPI: создание приложения, lifespan, подключение роутеров.

Здесь нет бизнес-логики и нет эндпоинтов - только сборка приложения.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.endpoints import health
from app.api.router import api_router
from app.core.config import get_settings, validate_settings
from app.services.lesson_closer import close_overdue_loop
from db.session import dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Старт: конфигурация -> гарантия бакетов/версий. Стоп: закрытие пула.

    validate_settings поднимает RuntimeError, если AUTH_STUB_ENABLED=false, -
    приложение тогда не стартует вовсе. Это намеренно: dist-окружение не должно
    молча поднять сервер с незакрытым требованием №11.

    ensure_buckets вызывается до первого запроса, а не при первой загрузке
    фото, потому что versioning обязан быть включён ДО первой записи объекта:
    версии у ранее записанных объектов не появляются задним числом (согласование
    хранилища, 10.11.2026). Проблемы провижининга НЕ валат приложение: хранилище
    может лежать во время старта (например, оно ещё разворачивается или это
    прогон тестов), а healthz честно покажет degraded/unconfigured и причина
    будет в app.state.storage_warnings.
    """
    settings = get_settings()
    validate_settings(settings)

    from app.services import storage

    try:
        app.state.storage_warnings = await storage.ensure_buckets()
    except Exception as exc:  # noqa: BLE001: старт не должен падать из-за хранилища
        app.state.storage_warnings = [f"provisioning skipped: {type(exc).__name__}: {exc}"]

    # Фоновое закрытие пар. Отказывается подниматься, если переменная
    # выключена (тесты, отладка журнала) - см. LESSON_CLOSE_ENABLED.
    stop_closer = asyncio.Event()
    closer_task: asyncio.Task | None = None
    if settings.lesson_close_enabled:
        closer_task = asyncio.create_task(
            close_overdue_loop(stop_closer, settings.lesson_close_interval_seconds),
            name="lesson-closer",
        )
        app.state.closer_task = closer_task
    app.state.closer_stopped = stop_closer

    try:
        yield
    finally:
        # Сначала сигналим фону и ждём его, и только потом гасим пул БД:
        # закрытие ходит в базу, и ронять пул под ним нельзя.
        stop_closer.set()
        if closer_task is not None:
            closer_task.cancel()
            try:
                await closer_task
            except asyncio.CancelledError:
                pass
        await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="StudentCV API",
        version="0.2",
        description=(
            "Учёт посещаемости через распознавание лиц. "
            "Контракт для будущего фронтенда (Vue) - этот OpenAPI."
        ),
        lifespan=lifespan,
    )
    # healthz - вне /api/v1 и вне авторизации: это эндпоинт healthcheck'а
    # контейнера, у которого нет учётных данных, и он не входит в контракт
    # для фронтенда. Контрактные роутеры - под api_router.
    app.include_router(health.router, tags=["health"])
    app.include_router(api_router)
    return app


app = create_app()
