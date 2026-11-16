"""Схемы пары (расписания).

HealthResponse переехал в app/schemas/health.py - здесь были только схемы
расписания; дубль схемы удалён после появления строгой версии.
"""

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict


class LessonRead(BaseModel):
    """Только чтение пар: расписание ведётся отдельным контуром, не API-срезом.

    group_number и closed_at появились вместе с ABSENT-записью: группа задаёт
    состав журнала, а closed_at - единственный надёжный признак того, что
    закрытие уже было. По наличию строк ABSENT фронт этого определить не может:
    на пару могли прийти все, и отсутствий в журнале не будет при закрытой паре.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    discipline_id: int
    discipline_name: str | None = None
    group_number: str
    lesson_date: date
    start_time: time
    end_time: time
    closed_at: datetime | None = None


class LessonList(BaseModel):
    items: list[LessonRead]
    total: int
