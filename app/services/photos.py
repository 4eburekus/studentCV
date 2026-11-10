"""Эталонные фото: загрузка в MinIO, правило 1-5, удаление вместе с объектом.

Главное правило этого файла: строка в student_photos и объект в бакете
живут или вместе, или не живут вовсе. Порядок действий выбран так, чтобы
при отказе на любом шаге не оставалось ни осиротевшего объекта, ни строки
без байтов.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services import storage
from app.services.storage import StorageError
from app.services.students import get as get_student
from db.models import Student, StudentPhoto

log = logging.getLogger(__name__)


class PhotoLimitError(Exception):
    def __init__(self, student_id: int, count: int, minimum: int, maximum: int) -> None:
        super().__init__(
            f"student {student_id} has {count} photos; "
            f"required between {minimum} and {maximum} (requirement N8)"
        )
        self.student_id = student_id
        self.count = count


class PhotoNotFound(Exception):
    def __init__(self, photo_id: int) -> None:
        super().__init__(f"photo {photo_id} not found")
        self.photo_id = photo_id


class InvalidImage(Exception):
    """Пустое или заведомо не изображение.

    Проверяем минимально: реальные гарантии качества эталона даёт CV-модуль,
    а не API. Но пустой файл в бакете - это сломанный эталон, который
    распознавание потеряет молча.
    """


class StudentNotActive(Exception):
    """Эталон нельзя завести выбывшему студенту.

    Отдельная ошибка, а не InvalidImage: предмет отказа - не картинка,
    и отвечать на это 422 про формат файла было бы неверно.
    """


async def count(session: AsyncSession, student_id: int) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(StudentPhoto)
            .where(StudentPhoto.student_id == student_id)
        )
    ).scalar_one()


async def list_for_student(
    session: AsyncSession, student_id: int
) -> list[StudentPhoto]:
    await get_student(session, student_id)
    result = await session.execute(
        select(StudentPhoto)
        .where(StudentPhoto.student_id == student_id)
        .order_by(StudentPhoto.created_at)
    )
    return list(result.scalars().all())


async def add(
    session: AsyncSession,
    student_id: int,
    payload: bytes,
    content_type: str = "image/jpeg",
) -> StudentPhoto:
    """Загрузка эталона: проверка лимита -> MinIO -> БД -> коммит.

    Схема ключа фиксируется ДО записи объекта, потому что она же уходит в
    photo_url и проверяется CHECK'ом.
    """
    if not payload:
        raise InvalidImage("photo payload is empty")

    student = await get_student(session, student_id)
    if not student.is_active:
        raise StudentNotActive(student_id)

    settings = get_settings()
    current = await count(session, student_id)
    if current >= settings.max_photos:
        raise PhotoLimitError(student_id, current, settings.min_photos, settings.max_photos)

    key = storage.new_biometric_key()
    content_hash = storage.compute_content_hash(payload)

    # 1. Объект в бакете раньше строки: если БД откажет, удалим объект.
    await storage.put_object(settings.s3_bucket_biometrics, key, payload, content_type)

    photo = StudentPhoto(
        student_id=student_id,
        photo_url=key,
        content_hash=content_hash,
    )
    session.add(photo)
    try:
        await session.commit()
    except Exception:
        # Откат строки без удаления объекта оставил бы осиротевший файл,
        # который никто никогда не найдёт.
        await session.rollback()
        await storage.delete_object(settings.s3_bucket_biometrics, key)
        raise

    await session.refresh(photo)
    return photo


async def remove(session: AsyncSession, photo_id: int) -> None:
    """Удаление строки И объекта.

    Сначала строка, потом объект - порядок выбран по тяжести остатка:
    осиротевшие байты в бакете это расход, а строка без объекта это битый
    эталон, который распознавание потеряет молча.

    Если удаление объекта не удалось, строка уже удалена и БД консистентна;
    об объекте пишем в лог - подберёт сверка (open question §9 про TTL кадров
    и уборку мусора в бакете).
    """
    photo = await session.get(StudentPhoto, photo_id)
    if photo is None:
        raise PhotoNotFound(photo_id)

    settings = get_settings()
    key = photo.photo_url

    await session.delete(photo)
    await session.commit()

    try:
        await storage.delete_object(settings.s3_bucket_biometrics, key)
    except StorageError:
        log.warning("photo row deleted but object %s stayed in bucket", key)
        raise


async def verify_objects(session: AsyncSession) -> list[str]:
    """Сверка «строка ↔ объект» по всему справочнику эталонов.

    Инструмент диагностики расхождения БД и бакета: content_hash позволяет
    сверять без скачивания, но здесь ограничиваемся head_object - дешевле.
    Возвращает список photo_url, которых нет в бакете.
    """
    settings = get_settings()
    broken: list[str] = []
    result = await session.execute(select(StudentPhoto.photo_url))
    for (key,) in result.all():
        if not await storage.object_exists(settings.s3_bucket_biometrics, key):
            broken.append(key)
    return broken
