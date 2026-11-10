"""Проверка готовности.

Без авторизации: этот эндпоинт дергает healthcheck контейнера, у которого
нет учётных данных. Возвращает 503, если база недоступна, - иначе healthcheck
всегда видел бы 200 и контейнер никогда не стал бы unhealthy.

Хранилище считается здоровым только вместе с провижинингом: «порт отвечает, но
бакетов нет» - это зелёный healthz над приложением, где первая же запись
эталона кончится ошибкой.
"""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.dependencies import get_session
from app.schemas.health import HealthResponse
from app.services import storage

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse)
async def healthz(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> HealthResponse:
    settings = get_settings()

    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001: health обязан вернуть статус, а не упасть 500
        db_ok = False

    # Предупреждения провижининга (versioning и пр.) lifespan кладёт в
    # app.state; до старта lifespan их нет - отсюда "".
    provisioning_warnings: list[str] = list(
        getattr(request.app.state, "storage_warnings", [])
    )

    storage_status: str
    warnings: list[str]
    try:
        # Зонд: список объектов в бакете эталонов.
        #
        # Именно list, а не head(несуществующего ключа): head по 404 не
        # отличает «ключ нет» от «бакет нет», а успешный list - это 200 даже
        # для пустого бакета. 404/NoSuchBucket значит ровно одно: бакета нет,
        # ensure_buckets() из lifespan не выполнился.
        await storage.list_probe(settings.s3_bucket_biometrics)
    except storage.ProvisioningError as exc:
        # Хранилище отвечает, но бакетов нет. Отдельное состояние, а не down:
        # перезапуск backend обычно чинит это сам (lifespan повторит зонд).
        storage_status = "unconfigured"
        warnings = [str(exc)]
    except storage.StorageError as exc:
        storage_status = "down"
        warnings = [str(exc)]
    except Exception as exc:  # noqa: BLE001
        storage_status = "down"
        warnings = [f"unexpected: {type(exc).__name__}: {exc}"]
    else:
        storage_status = "ok"
        warnings = provisioning_warnings

    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="down",
            database="down",
            storage=storage_status,  # type: ignore[arg-type]
            storage_warnings=warnings,
        )

    if storage_status == "down":
        # Хранилище лежит - фото не загрузить и события не принять:
        # приложение нерабочее, а не «почти рабочее».
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        overall = "down"
    elif storage_status == "ok" and not warnings:
        overall = "ok"
    else:
        # unconfigured или есть нерешённые предупреждения провижининга.
        overall = "degraded"

    return HealthResponse(
        status=overall,  # type: ignore[arg-type]
        database="ok",
        storage=storage_status,  # type: ignore[arg-type]
        storage_warnings=warnings,
    )
