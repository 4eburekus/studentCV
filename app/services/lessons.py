"""Расписание пар: чтение и редактирование.

Раньше здесь было только чтение, а создание пар относилось к «отдельному
контуру». Контур настал: админ-панель заводит расписание, и оставить создание
в сидах означало бы, что пару можно изменить только переписывая базу руками.

`LessonNotFound` и `get_lesson` объявлены именно здесь - это ресурс
расписания. app/services/attendance.py импортирует их отсюда, а не держит
свои: два класса с одним именем - способ получить `except LessonNotFound`,
который не ловит исключение, брошенное другим модулем.
"""

from datetime import date, time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.lesson import LessonCreate, LessonUpdate
from app.services.students import validate_group_number
from db.models import AttendanceRecord, Discipline, Lesson, Student


class LessonNotFound(Exception):
    def __init__(self, lesson_id: int) -> None:
        super().__init__(f"lesson {lesson_id} not found")
        self.lesson_id = lesson_id


class DisciplineNotFound(Exception):
    def __init__(self, discipline_id: int) -> None:
        super().__init__(f"discipline {discipline_id} not found")
        self.discipline_id = discipline_id


class InvalidLessonWindow(Exception):
    """Конец пары не позже начала.

    Дублирует CHECK end_time > start_time осознанно: тот сработает при commit
    и прилетит как IntegrityError без указания поля. Админу нужен 422 с
    понятным текстом до похода в базу, а не «conflict».
    """

    def __init__(self, lesson_id: int | None = None) -> None:
        super().__init__(
            "lesson end_time must be after start_time"
            + (f" (lesson {lesson_id})" if lesson_id else "")
        )
        self.lesson_id = lesson_id


class LessonClosed(Exception):
    def __init__(self, lesson_id: int) -> None:
        super().__init__(f"lesson {lesson_id} is already closed")
        self.lesson_id = lesson_id


class LessonConflict(Exception):
    def __init__(self, discipline_id: int, group_number: str, lesson_date: date, start_time: time) -> None:
        super().__init__(
            f"lesson slot is already occupied: discipline={discipline_id}, "
            f"group={group_number}, date={lesson_date}, start={start_time}"
        )


class LessonHasRecords(Exception):
    def __init__(self, lesson_id: int, records: int) -> None:
        super().__init__(f"lesson {lesson_id} has {records} attendance record(s)")
        self.lesson_id = lesson_id
        self.records = records


async def get_lesson(session: AsyncSession, lesson_id: int) -> Lesson:
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise LessonNotFound(lesson_id)
    return lesson


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


async def create(session: AsyncSession, payload: LessonCreate) -> Lesson:
    validate_group_number(payload.group_number)
    if not await session.get(Discipline, payload.discipline_id):
        raise DisciplineNotFound(payload.discipline_id)

    stmt = select(Lesson.id).where(
        Lesson.discipline_id == payload.discipline_id,
        Lesson.group_number == payload.group_number,
        Lesson.lesson_date == payload.lesson_date,
        Lesson.start_time == payload.start_time,
    )
    if await session.scalar(stmt):
        raise LessonConflict(
            payload.discipline_id,
            payload.group_number,
            payload.lesson_date,
            payload.start_time,
        )

    lesson = Lesson(
        discipline_id=payload.discipline_id,
        group_number=payload.group_number,
        lesson_date=payload.lesson_date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        room_number=payload.room_number,
    )
    session.add(lesson)
    await session.commit()
    await session.refresh(lesson)
    return lesson


async def update(
    session: AsyncSession, lesson_id: int, payload: LessonUpdate
) -> Lesson:
    lesson = await get_lesson(session, lesson_id)

    # Закрытую пару нельзя переводить в другую группу или менять её время:
    # ABSENT уже выставлен по старым границам, и расхождение между списком
    # студентов и временем закрытия превратит журнал в набор противоречий.
    if lesson.closed_at is not None:
        frozen = (
            payload.group_number not in (None, lesson.group_number),
            payload.lesson_date not in (None, lesson.lesson_date),
            payload.start_time not in (None, lesson.start_time),
            payload.end_time not in (None, lesson.end_time),
        )
        if any(frozen):
            raise LessonClosed(lesson_id)

    if payload.group_number is not None:
        validate_group_number(payload.group_number)
    if payload.discipline_id is not None and payload.discipline_id != lesson.discipline_id:
        if not await session.get(Discipline, payload.discipline_id):
            raise DisciplineNotFound(payload.discipline_id)

    # Присваивание по «передано / не передано», а не через `or`: для
    # room_number это не косметика. `payload.room_number or lesson.room_number`
    # превратил бы явное очищение аудитории ("" или None) в тихое «оставить
    # как было», и админ не смог бы снять назначенный кабинет вовсе.
    if payload.discipline_id is not None:
        lesson.discipline_id = payload.discipline_id
    if payload.group_number is not None:
        lesson.group_number = payload.group_number
    if payload.lesson_date is not None:
        lesson.lesson_date = payload.lesson_date
    if payload.start_time is not None:
        lesson.start_time = payload.start_time
    if payload.end_time is not None:
        lesson.end_time = payload.end_time
    if "room_number" in payload.model_fields_set:
        lesson.room_number = payload.room_number

    # Порядок полей после присваивания: CHECK end_time > start_time живёт в
    # базе, и менять время без проверки здесь означало бы ловить IntegrityError
    # вместо внятного ответа.
    if lesson.end_time <= lesson.start_time:
        raise InvalidLessonWindow(lesson_id)

    await session.commit()
    await session.refresh(lesson)
    return lesson


async def delete(session: AsyncSession, lesson_id: int) -> None:
    lesson = await get_lesson(session, lesson_id)

    records = (
        await session.execute(
            select(func.count())
            .select_from(AttendanceRecord)
            .where(AttendanceRecord.lesson_id == lesson_id)
        )
    ).scalar_one()
    if records:
        raise LessonHasRecords(lesson_id, records)

    await session.delete(lesson)
    await session.commit()


async def students_in_group(session: AsyncSession, group_number: str) -> int:
    """Сколько активных студентов в группе.

    Нулевой результат не блокирует создание пары: группа может быть заведена
    заранее, до импорта списка. Но фронт обязан показать это предупреждением,
    иначе админ получит «пары нет в расписании» вместо «на пару никто не
    записан».
    """
    return (
        await session.execute(
            select(func.count())
            .select_from(Student)
            .where(Student.group_number == group_number, Student.is_active.is_(True))
        )
    ).scalar_one()
