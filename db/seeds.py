"""Идемпотентные сиды: демо-данные для разработки и проверки схемы.

Запуск:  python -m db.seeds
Повторный запуск не должен падать с IntegrityError - все вставки
сначала проверяются на наличие.

Пароль преподавателя: Teacher123! (только для локальной разработки).
"""

import asyncio
from datetime import date, datetime, time, timedelta

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.enums import AttendanceStatus
from db.models import (
    AttendanceRecord,
    Discipline,
    Lesson,
    Student,
    StudentPhoto,
    Teacher,
)
from db.session import SessionLocal, dispose_engine

TEACHER_LOGIN = "teacher"
TEACHER_PASSWORD = "Teacher123!"

# Шаблонное расписание времени пар из README
LESSON_SLOTS = [
    (time(8, 30), time(10, 0)),
    (time(10, 10), time(11, 40)),
    (time(11, 50), time(13, 20)),
    (time(14, 0), time(15, 30)),
    (time(15, 40), time(17, 10)),
    (time(17, 20), time(18, 50)),
    (time(19, 0), time(20, 30)),
]

STUDENTS = [
    ("Иванов Иван Иванович", "01-ФИИтт-01"),
    ("Петрова Анна Сергеевна", "01-ФИИтт-01"),
    ("Сидоров Пётр Алексеевич", "02-ТИПП-02"),
    ("Кузнецова Мария Игоревна", "02-ТИПП-02"),
]

DISCIPLINE_NAME = "Основы программирования"


