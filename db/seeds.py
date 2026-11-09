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


async def get_or_create_lessons(
    session: AsyncSession, discipline: Discipline
) -> list[Lesson]:
    """Пары на учебную неделю: 7 слотов в понедельник, 5 - во вторник."""
    monday = next_monday(date.today())
    lessons: list[Lesson] = []

    for day_offset, slot_indexes in ((0, range(0, 7)), (1, range(0, 5))):
        lesson_date = monday + timedelta(days=day_offset)
        for slot_index in slot_indexes:
            start_time, end_time = LESSON_SLOTS[slot_index]
            lesson = await session.scalar(
                select(Lesson).where(
                    Lesson.discipline_id == discipline.id,
                    Lesson.lesson_date == lesson_date,
                    Lesson.start_time == start_time,
                )
            )
            if lesson is None:
                lesson = Lesson(
                    discipline_id=discipline.id,
                    lesson_date=lesson_date,
                    start_time=start_time,
                    end_time=end_time,
                )
                session.add(lesson)
                await session.flush()
                print("created lesson:", lesson_date, start_time)
            else:
                print("lesson exists:", lesson_date, start_time)
            lessons.append(lesson)
    return lessons


async def get_or_create_attendance(
    session: AsyncSession,
    students: list[Student],
    lessons: list[Lesson],
) -> None:
    """Несколько записей журнала, включая случай LATE с delay_minutes."""
    if not students or not lessons:
        return

    entries = [
        # (студент, пара, статус, минуты опоздания)
        (students[0], lessons[0], AttendanceStatus.PRESENT, None),
        (students[1], lessons[0], AttendanceStatus.LATE, 12),
        (students[2], lessons[1], AttendanceStatus.PRESENT, None),
    ]

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
    """Пара тестовых путей в MinIO - реальных файлов пока нет."""
    if not students:
        return
    student = students[0]
    photo_url = "biometrics/demo-0001.jpg"
    photo = await session.scalar(
        select(StudentPhoto).where(StudentPhoto.photo_url == photo_url)
    )
    if photo is None:
        session.add(StudentPhoto(student_id=student.id, photo_url=photo_url))
        print("created photo:", photo_url)
    else:
        print("photo exists:", photo_url)


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
