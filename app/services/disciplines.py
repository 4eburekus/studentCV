"""Дисциплины: справочник владельца журналов (требование №3).

Правило различимости, которое здесь защищается: дисциплину задаёт пара
«название + преподаватель». Два преподавателя вправе вести предмет с одинаковым
названием, и это не дубликат; дубликат - когда один и тот же преподаватель
заводит «Программирование» дважды. Различать их можно только по этой паре,
поэтому UNIQUE здесь составной (миграция 0004), а не по одному name.
"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.discipline import DisciplineCreate, DisciplineUpdate
from db.models import AttendanceRecord, Discipline, Lesson, Teacher


class DisciplineNotFound(Exception):
    def __init__(self, discipline_id: int) -> None:
        super().__init__(f"discipline {discipline_id} not found")
        self.discipline_id = discipline_id


class TeacherNotFound(Exception):
    def __init__(self, teacher_id: int) -> None:
        super().__init__(f"teacher {teacher_id} not found")
        self.teacher_id = teacher_id


class DuplicateDiscipline(Exception):
    def __init__(self, name: str, teacher_id: int) -> None:
        super().__init__(
            f"discipline {name!r} already exists for teacher {teacher_id}"
        )
        self.name = name
        self.teacher_id = teacher_id


class DisciplineInUse(Exception):
    """У дисциплины есть пары с записями журнала.

    Удаление дисциплины уводит за собой пары через ON DELETE CASCADE (см.
    Discipline.lessons в db/models.py), а пары - записи посещаемости. Без
    отказа один клик в админке стирал бы сданную историю, и ни один CHECK
    этому бы не помешал: каскад и есть легальный путь.
    """

    def __init__(self, discipline_id: int, lessons: int, records: int) -> None:
        super().__init__(
            f"discipline {discipline_id} has {lessons} lesson(s) with "
            f"{records} attendance record(s); delete those first"
        )
        self.discipline_id = discipline_id
        self.lessons = lessons
        self.records = records


async def get(session: AsyncSession, discipline_id: int) -> Discipline:
    discipline = await session.get(Discipline, discipline_id)
    if discipline is None:
        raise DisciplineNotFound(discipline_id)
    return discipline


async def teacher_name(session: AsyncSession, teacher_id: int) -> str | None:
    """Имя владельца для ответа одиночного CRUD-объекта."""
    return await session.scalar(select(Teacher.full_name).where(Teacher.id == teacher_id))


async def get_with_teacher(
    session: AsyncSession, discipline_id: int
) -> tuple[Discipline, str | None]:
    discipline = await get(session, discipline_id)
    return discipline, await teacher_name(session, discipline.teacher_id)


async def list_disciplines(
    session: AsyncSession,
    *,
    teacher_id: int | None = None,
    query: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[tuple[Discipline, str]], int]:
    """Дисциплины вместе с ФИО преподавателя - одним запросом.

    Имя преподавателя нужно списку на фронте (колонка «Преподаватель»), и
    брать его отдельным запросом на строку означало бы N+1 ровно там, где
    список заведомо короткий и JOIN дешевле.
    """
    conditions = []
    if teacher_id is not None:
        conditions.append(Discipline.teacher_id == teacher_id)
    if query:
        conditions.append(Discipline.name.ilike(f"%{query}%"))

    base = select(Discipline, Teacher.full_name).join(
        Teacher, Teacher.id == Discipline.teacher_id
    )
    count_stmt = select(func.count()).select_from(Discipline)
    for condition in conditions:
        base = base.where(condition)
        count_stmt = count_stmt.where(condition)

    total = (await session.execute(count_stmt)).scalar_one()
    stmt = (
        base.order_by(Discipline.name, Discipline.id).offset(offset).limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(row[0], row[1]) for row in rows], total


async def create(session: AsyncSession, payload: DisciplineCreate) -> Discipline:
    if not await session.get(Teacher, payload.teacher_id):
        raise TeacherNotFound(payload.teacher_id)

    discipline = Discipline(name=payload.name, teacher_id=payload.teacher_id)
    session.add(discipline)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateDiscipline(payload.name, payload.teacher_id) from exc
    await session.refresh(discipline)
    return discipline


async def update(
    session: AsyncSession, discipline_id: int, payload: DisciplineUpdate
) -> Discipline:
    discipline = await get(session, discipline_id)

    new_name = payload.name if payload.name is not None else discipline.name
    new_teacher = (
        payload.teacher_id if payload.teacher_id is not None else discipline.teacher_id
    )

    if payload.teacher_id is not None and not await session.get(
        Teacher, payload.teacher_id
    ):
        raise TeacherNotFound(payload.teacher_id)

    if (new_name, new_teacher) != (discipline.name, discipline.teacher_id):
        clash = await session.scalar(
            select(Discipline).where(
                Discipline.name == new_name,
                Discipline.teacher_id == new_teacher,
                Discipline.id != discipline_id,
            )
        )
        if clash:
            raise DuplicateDiscipline(new_name, new_teacher)

    discipline.name = new_name
    discipline.teacher_id = new_teacher
    await session.commit()
    await session.refresh(discipline)
    return discipline


async def remove(session: AsyncSession, discipline_id: int) -> None:
    discipline = await get(session, discipline_id)

    lessons = (
        await session.execute(
            select(func.count()).select_from(Lesson).where(
                Lesson.discipline_id == discipline_id
            )
        )
    ).scalar_one()

    records = (
        await session.execute(
            select(func.count())
            .select_from(AttendanceRecord)
            .join(Lesson, Lesson.id == AttendanceRecord.lesson_id)
            .where(Lesson.discipline_id == discipline_id)
        )
    ).scalar_one()

    if records:
        raise DisciplineInUse(discipline_id, lessons, records)

    # Пар без записей журнала удалять можно: каскад уберёт их, и история
    # посещаемости от этого не потеряется - её ещё нет.
    await session.delete(discipline)
    await session.commit()
