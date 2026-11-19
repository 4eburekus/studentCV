"""Схемы пары (расписания).

HealthResponse переехал в app/schemas/health.py - здесь были только схемы
расписания; дубль схемы удалён после появления строгой версии.
"""

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LessonRead(BaseModel):
    """Пара в том виде, в каком её показывают списку и админке.

    group_number и closed_at появились вместе с ABSENT-записью: группа задаёт
    состав журнала, а closed_at - единственный надёжный признак того, что
    закрытие уже было. По наличию строк ABSENT фронт этого определить не может:
    на пару могли прийти все, и отсутствий в журнале не будет при закрытой паре.

    room_number - аудитория (миграция 0004). Nullable: колонка добавлена
    позже остальных, и старые пары её не имеют.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    discipline_id: int
    discipline_name: str | None = None
    group_number: str
    lesson_date: date
    start_time: time
    end_time: time
    room_number: str | None = None
    closed_at: datetime | None = None


class LessonList(BaseModel):
    items: list[LessonRead]
    total: int


class LessonCreate(BaseModel):
    """Новая пара. Проверки формата группы и пересечения слота - в сервисе.

    Время принимается как time: фронт отдаёт "08:30", и pydantic разбирает это
    сам. Отдельного строкового поля с последующим парсингом здесь быть не
    должно - иначе формат «HH:MM» окажется нигде не описанным контрактом.
    """

    discipline_id: int = Field(ge=1)
    group_number: str = Field(min_length=4, max_length=20)
    lesson_date: date
    start_time: time
    end_time: time
    room_number: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def check_order(self) -> "LessonCreate":
        # Дублирует CHECK end_time > start_time намеренно: констрейнт
        #necessary, но приходит он как IntegrityError без указания поля, а
        # админ должен получить внятный 422 до похода в базу.
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class LessonUpdate(BaseModel):
    """Частичная правка пары.

    Смена группы или даты/времени у ЗАКРЫТОЙ пары запрещена в сервисе, а не
    здесь: закрытие уже вывело из этих значений список отсутствующих, и правка
    задним числом переписала бы журнал, которого админ не касался.
    """

    discipline_id: int | None = Field(default=None, ge=1)
    group_number: str | None = Field(default=None, min_length=4, max_length=20)
    lesson_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    room_number: str | None = Field(default=None, max_length=50)
