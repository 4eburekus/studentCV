"""Схемы посещаемости: событие от CV-модуля и журнал пары."""

from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from db.enums import AttendanceStatus

# Исходы обработки события. Literal, а не str: OpenAPI отдаёт enum, и фронт
# получает список допустимых значений в контракте, а не в переписке.
# Значения совпадают с константами в app/services/attendance.py - сводятся
# в одном месте (см. app.api.endpoints.attendance), расхождение здесь
# проявится как нераспознанный статус на клиенте.
Outcome = Literal[
    "recorded",
    "kept_earlier_entry",
    "kept_manual_edit",
    "ignored_after_lesson_end",
]


class AttendanceEventCreate(BaseModel):
    """Контракт приёмника (веха 5): событие + ссылка на кадр в хранилище."""

    lesson_id: int = Field(gt=0)
    student_id: int = Field(gt=0)
    captured_at: datetime = Field(
        description="Момент распознавания, с временной зоной (timestamptz)"
    )
    frame_object_key: str = Field(
        min_length=1,
        max_length=512,
        description="Ключ кадра в бакете frames: frames/<lesson_id>/<uuid4>.jpg",
    )


class AttendanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    lesson_id: int
    entry_time: datetime
    status: AttendanceStatus
    delay_minutes: int | None = None
    is_manually_edited: bool
    created_at: datetime


class AttendanceEventResult(BaseModel):
    """Ответ приёмника: исход и, если записали, сама запись.

    record = None означает «событие принято, но по правилу не записано»
    (вход после конца пары). Это НЕ ошибка: данные валидны, их сознательно
    не учитываем, поэтому 200, а не 4xx.
    """

    record: AttendanceRead | None = None
    outcome: Outcome = Field(
        description=(
            "recorded - создана или обновлена запись; "
            "kept_earlier_entry - оставлен более ранний вход; "
            "kept_manual_edit - запись правили руками, не трогали; "
            "ignored_after_lesson_end - вход после конца пары, строки нет"
        )
    )
    lesson_start: time | None = Field(
        default=None, description="Начало пары: от него считан delay_minutes"
    )
    delay_minutes: int | None = None


class JournalEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    full_name: str
    group_number: str
    entry_time: datetime
    status: AttendanceStatus
    delay_minutes: int | None = None


class Journal(BaseModel):
    lesson_id: int
    discipline_name: str
    lesson_date: str
    start_time: str
    end_time: str = Field(
        description="Конец пары: по нему журнал отличает опоздавших от "
        "тех, кто пришёл слишком поздно и не учтён"
    )
    entries: list[JournalEntry]
    total: int
