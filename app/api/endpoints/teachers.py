"""Преподаватели: CRUD справочника для админ-панели (требование №9).

Здесь же смена пароля отдельным PUT: совмещать её с PATCH нельзя, иначе
случайный запрос без поля обнулил бы учётку, а права на «переписать пароль»
и «переименовать» в реальном входе (требование №11) - разные права.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.openapi import R404, R409, merge
from app.dependencies import Pagination, get_session, pagination_params
from app.schemas import teacher as schemas
from app.services import teachers as teachers_service

router = APIRouter()


@router.post(
    "",
    response_model=schemas.TeacherRead,
    status_code=status.HTTP_201_CREATED,
    responses=merge(R409),
)
async def create_teacher(
    payload: schemas.TeacherCreate,
    session: AsyncSession = Depends(get_session),
) -> schemas.TeacherRead:
    try:
        return await teachers_service.create(session, payload)
    except teachers_service.LoginTaken as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except IntegrityError as exc:
        # Гонка: два параллельных POST с одним логином. Проверка в сервисе
        # не атомарна, поэтому UNIQUE остаётся последней инстанцией и молчать
        # о ней нельзя - без этого ответа клиент получил бы 500.
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"login {payload.login!r} is already used"
        ) from exc


@router.get("", response_model=schemas.TeacherList)
async def list_teachers(
    q: str | None = Query(None, max_length=255, description="Подстрока ФИО или логина"),
    page: Pagination = Depends(pagination_params),
    session: AsyncSession = Depends(get_session),
) -> schemas.TeacherList:
    items, total = await teachers_service.list_teachers(
        session, query=q, offset=page.offset, limit=page.limit
    )
    return schemas.TeacherList(items=items, total=total)


@router.get("/{teacher_id}", response_model=schemas.TeacherRead, responses=R404)
async def get_teacher(
    teacher_id: int,
    session: AsyncSession = Depends(get_session),
) -> schemas.TeacherRead:
    try:
        return await teachers_service.get(session, teacher_id)
    except teachers_service.TeacherNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.patch(
    "/{teacher_id}", response_model=schemas.TeacherRead, responses=merge(R404, R409)
)
async def update_teacher(
    teacher_id: int,
    payload: schemas.TeacherUpdate,
    session: AsyncSession = Depends(get_session),
) -> schemas.TeacherRead:
    try:
        return await teachers_service.update(session, teacher_id, payload)
    except teachers_service.TeacherNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except teachers_service.LoginTaken as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.put(
    "/{teacher_id}/password",
    response_model=schemas.TeacherRead,
    responses=R404,
)
async def set_teacher_password(
    teacher_id: int,
    payload: schemas.TeacherPasswordUpdate,
    session: AsyncSession = Depends(get_session),
) -> schemas.TeacherRead:
    try:
        return await teachers_service.set_password(session, teacher_id, payload.password)
    except teachers_service.TeacherNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.delete(
    "/{teacher_id}", status_code=status.HTTP_204_NO_CONTENT, responses=R409
)
async def delete_teacher(
    teacher_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Отказ, если за преподавателем числятся дисциплины.

    База защитила бы и сама (FK с ON DELETE RESTRICT), но её IntegrityError
    не объясняет админу, что именно мешало, поэтому счётчик дисциплин
    считается заранее и приходит в тексте 409.
    """
    try:
        await teachers_service.remove(session, teacher_id)
    except teachers_service.TeacherNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except teachers_service.TeacherHasDisciplines as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
