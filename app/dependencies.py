"""Общие зависимости FastAPI: БД, текущий преподаватель, пагинация.

Именно этот файл подключается к каждому роутеру как зависимость, поэтому
реальный вход (требование №11) заменяет заглушку правкой одного места.
"""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from db.models import Teacher
from db.session import get_db


def get_session(db: AsyncSession = Depends(get_db)) -> AsyncSession:
    """Прозрачная обёртка над db.session.get_db.

    Нужна, чтобы эндпоинты зависели от app-слоя, а не импортировали db напрямую:
    тогда смена источника сессии (например, на транзакционный middleware)
    не трогает обработчики.
    """
    return db


# auto_error=False принципиально: встроенный режим HTTPBearer при пустом
# заголовке бросает 403 (проверено в этой же версии FastAPI), а нам нужен 401 -
# «не представился», а не «представился неправильно». Схема при этом всё равно
# регистрируется в OpenAPI, поэтому security появляется в контракте.
bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description=(
        "Заглушка авторизации: сейчас проверяется НАЛИЧИЕ заголовка "
        "Authorization, а не подлинность токена. Требование №11 закрыто "
        "реальным входом отдельным срезом (см. get_current_teacher)."
    ),
)


async def get_current_teacher(
    session: AsyncSession = Depends(get_session),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Teacher:
    """STUB: требование №11 реальным входом НЕ закрыто.

    Проверяет, что клиент вообще представился (заголовок Authorization есть),
    и возвращает фиксированного преподавателя из config (AUTH_STUB_LOGIN) без
    проверки подлинности токена. Задача заглушки - зафиксировать контракт
    «у каждого обработчика есть текущий преподаватель» и заставить клиента
    обращаться с авторизацией с первого дня, чтобы срез реального входа
    (сессии/JWT, интеграция с ЕИОС) заменил только эту функцию и config,
    не переписывая эндпоинты и не ломая клиентов.

    Не для продакшена: AUTH_STUB_ENABLED=false в dist-окружении запрещает
    старт приложения (см. app.core.config.validate_settings).
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_settings()
    teacher = await session.scalar(
        select(Teacher).where(Teacher.login == settings.auth_stub_login)
    )
    if teacher is None:
        # Отдельная ошибка, а не 401: пропавший stub-логин - это поломка
        # окружения/сидов, а не неудачная попытка входа.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Stub teacher '{settings.auth_stub_login}' not found. "
                "Run db.seeds or fix AUTH_STUB_LOGIN."
            ),
        )
    return teacher


@dataclass(frozen=True)
class Pagination:
    """Пагинация списков. limit ограничен сверху, чтобы не выгружали всю базу."""

    offset: int
    limit: int
    page: int


def pagination_params(
    page: int = Query(1, ge=1, description="Номер страницы, начиная с 1"),
    limit: int = Query(50, ge=1, le=500, description="Элементов на странице"),
) -> Pagination:
    """Стандартные параметры постраничной выдачи для всех списков."""
    return Pagination(offset=(page - 1) * limit, limit=limit, page=page)
