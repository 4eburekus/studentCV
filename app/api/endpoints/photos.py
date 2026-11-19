"""Эталонные фото: загрузка (требование №8), список, удаление.

Роутер подключается БЕЗ префикса (см. app/api/router.py), потому что пути
разные: вложенные под студента (загрузка/список) и отдельные по id фото
(удаление). Полные пути объявлены здесь.
"""

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.dependencies import get_session
from app.api.openapi import R404, R409, R415, R422, R503, merge
from app.schemas import photo as schemas
from app.services import photos as photos_service
from app.services import storage
from app.services import students as students_service

router = APIRouter()

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png"}


async def _read_image(file: UploadFile) -> bytes:
    """Только читаем и проверяем тип; целостность изображения - дело CV-модуля."""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"content type {file.content_type!r} is not allowed; expected jpeg or png",
        )
    payload = await file.read()
    if not payload:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "uploaded file is empty")
    return payload


def _read(photo) -> schemas.PhotoRead:
    """ORM-объект -> ответ с готовым путём к байтам.

    content_path собираем здесь, а не на фронте: клиент не должен знать
    префикс API и то, что файл лежит в S3 под ключом photo_url. Именно из-за
    такого «собрать самому» в контрактах появляются расхождения вида
    «фронт ждёт /photos/1/raw, сервер отдаёт /photos/1/content».
    """
    return schemas.PhotoRead(
        id=photo.id,
        student_id=photo.student_id,
        photo_url=photo.photo_url,
        content_hash=photo.content_hash,
        created_at=photo.created_at,
        content_path=f"/api/v1/photos/{photo.id}/content",
    )


@router.post(
    "/students/{student_id}/photos",
    response_model=schemas.PhotoRead,
    status_code=status.HTTP_201_CREATED,
    responses=merge(R404, R409, R415, R422, R503),
)
async def add_photo(
    student_id: int,
    file: UploadFile = File(..., description="Эталонное фото (jpeg/png)"),
    session: AsyncSession = Depends(get_session),
) -> schemas.PhotoRead:
    payload = await _read_image(file)
    settings = get_settings()

    try:
        photo = await photos_service.add(session, student_id, payload, file.content_type or "image/jpeg")
    except storage.StorageError as exc:
        # Хранилище недоступно или отклонило запись. Это НЕ ошибка данных:
        # без 503 клиент получил бы 500 и считал бы, что сломали мы,
        # а не инфраструктура.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except photos_service.InvalidImage as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except photos_service.StudentNotActive as exc:
        # Выбывший студент: журнал жив, но эталон заводить поздно - это
        # конфликт состояния, а не ошибка формата файла.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except students_service.StudentNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except photos_service.PhotoLimitError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": str(exc),
                "student_id": exc.student_id,
                "photos_total": exc.count,
                "min_photos": settings.min_photos,
                "max_photos": settings.max_photos,
            },
        ) from exc
    return _read(photo)


@router.get(
    "/students/{student_id}/photos",
    response_model=schemas.PhotoList,
    responses=R404,
)
async def list_photos(
    student_id: int,
    session: AsyncSession = Depends(get_session),
) -> schemas.PhotoList:
    try:
        items = await photos_service.list_for_student(session, student_id)
    except students_service.StudentNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    settings = get_settings()
    total = len(items)
    return schemas.PhotoList(
        items=[_read(photo) for photo in items],
        total=total,
        min_photos=settings.min_photos,
        max_photos=settings.max_photos,
        # «Разрешить и предупреждать» (согласование 10.11.2026): удаление
        # последнего эталона допустимо, но студент без эталонов не
        # распознаётся - состояние отдаём полем, а не ошибкой.
        status="ok" if total >= settings.min_photos else "below_minimum",
    )


@router.delete(
    "/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=merge(R404, R503),
)
async def delete_photo(
    photo_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Удаляет и строку, и объект: осиротевшие файлы в бакете нам не нужны."""
    try:
        await photos_service.remove(session, photo_id)
    except storage.StorageError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except photos_service.PhotoNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/photos/{photo_id}/content",
    responses=merge(R404, R503),
)
async def get_photo_content(
    photo_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Прокси эталона для <img> фронтенда.

    Браузер не получает S3 endpoint, ключи или имя бакета. Это особенно важно
    в dist-варианте compose: SeaweedFS не должен быть публичным сервисом
    только ради превью в админке.
    """
    try:
        payload, content_type, etag = await photos_service.get_content(session, photo_id)
    except photos_service.PhotoNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except photos_service.PhotoObjectMissing as exc:
        # Строка есть, объект пропал: это рассинхронизация, но клиенту полезнее
        # 410, чем 500 - карточка может показать «объект отсутствует».
        raise HTTPException(status.HTTP_410_GONE, str(exc)) from exc
    except storage.StorageError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    return Response(
        content=payload,
        media_type=content_type,
        headers={
            "ETag": f'"{etag}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.put(
    "/photos/{photo_id}/content",
    response_model=schemas.PhotoRead,
    responses=merge(R404, R503),
)
async def replace_photo_content(
    photo_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> schemas.PhotoRead:
    """Атомарная замена байтов существующего эталона."""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"unsupported content type {file.content_type!r}; "
            f"allowed: {sorted(ALLOWED_CONTENT_TYPES)}",
        )

    try:
        payload = await file.read()
        photo = await photos_service.replace(
            session, photo_id, payload, file.content_type or "image/jpeg"
        )
    except photos_service.PhotoNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (storage.StorageError, storage.ObjectNotFound) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    return schemas.PhotoRead(
        id=photo.id,
        student_id=photo.student_id,
        photo_url=photo.photo_url,
        content_hash=photo.content_hash,
        created_at=photo.created_at,
        content_path=f"/api/v1/photos/{photo.id}/content",
    )
