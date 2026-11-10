"""Чтение расписания пар.

Расписание в этом срезе только читается: CV-модулю нужна пара, чтобы
поставить событие, преподавателю - список пар за день. Создание пар -
отдельный контур (будущий срез редактирования расписания).
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Discipline, Lesson


class LessonFilterError(Exception):
    pass


async def list_lessons(
    session: AsyncSession,
    *,
    discipline_id: int | None = None,
    lesson_date: date | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[tuple[Lesson, str | None]], int]:
    """Пары с именем дисциплины одним запросом.

    Возвращаем пары вместе с названием дисциплины, а не только Lesson:
    без этого фронтенд делал бы N+1 запросов за именами.
    """
    conditions = []
    if discipline_id is not None:
        conditions.append(Lesson.discipline_id == discipline_id)
    if lesson_date is not None:
        conditions.append(Lesson.lesson_date == lesson_date)

    base = (
        select(Lesson, Discipline.name)
        .join(Discipline, Discipline.id == Lesson.discipline_id)
    )
    count_stmt = select(func.count()).select_from(Lesson)
    for condition in conditions:
        base = base.where(condition)
        count_stmt = count_stmt.where(condition)

    total = (await session.execute(count_stmt)).scalar_one()
    stmt = (
        base.order_by(Lesson.lesson_date, Lesson.start_time)
        .offset(offset)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(row[0], row[1]) for row in rows], total
