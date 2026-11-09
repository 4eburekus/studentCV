"""Перечисления предметной области."""

from enum import Enum


class AttendanceStatus(str, Enum):
    """Статус посещения, который фиксируется в журнале."""

    PRESENT = "PRESENT"
    LATE = "LATE"
    ABSENT = "ABSENT"

    @classmethod
    def values(cls) -> list[str]:
        """Значения для нативного PG-enum (совпадают с именами элементов)."""
        return [member.name for member in cls]
