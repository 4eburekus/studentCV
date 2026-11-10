"""Журнал посещаемости: классификация прохода и upsert по UNIQUE.

Правила зафиксированы договорённостью 10.11.2026 (требования №4, №5, №7):

 - раньше начала пары                  -> PRESENT, delay_minutes NULL
 - ровно в начало и позже, но раньше
   конца пары                          -> LATE, delay_minutes >= 0
   (ровно в начало = LATE с 0 минутами - согласовано явно)
 - не раньше конца пары                -> НЕ записываем, студент остаётся ABSENT
 - при повторной доставке побеждает
   САМОЕ РАННЕЕ время входа            -> позднее событие не перебивает раннее
 - запись с is_manually_edited=true    -> автоматическое событие её не трогает

Логика отделена от HTTP сознательно: тот же register() вызывается и из
эндпоинта-приёмника, и из будущей Celery-задачи, и из тестов.
"""

import math
from datetime import date, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services import storage
from app.services.students import get as get_student
from db.enums import AttendanceStatus
from db.models import AttendanceRecord, Discipline, Lesson, Student


class LessonNotFound(Exception):
    def __init__(self, lesson_id: int) -> None:
        super().__init__(f"lesson {lesson_id} not found")
        self.lesson_id = lesson_id


class InactiveStudent(Exception):
    def __init__(self, student_id: int) -> None:
        super().__init__(f"student {student_id} is not active")
        self.student_id = student_id


class InvalidFrameKey(Exception):
    """Ключ кадра не соответствует контракту frames/<lesson_id>/<uuid4>.jpg.

    Отдельно от FrameMissing: это ошибка контракта на стороне CV-процесса,
    а не отсутствующий файл. Различать важно: «кадра нет» обычно значит
    гонку (файл ещё не дописан), а неверный формат - сломанный код.
    """

    def __init__(self, key: str) -> None:
        super().__init__(
            f"frame_object_key {key!r} does not match the required format "
            "frames/<lesson_id>/<uuid4>.jpg"
        )
        self.key = key