def hash_password(password: str) -> str:
    """bcrypt-хэш пароля (не путать с sha256)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def get_or_create_teacher(session: AsyncSession) -> Teacher:
    teacher = await session.scalar(
        select(Teacher).where(Teacher.login == TEACHER_LOGIN)
    )
    if teacher is None:
        teacher = Teacher(
            full_name="Смирнов Алексей Петрович",
            login=TEACHER_LOGIN,
            password_hash=hash_password(TEACHER_PASSWORD),
        )
        session.add(teacher)
        await session.flush()
        print("created teacher:", teacher.login)
    else:
        print("teacher exists:", teacher.login)
    return teacher


async def get_or_create_students(session: AsyncSession) -> list[Student]:
    result: list[Student] = []
    for full_name, group_number in STUDENTS:
        student = await session.scalar(
            select(Student).where(
                Student.full_name == full_name,
                Student.group_number == group_number,
            )
        )
        if student is None:
            student = Student(full_name=full_name, group_number=group_number)
            session.add(student)
            await session.flush()
            print("created student:", full_name, group_number)
        else:
            print("student exists:", full_name, group_number)
        result.append(student)
    return result


async def get_or_create_discipline(
    session: AsyncSession, teacher: Teacher
) -> Discipline:
    discipline = await session.scalar(
        select(Discipline).where(
            Discipline.name == DISCIPLINE_NAME,
            Discipline.teacher_id == teacher.id,
        )
    )
    if discipline is None:
        discipline = Discipline(name=DISCIPLINE_NAME, teacher_id=teacher.id)
        session.add(discipline)
        await session.flush()
        print("created discipline:", DISCIPLINE_NAME)
    else:
        print("discipline exists:", DISCIPLINE_NAME)
    return discipline


def next_monday(today: date) -> date:
    """Понедельник ближайшей учебной недели (сегодняшний понедельник - тоже)."""
    return today + timedelta(days=(7 - today.weekday()) % 7)


def groups_in_students() -> list[str]:
    """Группы демо-студентов в порядке объявления, без повторов."""
    return list(dict.fromkeys(group_number for _, group_number in STUDENTS))


async def get_or_create_lessons(
    session: AsyncSession, discipline: Discipline
) -> list[Lesson]:
    """Пары на учебную неделю: 7 слотов в понедельник, 5 - во вторник.

    Каждая группа получает ОДИНАКОВОЕ расписание. Это не лень, а демонстрация:
    одна дисциплина в один слот у двух групп стала возможной только после того,
    как группа вошла в UNIQUE ключ пары; со старым ключом вторая группа давала
    IntegrityError.
    """
    monday = next_monday(date.today())
    lessons: list[Lesson] = []

    for group_number in groups_in_students():
        for day_offset, slot_indexes in ((0, range(0, 7)), (1, range(0, 5))):
            lesson_date = monday + timedelta(days=day_offset)
            for slot_index in slot_indexes:
                start_time, end_time = LESSON_SLOTS[slot_index]
                lesson = await session.scalar(
                    select(Lesson).where(
                        Lesson.discipline_id == discipline.id,
                        Lesson.group_number == group_number,
                        Lesson.lesson_date == lesson_date,
                        Lesson.start_time == start_time,
                    )
                )
                if lesson is None:
                    lesson = Lesson(
                        discipline_id=discipline.id,
                        group_number=group_number,
                        lesson_date=lesson_date,
                        start_time=start_time,
                        end_time=end_time,
                    )
                    session.add(lesson)
                    await session.flush()
                    print("created lesson:", group_number, lesson_date, start_time)
                else:
                    print("lesson exists:", group_number, lesson_date, start_time)
                lessons.append(lesson)
    return lessons


async def get_or_create_attendance(
    session: AsyncSession,
    students: list[Student],
    lessons: list[Lesson],
) -> None:
    """Несколько записей журнала, включая случай LATE с delay_minutes.

    Пару берём ТОЛЬКО своей группы: после того как ABSENT стал записью,
    запись чужой группы означала бы «студент сходил на пару, которой у него
    нет», и закрытие такой пары никогда бы её не поправило.
    """
    if not students or not lessons:
        return

    def first_lessons_of(group_number: str) -> list[Lesson]:
        return [lesson for lesson in lessons if lesson.group_number == group_number]

    own: dict[str, list[Lesson]] = {
        group: first_lessons_of(group) for group in groups_in_students()
    }

    entries = []
    for student, index, status, delay in (
        (students[0], 0, AttendanceStatus.PRESENT, None),
        (students[1], 0, AttendanceStatus.LATE, 12),
        (students[2], 1, AttendanceStatus.PRESENT, None),
    ):
        group_lessons = own.get(student.group_number) or []
        if index >= len(group_lessons):
            continue
        entries.append((student, group_lessons[index], status, delay))

    if not entries:
        print("attendance skipped: no lessons for the seeded groups")
        return

    for student, lesson, status, delay in entries:
        record = await session.scalar(
            select(AttendanceRecord).where(
                AttendanceRecord.student_id == student.id,
                AttendanceRecord.lesson_id == lesson.id,
            )
        )
        if record is not None:
            print("attendance exists:", student.full_name, lesson.lesson_date)
            continue

        start_dt = datetime.combine(lesson.lesson_date, lesson.start_time)
        entry_time = start_dt
        if delay is not None:
            entry_time = start_dt + timedelta(minutes=delay)

        session.add(
            AttendanceRecord(
                student_id=student.id,
                lesson_id=lesson.id,
                entry_time=entry_time,
                status=status,
                delay_minutes=delay,
            )
        )
        print("created attendance:", student.full_name, status.name)


async def get_or_create_photos(
    session: AsyncSession, students: list[Student]
) -> None:
    """Эталонные фото сидами НЕ создаются.

    С среза MinIO фото - не строка в БД, а объект в бакете: ключ
    biometrics/<uuid4>.jpg проходит CHECK по формату, но ссылка на
    несуществующий объект была бы хуже отсутствия данных (CV-модуль
    молча терял бы эталон). Поэтому эталоны заводятся только через
    POST /students/{id}/photos, который кладёт байты и пишет content_hash.
    Функция оставлена пустой, чтобы не менять порядок вызовов main().
    """
    return None


async def main() -> None:
    async with SessionLocal() as session:
        try:
            teacher = await get_or_create_teacher(session)
            students = await get_or_create_students(session)
            discipline = await get_or_create_discipline(session, teacher)
            lessons = await get_or_create_lessons(session, discipline)
            await get_or_create_attendance(session, students, lessons)
            await get_or_create_photos(session, students)
            await session.commit()
            print("seeds committed")
        except Exception:
            await session.rollback()
            raise
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
