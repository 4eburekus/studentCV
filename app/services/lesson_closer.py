"""Фоновое закрытие истёкших пар («будильник»).

Почему это отдельный модуль, а не middleware или триггер в БД

Триггер на вставку (AFTER INSERT ON attendance_records) решает половину задачи
и не решает вторую половину: у него нет таймера, он просыпается только когда
кто-то пишет в таблицу. Пара, на которую не подошёл НИКТО, не даёт ни одной
вставки, и ABSENT по ней не появился бы никогда. Планировщик же опирается на
now() и потому закрывает и такие пары тоже.

Почему не pg_cron: официальный образ postgres:16-alpine его не содержит,
нужны смена образа базы, shared_preload_libraries и перезапуск - то есть
инфраструктурный слой, который Устав выносит за пределы задачи.

Почему asyncio, а не APScheduler: библиотеки в requirements.txt нет, а её
установка в этой среде упирается в блокировку Docker Hub/PyPI. Цикл здесь
тривиален (спать, закрыть, логировать), и своя реализация не добавляет
поверхности отказа; при переходе на Celery/Beat меняется только этот файл -
ядро close_overdue_lessons остаётся тем же.
"""

import asyncio
import logging

from db.session import SessionLocal
from app.services.attendance import close_overdue_lessons

log = logging.getLogger(__name__)

# Ошибка одного прогона не убивает контур: база может перезапускаться раньше
# backend'а, а пропущенный прогон компенсируется следующим - закрытие
# идемпотентно и опирается на closed_at, а не на «успели ли в прошлый раз».
_MAX_BACKOFF_SECONDS = 300


async def close_overdue_loop(
    stop: asyncio.Event, interval_seconds: int
) -> None:
    """Цикл «закрыть истёкшие пары -> спать», пока не придёт stop.

    Работа идёт ДО сна, а не после: прогон, стартовавший сразу при подъёме
    приложения, закрывает пары, истёкшие, пока контейнер был выключен. Иначе
    журнал показывал бы неполную картину минимум один интервал после каждого
    рестарта.

    Интервал меряется от конца прогона. Это консервативно (пауза никогда не
    короче заданной) и достаточно: закрытие пары - один INSERT..SELECT на
    группу, доли секунды, заплыть за интервал ему нечем.
    """
    while not stop.is_set():
        try:
            async with SessionLocal() as session:
                closed = await close_overdue_lessons(session)
            if closed:
                log.info("lesson closer: closed %d overdue lesson(s)", closed)
            delay = interval_seconds
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001: фон не должен ронять сервер
            delay = min(interval_seconds * 2, _MAX_BACKOFF_SECONDS)
            log.warning(
                "lesson closer failed (%s), retry in %ds", type(exc).__name__, delay
            )

        # wait_for(Event) вместо sleep: stop видит завершение немедленно,
        # graceful shutdown не упирается в остаток интервала.
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            continue
