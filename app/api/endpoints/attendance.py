"""Приёмник событий от CV-модуля и журнал пары (веха 5).

POST /attendance/events - «передача в систему» из формулировки вехи:
событие (кто, когда) плюс ссылка на доказательный кадр в объектном
хранилище. При повторной доставке той же пары побеждает самое раннее время
входа, а запись, исправленную руками, автоматическое событие не трогает.
Дублей не возникает за счёт UNIQUE (student_id, lesson_id) - это и есть
критерий «без потерь и дублей».
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_session
from app.api.openapi import R404, R409, R422, R503, merge, ok
from app.schemas import attendance as schemas
from app.services import attendance as attendance_service
from app.services import storage

router = APIRouter()

# Исход «recorded» отличает два случая, в которых запись изменилась (создана
# или обновлена ранним входом), от трёх, в которых журнал остался как был.
_RECORDED = attendance_service.OUTCOME_RECORDED


@router.post(
    "/events",
    response_model=schemas.AttendanceEventResult,
    status_code=status.HTTP_201_CREATED,
    # 200 описан вручную: маршрут объявлен как 201, и FastAPI не подставил бы
    # схему для второго успешного кода сам - клиент получил бы
    # недокументированный ответ ровно в том случае, который важнее всего
    # (данные пришли, но по правилу не записаны).
    responses=merge(
        {"200": ok("Принято; запись не изменена или отброшена по правилу.",
                   schemas.AttendanceEventResult)},
        R404, R409, R422, R503,
    ),
)
async def register_event(
    payload: schemas.AttendanceEventCreate,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> schemas.AttendanceEventResult:
    """Регистрация одного распознанного прохода.

    Коды: 201 - запись создана или обновлена; 200 - событие принято, но по
    правилу не записано (вход после конца пары) либо оставлено то, что уже
    было (ранний вход / ручная правка). Различие даёт поле outcome.
    """
    try:
        record, outcome, lesson = await attendance_service.register(
            session,
            lesson_id=payload.lesson_id,
            student_id=payload.student_id,
            captured_at=payload.captured_at,
            frame_object_key=payload.frame_object_key,
        )
    except attendance_service.LessonNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except attendance_service.InactiveStudent as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except attendance_service.InvalidFrameKey as exc:
        # Неверный формат ключа - не «кадра нет», а поломка на стороне
        # CV-процесса: в тексте отвечаем так, чтобы причину искали в нём.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except attendance_service.FrameMissing as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except storage.StorageError as exc:
        # Хранилище недоступно - это не вина данных, 503 честнее 422/500.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    if outcome != _RECORDED:
        # Ничего не изменилось (или changeset отброшен правилом): это успех
        # доставки, но не создание записи. 201 здесь врал бы.
        response.status_code = status.HTTP_200_OK

    return schemas.AttendanceEventResult(
        record=record,
        outcome=outcome,
        lesson_start=lesson.start_time,
        delay_minutes=record.delay_minutes if record else None,
    )


@router.post(
    "/lessons/{lesson_id}/close",
    response_model=schemas.LessonClosure,
    responses=merge(R404, R503),
)
async def close_lesson(
    lesson_id: int,
    session: AsyncSession = Depends(get_session),
) -> schemas.LessonClosure:
    """Завершить пару: проставить ABSENT активным студентам группы без отметки.

    Это кнопка на фронте, и она зовёт ровно ту же функцию, что и планировщик,
    поэтому два пути не могут разойтись. Операция идемпотентна: повторный
    вызов создаст 0 строк и ничего не испортит. Пару можно закрыть досрочно -
    это самолечится: студент, помеченный ABSENT, а потом замеченный камерой,
    перезапишет свою строку, потому что закрытие только добавляет записи,
    но не меняет существующие.

    200 всегда, в том числе при повторе: результат тот же, а 409 заставил бы
    фронт обрабатывать «уже закрыто» как сбой.
    """
    try:
        report = await attendance_service.close_lesson(session, lesson_id)
    except attendance_service.LessonNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return schemas.LessonClosure(
        lesson_id=report.lesson_id,
        group_number=report.group_number,
        absent_created=report.absent_created,
        already_recorded=report.already_recorded,
        closed_at=report.closed_at,
        was_already_closed=report.was_already_closed,
    )


@router.get("/journal", response_model=schemas.Journal, responses=merge(R404, R503))
async def get_journal(
    lesson_id: int = Query(..., ge=1, description="Пара, журнал которой нужен"),
    session: AsyncSession = Depends(get_session),
) -> schemas.Journal:
    """Журнал пары: кто и во сколько прошёл.

    Состав журнала определяет закрытие пары: пока пара не закрыта, в журнале
    только те, кого зафиксировала камера; после закрытия там же лежат и ABSENT.
    Поэтому у ответа есть closed_at: по нему фронт различает «прогулов ещё нет»
    и «прогулов нет, потому что все пришли» (см. §9.5 плана - ABSENT теперь
    отдельная запись, а не отсутствие строки).
    Студенты тянутся одним JOIN в сервисе - без N+1.
    """
    try:
        lesson, discipline_name, pairs = await attendance_service.journal_for_lesson(
            session, lesson_id
        )
    except attendance_service.LessonNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    entries = [
        schemas.JournalEntry(
            id=record.id,
            student_id=student.id,
            full_name=student.full_name,
            group_number=student.group_number,
            entry_time=record.entry_time,
            status=record.status,
            delay_minutes=record.delay_minutes,
            is_manually_edited=record.is_manually_edited,
            frame_object_key=record.frame_object_key,
            edited_at=record.edited_at,
        )
        for record, student in pairs
    ]

    return schemas.Journal(
        lesson_id=lesson_id,
        discipline_name=discipline_name,
        lesson_date=str(lesson.lesson_date),
        start_time=lesson.start_time.strftime("%H:%M"),
        group_number=lesson.group_number,
        end_time=lesson.end_time.strftime("%H:%M"),
        # Формат как у start/end: фронту нужен отображаемый момент, а не
        # ISO-строка с зоной, которую он будет парсить на своей стороне.
        closed_at=(
            lesson.closed_at.strftime("%Y-%m-%d %H:%M") if lesson.closed_at else None
        ),
        entries=entries,
        total=len(entries),
    )


@router.post(
    "/records",
    response_model=schemas.AttendanceRecordUpdateResult,
    status_code=status.HTTP_201_CREATED,
    responses=merge(R404, R422),
)
async def set_attendance_record(
    payload: schemas.AttendanceRecordSet,
    session: AsyncSession = Depends(get_session),
) -> schemas.AttendanceRecordUpdateResult:
    """Проставить отметку вручную по паре и студенту (требование №7).

    PATCH по record_id для этого не годится: до закрытия пары у студента без
    отметки записи нет, и править нечего. POST закрывает «добавление» из
    формулировки требования, а правила времени, статуса и кадра у него ровно
    те же, что у правки, - оба идут через normalize_manual_entry.

    Если запись уже есть, она перезаписывается: ключ (student_id, lesson_id)
    общий с UNIQUE и с upsert автоматики, поэтому «создать» и «исправить» -
    одна операция, а дубль невозможен.
    """
    try:
        record, delay, edited_at = await attendance_service.set_manual_record(
            session,
            payload.lesson_id,
            payload.student_id,
            status=payload.status,
            entry_time=payload.entry_time,
        )
    except attendance_service.LessonNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except attendance_service.StudentNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (
        attendance_service.EntryTimeNotAllowed,
        attendance_service.StudentNotInLessonGroup,
    ) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return schemas.AttendanceRecordUpdateResult(
        record=record,
        delay_minutes=delay,
        edited_at=edited_at,
    )


@router.patch(
    "/records/{record_id}",
    response_model=schemas.AttendanceRecordUpdateResult,
    responses=merge(R404, R422),
)
async def update_attendance_record(
    record_id: int,
    payload: schemas.AttendanceRecordUpdate,
    session: AsyncSession = Depends(get_session),
) -> schemas.AttendanceRecordUpdateResult:
    """Ручная правка отметки (требование №7, задача 3.3.1).

    Назначение - спорные ситуации: камера не узнала, студент был, но ушёл
    раньше фиксации, отметка потерялась. Поэтому здесь можно и выставить
    ABSENT по уже закрытой паре, и проставить вход там, где его не было.

    Ключевые ограничения контракта (см. AttendanceRecordUpdate):
      - delay_minutes сервер считает сам, от клиента он не принимается;
      - время ПОСЛЕ конца пары разрешено - ручная правка для того и нужна;
      - время вне суток пары отвергается: это опечатка, а не решение;
      - правка снимает адрес кадра: прежний кадр был доказательством
        автоматического входа, который преподаватель только что отверг.

    После правки запись помечается is_manually_edited навсегда: автоматика её
    больше не перетирает (см. условие upsert в register).
    """
    try:
        record, delay, edited_at = await attendance_service.update_record(
            session,
            record_id,
            status=payload.status,
            entry_time=payload.entry_time,
        )
    except attendance_service.RecordNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except attendance_service.EntryTimeNotAllowed as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return schemas.AttendanceRecordUpdateResult(
        record=record,
        delay_minutes=delay,
        edited_at=edited_at,
    )
