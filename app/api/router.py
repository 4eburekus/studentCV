"""Точка подключения всего API.

Здесь живут ДВЕ вещи, которые важно держать в одном месте:

1. Префикс версии. Смена /api/v1 на /api/v2 правит этот файл, а не каждый
   эндпоинт.
2. Авторизацию и её описание в контракте. И зависимость get_current_teacher,
   и ответ 401 объявлены ОДИН раз на api_router: проверено на живом
   FastAPI 0.115, что и dependencies, и responses родителя долляются до
   маршрутов, подключённых через include_router, не затирая route-level
   responses. Размазать 401 по обработчикам - способ однажды забыть его на
   одном эндпоинте, и это будет дыра в контракте, а не опечатка.

Реальный вход (требование №11) заменяет заглушку правкой app/dependencies.py;
этот файл при этом не меняется.
"""

from fastapi import APIRouter, Depends

from app.api.endpoints import attendance, lessons, photos, students
from app.dependencies import get_current_teacher
from app.api.openapi import R401

api_router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(get_current_teacher)],
    responses=R401,
)

# /healthz подключается в app/main.py: это проверка готовности контейнера,
# у healthcheck'а нет учётных данных, и в контракт для фронтенда он не входит.
api_router.include_router(students.router, prefix="/students", tags=["students"])
# Фото живут и как вложенный ресурс студента (загрузка, список), и как
# отдельный ресурс (удаление по id) - оба пути объявлены в photos.py, поэтому
# подпрефикса здесь нет.
api_router.include_router(photos.router, tags=["photos"])
api_router.include_router(lessons.router, prefix="/lessons", tags=["lessons"])
api_router.include_router(
    attendance.router, prefix="/attendance", tags=["attendance"]
)
