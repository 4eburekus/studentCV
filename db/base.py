"""Базовый декларативный слой SQLAlchemy."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Предсказуемые имена ограничений: их видно в pgAdmin и в диффах Alembic,
# а не как attendance_records_delay_minutes_check / lessons_group_number_check.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Общий базовый класс для всех моделей."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
