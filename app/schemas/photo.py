"""Схемы эталонного фото."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PhotoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    photo_url: str
    # NULL у строк, созданных до среза объектного хранилища (миграция 0002)
    content_hash: str | None = None
    created_at: datetime


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


class ErrorDetail(BaseModel):
    """Ответ на нарушение правила 1-5 (requirement N8)."""

    detail: str
    student_id: int
    photos_total: int
    min_photos: int
    max_photos: int
