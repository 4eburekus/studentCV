"""Схемы посещаемости: событие от CV-модуля и журнал пары."""

from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from db.enums import AttendanceStatus

# Исходы обработки события. Literal, а не str: OpenAPI отдаёт enum, и фронт
# получает список допустимых значений в контракте, а не в переписке.
# Значения совпадают с константами в app/services/attendance.py - сводятся
# в одном месте (см. app.api.endpoints.attendance), расхождение здесь
# проявится как нераспознанный статус на клиенте.
Outcome = Literal[
    "recorded",
    "kept_earlier_entry",
    "kept_manual_edit",
    "ignored_after_lesson_end",
]


class AttendanceEventCreate(BaseModel):
    """Контракт приёмника (веха 5): событие + ссылка на кадр в хранилище."""

    lesson_id: int = Field(gt=0)
    student_id: int = Field(gt=0)
    captured_at: datetime = Field(
        description="Момент распознавания, с временной зоной (timestamptz)"
    )
    frame_object_key: str = Field(
        min_length=1,
        max_length=512,
        description="Ключ кадра в бакете frames: frames/<lesson_id>/<uuid4>.jpg",
    )


class AttendanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    lesson_id: int
    # None у ABSENT: времени входа не было. Схема обязана это пропускать, иначе
    # первая же ABSENT-строка в журнале дала бы ValidationError и HTTP 500.
    entry_time: datetime | None = None
    status: AttendanceStatus
    delay_minutes: int | None = None
    # Адрес доказательного снимка того входа, который здесь засчитан. None у
    # ABSENT от закрытия пары (события не было) и у строк до этой правки.
    frame_object_key: str | None = None
    is_manually_edited: bool
    # Момент ручной правки; None у записей, которые правили только автоматикой.
    # Нужен журналу как «когда это изменили», иначе отметка выглядит свежее,
    # чем она есть на самом деле.
    edited_at: datetime | None = None
    created_at: datetime


class AttendanceEventResult(BaseModel):
    """Ответ приёмника: исход и, если записали, сама запись.

    record = None означает «событие принято, но по правилу не записано»
    (вход после конца пары). Это НЕ ошибка: данные валидны, их сознательно
    не учитываем, поэтому 200, а не 4xx.
    """

    record: AttendanceRead | None = None
    outcome: Outcome = Field(
        description=(
            "recorded - создана или обновлена запись; "
            "kept_earlier_entry - оставлен более ранний вход; "
            "kept_manual_edit - запись правили руками, не трогали; "
            "ignored_after_lesson_end - вход после конца пары, отметка "
            "о посещении не ставится (строка может быть ABSENT от закрытия)"
        )
    )
    lesson_start: time | None = Field(
        default=None, description="Начало пары: от него считан delay_minutes"
    )
    delay_minutes: int | None = None


class AttendanceRecordUpdate(BaseModel):
    """Ручная правка записи журнала (требование №7).

    Принимается только статус и время. delay_minutes здесь нет СОЗНАТЕЛЬНО:
    он производная от времени, и приняв его от клиента мы получили бы журнал,
    где за один и тот же вход написано «пришёл в 9:15» и «опоздал на 5 минут».
    Минуты считает сервер той же формулой, что и автоматика.

    Время вне календарных суток пары отвергается (422) - это защита от
    опечатки в дате. А вот время ПОСЛЕ конца пары разрешено намеренно:
    правило «не позже конца пары» ограничивает автоматику, а ручная правка
    существует именно для исключений из него (форс-мажор, сбой камеры,
    опоздание, которое преподаватель засчитал).
    """

    status: AttendanceStatus
    # Обязателен NULL ровно у ABSENT - это требует CHECK в БД, и схема
    # не должна давать клиенту прислать время вместе с отсутствием.
    entry_time: datetime | None = None


class AttendanceRecordSet(BaseModel):
    """Ручная отметка «по паре и студенту» - создаёт запись, если её нет.

    Нужен именно этот вход, а не только PATCH по record_id: до закрытия пары
    у студента без отметки записи нет, и править по идентификатору нечего -
    в журнале он висит как «Не отмечен». Требование №7 говорит
    «добавление/редактирование», и POST закрывает первую половину.
    """

    lesson_id: int = Field(ge=1)
    student_id: int = Field(ge=1)
    status: AttendanceStatus
    entry_time: datetime | None = None


class AttendanceRecordUpdateResult(BaseModel):
    """Что стало с записью после правки.

    delay_minutes возвращается отдельным полем, а не только внутри record,
    потому что именно его UI показывает преподавателю сразу после сохранения
    и ему нужно сверить, что сервер посчитал то же, что он имел в виду.
    """

    record: AttendanceRead
    delay_minutes: int | None = Field(
        default=None, description="Посчитано сервером, не принято из запроса"
    )
    edited_at: datetime


class JournalEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    full_name: str
    group_number: str
    entry_time: datetime | None = None
    status: AttendanceStatus
    delay_minutes: int | None = None
    # Признак ручной правки в журнале обязателен: преподаватель должен видеть,
    # какая отметка поставлена руками, а какая пришла с камеры.
    is_manually_edited: bool = False
    # Ключ кадра в журнале нужен ровно для одного: открыть снимок у спорной
    # отметки перед тем, как править её руками (задача 3.3.1).
    frame_object_key: str | None = None
    # Правка снимает кадр, поэтому в журнале это видно сразу: «вручную, кадра
    # нет» означает, что отметку поставил человек.
    edited_at: datetime | None = None


class Journal(BaseModel):
    lesson_id: int
    discipline_name: str
    lesson_date: str
    start_time: str
    group_number: str = Field(
        description="Группа, для которой пара: из неё считается состав журнала"
    )
    end_time: str = Field(
        description="Конец пары: по нему журнал отличает опоздавших от "
        "тех, кто пришёл слишком поздно и не учтён"
    )
    closed_at: str | None = Field(
        default=None,
        description="Момент закрытия пары (когда проставлены ABSENT); "
        "None - пара ещё не закрыта",
    )
    entries: list[JournalEntry]
    total: int


class LessonClosure(BaseModel):
    """Ответ кнопки «завершить пару».

    Числа, а не сообщение: фронт собирает из них текст «проставлено N
    отсутствий», а тесты проверяют суть. Повторный вызов возвращает тот же
    lesson_id с absent_created=0 и was_already_closed=true - это не сбой,
    а идемпотентность.
    """

    lesson_id: int
    group_number: str = Field(
        description="Группа, составу которой проставлены отсутствия"
    )
    absent_created: int = Field(
        description="Сколько ABSENT-строк создано этим вызовом (повтор - 0)"
    )
    already_recorded: int = Field(
        default=0,
        description="Сколько студентов уже имели отметку о посещении до закрытия",
    )
    closed_at: datetime = Field(description="Момент закрытия пары")
    was_already_closed: bool = Field(
        description="True, если пара была закрыта раньше этого вызова"
    )
