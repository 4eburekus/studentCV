"""Схемы пары (расписания).

HealthResponse переехал в app/schemas/health.py - здесь были только схемы
расписания; дубль схемы удалён после появления строгой версии.
"""

from datetime import date, time

from pydantic import BaseModel, ConfigDict


class LessonRead(BaseModel):
    """Только чтение: расписание ведётся отдельным контуром, не API-срезом."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    discipline_id: int
    discipline_name: str | None = None
    lesson_date: date
    start_time: time
    end_time: time


class LessonList(BaseModel):
    items: list[LessonRead]
    total: int
