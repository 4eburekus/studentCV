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
    group_number: str | None = None,
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
    # Фильтр по группе обязателен: теперь у одной дисциплины в один слот
    # столько пар, сколько групп её посещают. Без него «расписание на сегодня»
    # смешал бы группы в одну простыню.
    if group_number is not None:
        conditions.append(Lesson.group_number == group_number)

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
        base.order_by(
            # tie-breaker по group_number/id: после того как группа вошла в
            # ключ пары, у разных групп равные (lesson_date, start_time). Без
            # полного упорядочивания Postgres вправе менять их порядок от
            # запроса к запросу, и «первая пара» поплыла бы и в тестах, и на
            # фронте.
            Lesson.lesson_date,
            Lesson.start_time,
            Lesson.group_number,
            Lesson.id,
        )
        .offset(offset)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(row[0], row[1]) for row in rows], total
