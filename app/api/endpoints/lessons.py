"""Расписание пар: чтение и ведение (админ-панель).

Чтение нужно CV-модулю и преподавателю, создание/правка/удаление - админке.
Удаление отказывает, если у пары есть записи журнала: каскад
`lessons -> attendance_records` в схеме легален, и без отказа одна кнопка
стирала бы сданную историю.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.openapi import R404, R409, R422, merge
from app.dependencies import Pagination, get_session, pagination_params
from app.schemas import lesson as schemas
from app.services import lessons as lessons_service
from app.services.students import InvalidGroupNumber
from db.models import Discipline, Lesson

router = APIRouter()


@router.get("", response_model=schemas.LessonList)
async def list_lessons(
    discipline_id: int | None = Query(None, ge=1),
    date_: date | None = Query(None, alias="date"),
    group_number: str | None = Query(
        None,
        min_length=4,
        max_length=20,
        description="Пары только этой группы: без фильтра в одну простыню "
        "смешаются пары разных групп в одном и том же слоте",
    ),
    page: Pagination = Depends(pagination_params),
    session: AsyncSession = Depends(get_session),
) -> schemas.LessonList:
    rows, total = await lessons_service.list_lessons(
        session,
        discipline_id=discipline_id,
        lesson_date=date_,
        group_number=group_number,
        offset=page.offset,
        limit=page.limit,
    )
    items = [
        schemas.LessonRead(
            id=lesson.id,
            discipline_id=lesson.discipline_id,
            discipline_name=name,
            group_number=lesson.group_number,
            lesson_date=lesson.lesson_date,
            start_time=lesson.start_time,
            end_time=lesson.end_time,
            room_number=lesson.room_number,
            closed_at=lesson.closed_at,
        )
        for lesson, name in rows
    ]
    return schemas.LessonList(items=items, total=total)


def _read(lesson: Lesson, discipline_name: str | None) -> schemas.LessonRead:
    return schemas.LessonRead(
        id=lesson.id,
        discipline_id=lesson.discipline_id,
        discipline_name=discipline_name,
        group_number=lesson.group_number,
        lesson_date=lesson.lesson_date,
        start_time=lesson.start_time,
        end_time=lesson.end_time,
        room_number=lesson.room_number,
        closed_at=lesson.closed_at,
    )


@router.get(
    "/{lesson_id}", response_model=schemas.LessonRead, responses=R404
)
async def get_lesson(
    lesson_id: int,
    session: AsyncSession = Depends(get_session),
) -> schemas.LessonRead:
    try:
        lesson = await lessons_service.get_lesson(session, lesson_id)
    except lessons_service.LessonNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    name = await session.scalar(
        select(Discipline.name).where(Discipline.id == lesson.discipline_id)
    )
    return _read(lesson, name)


@router.post(
    "",
    response_model=schemas.LessonRead,
    status_code=status.HTTP_201_CREATED,
    responses=merge(R404, R409, R422),
)
async def create_lesson(
    payload: schemas.LessonCreate,
    session: AsyncSession = Depends(get_session),
) -> schemas.LessonRead:
    try:
        lesson = await lessons_service.create(session, payload)
    except lessons_service.DisciplineNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidGroupNumber as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except lessons_service.LessonConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    name = await session.scalar(
        select(Discipline.name).where(Discipline.id == lesson.discipline_id)
    )
    return _read(lesson, name)


@router.patch(
    "/{lesson_id}", response_model=schemas.LessonRead, responses=merge(R404, R409, R422)
)
async def update_lesson(
    lesson_id: int,
    payload: schemas.LessonUpdate,
    session: AsyncSession = Depends(get_session),
) -> schemas.LessonRead:
    try:
        lesson = await lessons_service.update(session, lesson_id, payload)
    except lessons_service.LessonNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except lessons_service.DisciplineNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidGroupNumber as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except lessons_service.InvalidLessonWindow as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except lessons_service.LessonClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except lessons_service.LessonConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    name = await session.scalar(
        select(Discipline.name).where(Discipline.id == lesson.discipline_id)
    )
    return _read(lesson, name)


@router.delete(
    "/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT, responses=merge(R404, R409)
)
async def delete_lesson(
    lesson_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await lessons_service.delete(session, lesson_id)
    except lessons_service.LessonNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except lessons_service.LessonHasRecords as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
