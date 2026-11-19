"""Преподаватели: заведение, правка, смена пароля, удаление (требование №9).

Пароль нигде не покидает этот модуль в открытом виде и никогда не уходит в
ответ: `password_hash` отсутствует в схемах чтения (см. app/schemas/teacher.py).
Хэш - bcrypt, тем же способом, что и в db/seeds.py: два способа хэширования в
одном проекте означают учётки, которые перестают входить после первой же правки.
"""

import bcrypt
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.teacher import TeacherCreate, TeacherUpdate
from db.models import Discipline, Teacher


class TeacherNotFound(Exception):
    def __init__(self, teacher_id: int) -> None:
        super().__init__(f"teacher {teacher_id} not found")
        self.teacher_id = teacher_id


class LoginTaken(Exception):
    """Логин уже занят.

    Отдельная ошибка, а не IntegrityError: UNIQUE на login есть, но отвечать
    «конфликт» без указания поля - способ заставить администратора гадать, что
    именно он ввёл не так.
    """

    def __init__(self, login: str) -> None:
        super().__init__(f"login {login!r} is already used by another teacher")
        self.login = login


class TeacherHasDisciplines(Exception):
    """У преподавателя есть дисциплины - значит, за ним стоит журнал.

    База защитила бы и сама (FK disciplines.teacher_id с ON DELETE RESTRICT),
    но RESTRICT приходит как IntegrityError без объяснения причины, а админу
    нужно знать, сколько именно дисциплин держать в голове перед удалением.
    """

    def __init__(self, teacher_id: int, disciplines: int) -> None:
        super().__init__(
            f"teacher {teacher_id} still owns {disciplines} discipline(s); "
            "reassign or delete them first"
        )
        self.teacher_id = teacher_id
        self.disciplines = disciplines


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def get(session: AsyncSession, teacher_id: int) -> Teacher:
    teacher = await session.get(Teacher, teacher_id)
    if teacher is None:
        raise TeacherNotFound(teacher_id)
    return teacher


async def list_teachers(
    session: AsyncSession,
    *,
    query: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[Teacher], int]:
    conditions = []
    if query:
        pattern = f"%{query}%"
        conditions.append(
            or_(Teacher.full_name.ilike(pattern), Teacher.login.ilike(pattern))
        )

    stmt = select(Teacher)
    count_stmt = select(func.count()).select_from(Teacher)
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = (await session.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(Teacher.full_name, Teacher.id).offset(offset).limit(limit)
    items = list((await session.execute(stmt)).scalars().all())
    return items, total


async def create(session: AsyncSession, payload: TeacherCreate) -> Teacher:
    if await session.scalar(select(Teacher).where(Teacher.login == payload.login)):
        raise LoginTaken(payload.login)

    teacher = Teacher(
        full_name=payload.full_name,
        login=payload.login,
        password_hash=hash_password(payload.password),
    )
    session.add(teacher)
    await session.commit()
    await session.refresh(teacher)
    return teacher


async def update(
    session: AsyncSession, teacher_id: int, payload: TeacherUpdate
) -> Teacher:
    """Только ФИО и логин. Пароль - в set_password, см. докстринг схемы."""
    teacher = await get(session, teacher_id)

    if payload.login is not None and payload.login != teacher.login:
        if await session.scalar(
            select(Teacher).where(Teacher.login == payload.login, Teacher.id != teacher_id)
        ):
            raise LoginTaken(payload.login)
        teacher.login = payload.login
    if payload.full_name is not None:
        teacher.full_name = payload.full_name

    await session.commit()
    await session.refresh(teacher)
    return teacher


async def set_password(
    session: AsyncSession, teacher_id: int, password: str
) -> Teacher:
    teacher = await get(session, teacher_id)
    teacher.password_hash = hash_password(password)
    await session.commit()
    await session.refresh(teacher)
    return teacher


async def remove(session: AsyncSession, teacher_id: int) -> None:
    teacher = await get(session, teacher_id)

    owned = (
        await session.execute(
            select(func.count())
            .select_from(Discipline)
            .where(Discipline.teacher_id == teacher_id)
        )
    ).scalar_one()
    if owned:
        raise TeacherHasDisciplines(teacher_id, owned)

    await session.delete(teacher)
    await session.commit()
