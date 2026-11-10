"""Схемы студента."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StudentCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    group_number: str = Field(
        min_length=4,
        max_length=20,
        description="Формат 99-АААаа-99, например 01-ФИИтт-01",
    )
    is_active: bool = True


class StudentUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    group_number: str | None = Field(default=None, min_length=4, max_length=20)
    is_active: bool | None = None


class StudentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    group_number: str
    is_active: bool
    created_at: datetime


class StudentList(BaseModel):
    items: list[StudentRead]
    total: int
    page: int
    limit: int
