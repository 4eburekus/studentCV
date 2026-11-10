"""Чтение расписания пар (нужно CV-модулю и преподавателю)."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination, get_session, pagination_params
from app.schemas import lesson as schemas
from app.services import lessons as lessons_service

router = APIRouter()


@router.get("", response_model=schemas.LessonList)
async def list_lessons(
    discipline_id: int | None = Query(None, ge=1),
    date_: date | None = Query(None, alias="date"),
    page: Pagination = Depends(pagination_params),
    session: AsyncSession = Depends(get_session),
) -> schemas.LessonList:
    rows, total = await lessons_service.list_lessons(
        session,
        discipline_id=discipline_id,
        lesson_date=date_,
        offset=page.offset,
        limit=page.limit,
    )
    items = [
        schemas.LessonRead(
            id=lesson.id,
            discipline_id=lesson.discipline_id,
            discipline_name=name,
            lesson_date=lesson.lesson_date,
            start_time=lesson.start_time,
            end_time=lesson.end_time,
        )
        for lesson, name in rows
    ]
    return schemas.LessonList(items=items, total=total)
