"""Схемы дисциплины.

teacher_name есть только в ответах: он приходит JOIN'ом из teachers и нужен
списку, чтобы не дёргать преподавателя отдельным запросом на каждую строку.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DisciplineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    teacher_id: int
    teacher_name: str | None = None
    created_at: datetime


class DisciplineList(BaseModel):
    items: list[DisciplineRead]
    total: int


class DisciplineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    teacher_id: int = Field(ge=1)


class DisciplineUpdate(BaseModel):
    """Частичная правка; не переданное поле остаётся как было."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    teacher_id: int | None = Field(default=None, ge=1)
