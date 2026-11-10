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


@router.get("/journal", response_model=schemas.Journal, responses=merge(R404, R503))
async def get_journal(
    lesson_id: int = Query(..., ge=1, description="Пара, журнал которой нужен"),
    session: AsyncSession = Depends(get_session),
) -> schemas.Journal:
    """Журнал пары: кто и во сколько прошёл.

    Отсутствие строки = ABSENT (модель §3.6 плана). Важно для чтения журнала:
    студент, пришедший ПОСЛЕ конца пары, тоже не имеет строки - по правилам
    10.11.2026 он не учитывается. Различить эти два случая по одной записи
    нельзя; вопрос вынесен в §9 плана как вопрос заказчику, потому что ответ
    меняет схему.
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
        )
        for record, student in pairs
    ]

    return schemas.Journal(
        lesson_id=lesson_id,
        discipline_name=discipline_name,
        lesson_date=str(lesson.lesson_date),
        start_time=lesson.start_time.strftime("%H:%M"),
        end_time=lesson.end_time.strftime("%H:%M"),
        entries=entries,
        total=len(entries),
    )
