"""Студенты: заведение, поиск, правка, мягкое удаление (требование №9)."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination, get_session, pagination_params
from app.api.openapi import R404, R409, R422, merge
from app.schemas import student as schemas
from app.services import students as students_service

router = APIRouter()


@router.post(
    "",
    response_model=schemas.StudentRead,
    status_code=status.HTTP_201_CREATED,
    responses=merge(R409, R422),
)
async def create_student(
    payload: schemas.StudentCreate,
    session: AsyncSession = Depends(get_session),
) -> schemas.StudentRead:
    try:
        student = await students_service.create(session, payload)
    except students_service.InvalidGroupNumber as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"student already exists: {payload.full_name} / {payload.group_number}",
        ) from exc
    return student


@router.get("", response_model=schemas.StudentList)
async def list_students(
    group: str | None = Query(None, max_length=20, description="Точный номер группы"),
    q: str | None = Query(None, max_length=255, description="Подстрока ФИО или группы"),
    is_active: bool | None = Query(True),
    page: Pagination = Depends(pagination_params),
    session: AsyncSession = Depends(get_session),
) -> schemas.StudentList:
    items, total = await students_service.list_students(
        session,
        group=group,
        query=q,
        is_active=is_active,
        offset=page.offset,
        limit=page.limit,
    )
    return schemas.StudentList(items=items, total=total, page=page.page, limit=page.limit)


@router.get(
    "/{student_id}", response_model=schemas.StudentRead, responses=R404
)
async def get_student(
    student_id: int,
    session: AsyncSession = Depends(get_session),
) -> schemas.StudentRead:
    try:
        return await students_service.get(session, student_id)
    except students_service.StudentNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.patch(
    "/{student_id}",
    response_model=schemas.StudentRead,
    responses=merge(R404, R422),
)
async def update_student(
    student_id: int,
    payload: schemas.StudentUpdate,
    session: AsyncSession = Depends(get_session),
) -> schemas.StudentRead:
    try:
        return await students_service.update(session, student_id, payload)
    except students_service.StudentNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except students_service.InvalidGroupNumber as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT, responses=R404)
async def deactivate_student(
    student_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Мягкое удаление: студент остаётся, журнал не рвётся.

    Физическое удаление через ON DELETE CASCADE стёрло бы записи посещаемости
    и отчёт за прошлые недели стал бы неправдой.
    """
    try:
        await students_service.deactivate(session, student_id)
    except students_service.StudentNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
