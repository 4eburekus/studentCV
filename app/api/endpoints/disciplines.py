"""Дисциплины: CRUD справочника для админ-панели (требование №3).

Удаление отказывает, если у дисциплины есть пары с записями журнала: каскад
`disciplines -> lessons -> attendance_records` в схеме легален, и без отказа
один клик стирал бы сданную историю посещаемости целиком.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.openapi import R404, R409, merge
from app.dependencies import Pagination, get_session, pagination_params
from app.schemas import discipline as schemas
from app.services import disciplines as disciplines_service

router = APIRouter()


def _read(discipline, teacher_name: str | None) -> schemas.DisciplineRead:
    """Сборка ответа из пары (Discipline, teacher_name).

    from_attributes здесь не спасает: `teacher_name` не поле модели, он
    приходит JOIN'ом из сервиса, поэтому поле подставляется явно.
    """
    return schemas.DisciplineRead(
        id=discipline.id,
        name=discipline.name,
        teacher_id=discipline.teacher_id,
        teacher_name=teacher_name,
        created_at=discipline.created_at,
    )


@router.post(
    "",
    response_model=schemas.DisciplineRead,
    status_code=status.HTTP_201_CREATED,
    responses=merge(R404, R409),
)
async def create_discipline(
    payload: schemas.DisciplineCreate,
    session: AsyncSession = Depends(get_session),
) -> schemas.DisciplineRead:
    try:
        discipline = await disciplines_service.create(session, payload)
    except disciplines_service.TeacherNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except disciplines_service.DuplicateDiscipline as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"discipline {payload.name!r} already exists for teacher "
            f"{payload.teacher_id}",
        ) from exc
    # Имя преподавателя для ответа: список получает его JOIN'ом в сервисе,
    # одиночный объект - тем же способом, иначе карточка осталась бы без
    # преподавателя, хотя колонка в таблице админки есть.
    teacher_name = await disciplines_service.teacher_name(session, discipline.teacher_id)
    return _read(discipline, teacher_name)


@router.get("", response_model=schemas.DisciplineList)
async def list_disciplines(
    teacher_id: int | None = Query(None, ge=1),
    q: str | None = Query(None, max_length=255, description="Подстрока названия"),
    page: Pagination = Depends(pagination_params),
    session: AsyncSession = Depends(get_session),
) -> schemas.DisciplineList:
    rows, total = await disciplines_service.list_disciplines(
        session,
        teacher_id=teacher_id,
        query=q,
        offset=page.offset,
        limit=page.limit,
    )
    return schemas.DisciplineList(
        items=[_read(discipline, name) for discipline, name in rows], total=total
    )


@router.get(
    "/{discipline_id}", response_model=schemas.DisciplineRead, responses=R404
)
async def get_discipline(
    discipline_id: int,
    session: AsyncSession = Depends(get_session),
) -> schemas.DisciplineRead:
    try:
        discipline, teacher_name = await disciplines_service.get_with_teacher(
            session, discipline_id
        )
    except disciplines_service.DisciplineNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _read(discipline, teacher_name)


@router.patch(
    "/{discipline_id}",
    response_model=schemas.DisciplineRead,
    responses=merge(R404, R409),
)
async def update_discipline(
    discipline_id: int,
    payload: schemas.DisciplineUpdate,
    session: AsyncSession = Depends(get_session),
) -> schemas.DisciplineRead:
    try:
        discipline = await disciplines_service.update(session, discipline_id, payload)
    except disciplines_service.DisciplineNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except disciplines_service.TeacherNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except disciplines_service.DuplicateDiscipline as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    teacher_name = await disciplines_service.teacher_name(session, discipline.teacher_id)
    return _read(discipline, teacher_name)


@router.delete(
    "/{discipline_id}", status_code=status.HTTP_204_NO_CONTENT, responses=R409
)
async def delete_discipline(
    discipline_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await disciplines_service.remove(session, discipline_id)
    except disciplines_service.DisciplineNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except disciplines_service.DisciplineInUse as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