class FrameMissing(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(f"frame object {key} not found in storage")
        self.key = key


# Исходы обработки события - машиночитаемые константы. CV-процесс и фронтенд
# обязаны отличать «записали» от «проигнорировали по правилу» без разбора
# текста сообщения: текст меняет формулировку, константа - нет.
OUTCOME_RECORDED = "recorded"  # создали запись или обновили её более ранним входом
OUTCOME_KEPT_EARLIER_ENTRY = "kept_earlier_entry"
OUTCOME_KEPT_MANUAL_EDIT = "kept_manual_edit"
OUTCOME_IGNORED_AFTER_END = "ignored_after_lesson_end"


def _as_aware(value: datetime) -> datetime:
    """Naive-время трактуем как UTC.

    Pydantic пропустит naive-значения от кривого клиента; сравнение naive с
    aware бросило бы TypeError уже в арифметике, а молча неверный знак
    разницы дал бы неправильное опоздание в журнале.
    """
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def classify(
    captured_at: datetime,
    lesson_start: time,
    lesson_end: time,
    lesson_date: date,
) -> tuple[AttendanceStatus, int | None] | None:
    """Статус и минуты опоздания. None - «событие не записываем».

    ДАТА границы берётся из lesson_date, а не из captured_at.date(): событие
    может прийти с другим днём (пересланное вчера, сбитые часы CV-процесса),
    и раньше мы сравнивали его с границами этого же другого дня, то есть не с
    той парой. Авторитет у расписания.

    Зона - из приходящего времени: расписание хранит naive Time/Date без зоны
    (вопрос вынесен в §9 плана).
    """
    captured_at = _as_aware(captured_at)
    start_dt = datetime.combine(lesson_date, lesson_start, tzinfo=captured_at.tzinfo)
    end_dt = datetime.combine(lesson_date, lesson_end, tzinfo=captured_at.tzinfo)

    if captured_at >= end_dt:
        # Вход после конца пары: по правилу 10.11.2026 такой студент на эту
        # пару не приходил. Строка с LATE на сотни минут исказила бы журнал.
        return None

    delta_seconds = (captured_at - start_dt).total_seconds()
    if delta_seconds < 0:
        return AttendanceStatus.PRESENT, None

    # delta == 0 (ровно в начало) - LATE с 0 минутами. Действующий CHECK
    # (delay_minutes >= 0 и LATE <=> NOT NULL) это допускает, схема не меняется.
    return AttendanceStatus.LATE, max(0, math.ceil(delta_seconds / 60))


async def get_lesson(session: AsyncSession, lesson_id: int) -> Lesson:
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise LessonNotFound(lesson_id)
    return lesson


async def _reload_record(
    session: AsyncSession,
    *,
    record_id: int | None = None,
    student_id: int | None = None,
    lesson_id: int | None = None,
) -> AttendanceRecord:
    """Перечитывает запись из базы, а не из identity map.

    Это не перестраховка, а исправление реальной ошибки. get_student() тянет
    attendance_records через lazy="selectin" и кладёт их в identity map
    session'а. После ON CONFLICT DO UPDATE обычный session.get()/select()
    вернул бы ЗАКЭШИРОВАННЫЙ объект со СТАРЫМИ значениями: сессия у нас с
    expire_on_commit=False, поэтому commit ничего не инвалидирует. Наружу
    уходил ответ, не соответствующий базе (именно так себя и проявлял
    «красный» тест: статус оставался LATE 5, хотя в строке было записано
    другое). populate_existing заставляет выполнить реальный SELECT.
    """
    stmt = select(AttendanceRecord).execution_options(populate_existing=True)
    if record_id is not None:
        stmt = stmt.where(AttendanceRecord.id == record_id)
    else:
        stmt = stmt.where(
            AttendanceRecord.student_id == student_id,
            AttendanceRecord.lesson_id == lesson_id,
        )
    return (await session.execute(stmt)).scalar_one()


async def register(
    session: AsyncSession,
    *,
    lesson_id: int,
    student_id: int,
    captured_at: datetime,
    frame_object_key: str,
    check_frame: bool = True,
) -> tuple[AttendanceRecord | None, str, Lesson]:
    """Приём события распознавания: upsert по (student_id, lesson_id).

    Порядок проверок: сначала данные (студент, пара), затем формат ключа, и
    только потом обращение к хранилищу. Данные - раньше не из экономии: если
    проверить кадр до пары, то запрос с несуществующей парой и чужим ключом
    получил бы 422 вместо честного 404, и CV-процесс искал бы проблему не там.
    Формат ключа держим перед сетевым вызовом - он дешёвый и отсеивает
    сломанный код клиента без похода в бакет.

    check_frame=False - для тестов логики без хранилища; в эндпоинте всегда True.
    Возвращает (запись | None, исход, пара); None - событие отброшено по правилу.
    """
    student = await get_student(session, student_id)
    if not student.is_active:
        raise InactiveStudent(student_id)

    lesson = await get_lesson(session, lesson_id)

    if check_frame:
        # Формат проверяем до обращения к хранилищу: мусорный ключ - ошибка
        # контракта CV-процесса, и отвечать на неё «кадра нет» было бы неверно.
        if not storage.is_frame_key(frame_object_key):
            raise InvalidFrameKey(frame_object_key)
        settings = get_settings()
        if not await storage.object_exists(settings.s3_bucket_frames, frame_object_key):
            raise FrameMissing(frame_object_key)

    captured_at = _as_aware(captured_at)

    verdict = classify(captured_at, lesson.start_time, lesson.end_time, lesson.lesson_date)
    if verdict is None:
        # Кадр остаётся в бакете, строки нет: по этой паре студент ABSENT.
        return None, OUTCOME_IGNORED_AFTER_END, lesson

    status, delay = verdict

    # Условия обновления:
    #   entry_time > EXCLUDED.entry_time  - «побеждает ранний вход»: обновляем
    #                                       только если новый проход РАНЬШЕ
    #                                       записанного;
    #   is_manually_edited = FALSE        - защиту ручной правки (требование №7)
    #                                       ставим сюда же, через AND: правка
    #                                       преподавателя важнее любого кадра,
    #                                       даже более раннего.
    # Когда условие не выполнено, Postgres даёт INSERT 0 0 - строк нет, и это
    # осмысленный исход, а не ошибка (ветка ниже).
    stmt = (
        pg_insert(AttendanceRecord)
        .values(
            student_id=student_id,
            lesson_id=lesson_id,
            entry_time=captured_at,
            status=status,
            delay_minutes=delay,
            is_manually_edited=False,
            edited_at=None,
        )
        .on_conflict_do_update(
            index_elements=["student_id", "lesson_id"],
            set_={
                "entry_time": captured_at,
                "status": status,
                "delay_minutes": delay,
            },
            where=(
                AttendanceRecord.is_manually_edited.is_(False)
                & (AttendanceRecord.entry_time > captured_at)
            ),
        )
        # id затронутой строки. Признак «вставлено vs обновлено» (xmax = 0)
        # здесь не нужен: по контракту оба случая - это recorded, а различие
        # «создали или оставили как было» даёт ноль затронутых строк.
        .returning(AttendanceRecord.id)
    )

    row = (await session.execute(stmt)).first()

    if row is not None:
        # Строка вставлена или обновлена более ранним входом - оба случая
        # означают «данные записи изменились нашим событием».
        await session.commit()
        record = await _reload_record(session, record_id=row[0])
        return record, OUTCOME_RECORDED, lesson

    # Строк не затронуто. Причина одна из двух, и для CV-процесса они значат
    # разное, поэтому различаем их по флагу уже существующей записи.
    record = await _reload_record(
        session, student_id=student_id, lesson_id=lesson_id
    )
    outcome = (
        OUTCOME_KEPT_MANUAL_EDIT
        if record.is_manually_edited
        else OUTCOME_KEPT_EARLIER_ENTRY
    )
    await session.commit()
    return record, outcome, lesson


async def journal_for_lesson(
    session: AsyncSession, lesson_id: int
) -> tuple[Lesson, str, list[tuple[AttendanceRecord, Student]]]:
    """Журнал пары одним запросом: пара, дисциплина, записи со студентами.

    Раньше здесь был N+1 (студент на каждую запись) - на группе из 30 человек
    это 30 лишних round-trip на каждую выдачу журнала.
    Отсутствие записи = ABSENT: пустые строки не заводим.
    """
    lesson = await get_lesson(session, lesson_id)

    discipline_name = (
        await session.execute(
            select(Discipline.name).where(Discipline.id == lesson.discipline_id)
        )
    ).scalar_one()

    result = await session.execute(
        select(AttendanceRecord, Student)
        .join(Student, Student.id == AttendanceRecord.student_id)
        .where(AttendanceRecord.lesson_id == lesson_id)
        .order_by(AttendanceRecord.entry_time)
    )
    pairs = [(row[0], row[1]) for row in result.all()]
    return lesson, discipline_name, pairs
