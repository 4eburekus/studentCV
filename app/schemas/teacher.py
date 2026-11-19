"""Схемы преподавателя.

Пароль здесь только на входе: `password_hash` не попадает ни в одну модель
ответа. Это не осторожность, а требование - хэш в JSON означал бы, что он
утечёт в логи прокси, в кэш браузера и в скриншоты поддержки.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TeacherRead(BaseModel):
    """Преподаватель без секретов."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    login: str
    created_at: datetime


class TeacherList(BaseModel):
    items: list[TeacherRead]
    total: int


class TeacherCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    login: str = Field(min_length=1, max_length=100)
    # Минимум 8 - нижняя граница, а не политика паролей: реальные правила
    # (срок жизни, история, блокировка после попыток) относятся к срезу
    # авторизации (требование N11), которого ещё нет.
    password: str = Field(min_length=8, max_length=128)


class TeacherUpdate(BaseModel):
    """Частичное обновление: не переданное поле не меняется.

    Пароля здесь нет намеренно: его смена - отдельная операция с отдельным
    правом. Иначе случайный PATCH с пустым password сбрасывал бы учётку.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    login: str | None = Field(default=None, min_length=1, max_length=100)


class TeacherPasswordUpdate(BaseModel):
    password: str = Field(min_length=8, max_length=128)
