"""Логика студентов: создание, поиск, фильтрация, мягкое удаление.

Проверка формата номера группы идёт по той же регулярке, что и CHECK в БД
(GROUP_NUMBER_REGEX в db/models.py). Ошибка до отправки в БД нужна для
внятного 422: сообщение UniqueViolation от констрейнта пользователь не поймёт.
"""

from __future__ import annotations

import re
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.student import StudentCreate, StudentUpdate
from db.models import GROUP_NUMBER_REGEX, Student


class StudentNotFound(Exception):
    def __init__(self, student_id: int) -> None:
        super().__init__(f"student {student_id} not found")
        self.student_id = student_id


class InvalidGroupNumber(Exception):
    def __init__(self, value: str) -> None:
        super().__init__(
            f"group number '{value}' does not match the required format "
            f"{GROUP_NUMBER_REGEX} (example: 01-ФИИтт-01)"
        )
        self.value = value


def validate_group_number(group_number: str) -> None:
    if not re.match(GROUP_NUMBER_REGEX, group_number):
        raise InvalidGroupNumber(group_number)


async def create(session: AsyncSession, payload: StudentCreate) -> Student:
    validate_group_number(payload.group_number)
    student = Student(
        full_name=payload.full_name,
        group_number=payload.group_number,
        is_active=payload.is_active,
    )
    session.add(student)
    await session.commit()
    await session.refresh(student)
    return student


async def get(session: AsyncSession, student_id: int) -> Student:
    student = await session.get(Student, student_id)
    if student is None:
        raise StudentNotFound(student_id)
    return student


async def list_students(
    session: AsyncSession,
    *,
    group: str | None = None,
    query: str | None = None,
    is_active: bool | None = True,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[Student], int]:
    """Список с фильтром по группе, подстрокой ФИО и активностью.

    Возвращает (страница, общее_число) - второе нужно для пагинации на фронте.
    """
    conditions = []
    if group:
        conditions.append(Student.group_number == group)
    if query:
        pattern = f"%{query}%"
        conditions.append(
            or_(
                Student.full_name.ilike(pattern),
                Student.group_number.ilike(pattern),
            )
        )
    if is_active is not None:
        conditions.append(Student.is_active == is_active)

    stmt = select(Student)
    count_stmt = select(func.count()).select_from(Student)
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = (await session.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(Student.group_number, Student.full_name)
        .offset(offset)
        .limit(limit)
    )
    items = list((await session.execute(stmt)).scalars().all())
    return items, total


async def update(session: AsyncSession, student_id: int, payload: StudentUpdate) -> Student:
    student = await get(session, student_id)

    if payload.group_number is not None:
        validate_group_number(payload.group_number)
        student.group_number = payload.group_number
    if payload.full_name is not None:
        student.full_name = payload.full_name
    if payload.is_active is not None:
        student.is_active = payload.is_active

    await session.commit()
    await session.refresh(student)
    return student


async def deactivate(session: AsyncSession, student_id: int) -> Student:
    """МЯГКОЕ удаление: is_active=false, строка остаётся.

    Физическое удалило бы записи журнала через ON DELETE CASCADE и разорвало
    уже сданные отчёты - журнал должен пережить выбывание студента.
    """
    student = await get(session, student_id)
    student.is_active = False
    await session.commit()
    await session.refresh(student)
    return student
