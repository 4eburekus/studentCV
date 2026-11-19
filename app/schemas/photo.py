"""Схемы эталонного фото."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PhotoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    # ВНИМАНИЕ: это НЕ ссылка. Здесь лежит ключ объекта в бакете
    # (biometrics/<uuid4>.jpg), историческое имя колонки обманывает.
    photo_url: str
    # NULL у строк, созданных до среза объектного хранилища (миграция 0002)
    content_hash: str | None = None
    created_at: datetime
    # Абсолютный путь для <img src>: GET /api/v1/photos/{id}/content.
    # Отдаём его сервером, а не собираем на фронте: фронт не должен знать
    # ни префикс API, ни то, что байты лежат в S3, ни схему ключа бакета.
    content_path: str | None = None


class PhotoList(BaseModel):
    items: list[PhotoRead]
    total: int
    # Правило 1-5 (требование №8): фронтенду нужно показать, довёл ли
    # преподаватель набор эталонов до минимума. Считается на сервере.
    min_photos: int = 1
    max_photos: int = 5
    # Нижняя граница НЕ блокирует удаление последнего: согласовано
    # 10.11.2026 «разрешить и предупреждать». Статус машиночитаемый
    # (Literal), а не текстовое warning-поле: клиенту нельзя сравнивать строки,
    # иначе смена формулировки сломает интерфейс.
    status: Literal["ok", "below_minimum"] = "ok"


class PhotoContent(BaseModel):
    """Служебная схема: ответ GET .../content отдаёт байты, не JSON.

    Объявлена для OpenAPI - без неё документация показывала бы этот эндпоинт
    как пустой, а контракт для фронтенда именно здесь и читается.
    """

    content_type: str
    content_hash: str | None = None


class ErrorDetail(BaseModel):
    """Ответ на нарушение правила 1-5 (requirement N8)."""

    detail: str
    student_id: int
    photos_total: int
    min_photos: int
    max_photos: int
