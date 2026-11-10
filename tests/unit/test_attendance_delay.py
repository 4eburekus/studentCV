"""Юнит-тесты классификации прохода.

Самое хрупкое место приёмника: рассогласование статус/минуты ломает CHECK в
БД, а неверная граница дня тихо считает опоздание не по той паре. Проверяем
правила 10.11.2026 как спецификацию, независимо от HTTP и хранилища.

Правила (см. докстринг app/services/attendance.py):
  раньше начала            -> PRESENT, delay NULL
  ровно в начало           -> LATE, delay 0      (инверсия прежнего теста!)
  в середине пары          -> LATE, ceil(минут)
  не раньше конца          -> None (не записываем)
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.attendance import classify
from db.enums import AttendanceStatus

LESSON_DATE = date(2026, 11, 9)
START = datetime(2026, 11, 9, 8, 30, tzinfo=timezone.utc).time()
END = datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc).time()


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 11, 9, hour, minute, second, tzinfo=timezone.utc)


# --- PRESENT: раньше начала --------------------------------------------------


def test_present_before_start_time():
    assert classify(at(8, 12), START, END, LESSON_DATE) == (AttendanceStatus.PRESENT, None)


def test_present_one_minute_before_start():
    assert classify(at(8, 29), START, END, LESSON_DATE) == (AttendanceStatus.PRESENT, None)


# --- LATE: ровно начало и позже (до конца) -----------------------------------


def test_late_at_start_time():
    """РОВНО в начало - это LATE с 0 минутами, не PRESENT.

    Инверсия прежнего test_present_at_start_time: то закрепляло наше
    допущение, а не правило заказчика (договорённость 10.11.2026).
    """
    assert classify(at(8, 30), START, END, LESSON_DATE) == (AttendanceStatus.LATE, 0)


def test_late_rounds_up_to_minutes():
    """31 сек после начала = 1 минута: ceil, а не round/truncate."""
    assert classify(at(8, 30, 31), START, END, LESSON_DATE) == (AttendanceStatus.LATE, 1)


def test_late_exact_minutes():
    assert classify(at(8, 42), START, END, LESSON_DATE) == (AttendanceStatus.LATE, 12)


def test_late_full_hour():
    assert classify(at(9, 30), START, END, LESSON_DATE) == (AttendanceStatus.LATE, 60)


def test_late_last_minute_before_end():
    """9:59 - ещё внутри пары, последняя учитываемая минута (90)."""
    assert classify(at(9, 59), START, END, LESSON_DATE) == (AttendanceStatus.LATE, 89)


# --- Не записываем: не раньше конца ------------------------------------------


def test_ignored_at_end_time():
    """Ровно конец пары - уже не учитываем: граница включительная."""
    assert classify(at(10, 0), START, END, LESSON_DATE) is None


def test_ignored_after_end_time():
    assert classify(at(10, 30), START, END, LESSON_DATE) is None


def test_ignored_hours_after_end():
    assert classify(at(13, 0), START, END, LESSON_DATE) is None


# --- Дата границы берётся из пары, а не из события ---------------------------


def test_uses_lesson_date_not_event_date():
    """Границы считаются от даты ПАРЫ, а не от даты события.

    Регресс на старое поведение: calculate_delay строил start/end из
    captured_at.date(), поэтому событие с другим днём попадало на «те же
    8:30-10:00, но своего дня» и молча записывалось как опоздание на пару,
    которой в этот день не было.

    Прежняя версия этого теста предполагала обратное (что день игнорируется и
    8:12 в любой день = PRESENT) - это было моё допущение, а не правило; его
    опроверг сам прогон.

    Пара - понедельник 9 ноября, 8:30-10:00.
    """
    # То же время суток (9:00), но на неделю позже пары: по факту это НЕ
    # про эту пару. Со старым кодом - LATE 30 (пара, «придуманная» на 16-е),
    # с границами от даты пары - «не раньше конца», не записываем.
    later_day = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
    assert classify(later_day, START, END, LESSON_DATE) is None

    # Тот же самый 9:00 в дату пары - обычное опоздание.
    same_day = datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)
    assert classify(same_day, START, END, LESSON_DATE) == (AttendanceStatus.LATE, 30)


# --- Naive-время --------------------------------------------------------------


def test_naive_datetime_treated_as_utc():
    """Pydantic пропустит naive-время от кривого клиента - падать не должны."""
    captured = datetime(2026, 11, 9, 8, 45)
    assert classify(captured, START, END, LESSON_DATE) == (AttendanceStatus.LATE, 15)


# --- Инварианты ---------------------------------------------------------------


def test_status_and_delay_invariant():
    """CHECK (status='LATE') <=> (delay_minutes IS NOT NULL) и delay >= 0.

    Включая 0: новое правило допускает LATE с нулевым опозданием, и CHECK
    (delay_minutes >= 0) это позволяет - схема из-за правил не менялась.
    """
    for offset in (-3600, -60, 0, 1, 59, 60, 30 * 60):
        captured = at(8, 30) + timedelta(seconds=offset)
        result = classify(captured, START, END, LESSON_DATE)
        if result is None:
            continue
        status, delay = result
        assert (status is AttendanceStatus.LATE) == (delay is not None)
        assert delay is None or delay >= 0


@pytest.mark.parametrize("seconds", [1, 61, 90])
def test_late_positive_range(seconds):
    result = classify(at(8, 30) + timedelta(seconds=seconds), START, END, LESSON_DATE)
    assert result is not None
    status, delay = result
    assert status is AttendanceStatus.LATE
    assert delay >= 1
