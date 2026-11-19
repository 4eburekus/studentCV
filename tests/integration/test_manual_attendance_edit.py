"""Ручное редактирование журнала (требование №7, задача 3.3.1).

Проверяет ровно то, что не выводится из кода 200:
- delay_minutes считает сервер, а не клиент (иначе журнал врал бы сам себе);
- PRESENT обязан остаться без задержки, несмотря на CHECK
  late_iff_delay_present - это место легче всего сломать «улучшением»;
- ABSENT сбрасывает и время, и адрес кадра (CHECK absent_iff_no_entry_time);
- правка навсегда снимает строку с автоматического перезаписывания;
- время ПОСЛЕ конца пары разрешено (ради этого правка и существует), а время
  в другой день отвергнуто - CHECK на окно пары в БД нет, это единственная
  защита от опечатки в дате.

Границы пары берутся из lesson_span() - той же даты, что у пары: время,
построенное от «сегодня», оказалось бы в другом дне, и правка отвергала бы
его по правильной причине, но тест проверял бы не то.
"""

from datetime import timedelta

import httpx
import pytest

from test_api_flow import (  # noqa: F401 - фикстуры и хелперы переиспользуются
    captured_for,
    client,
    lesson_span,
    make_frame_key,
    make_lesson_group,
    make_student,
    unique_group,
    unique_suffix,
)


@pytest.fixture()
def marked_pair(client: httpx.Client) -> dict:
    """Пара со студентом, у которого уже есть автоматическая отметка LATE 15.

    Отметка нужна именно автоматическая: только на ней видно, что правка
    переставила флаг is_manually_edited и пересчитала минуты.
    """
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])
    key = make_frame_key(lesson["id"])

    body = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, 15),
            "frame_object_key": key,
        },
    ).json()
    assert body["record"]["status"] == "LATE", body
    assert body["record"]["delay_minutes"] == 15, body
    assert body["record"]["frame_object_key"] == key, body

    lesson["record_id"] = body["record"]["id"]
    lesson["student"] = student
    lesson["frame_key"] = key
    return lesson


def set_record(client: httpx.Client, **body) -> httpx.Response:
    return client.post("/api/v1/attendance/records", json=body)


def patch_record(client: httpx.Client, record_id: int, **body) -> httpx.Response:
    return client.patch(f"/api/v1/attendance/records/{record_id}", json=body)


def get_journal(client: httpx.Client, lesson_id: int) -> dict:
    r = client.get("/api/v1/attendance/journal", params={"lesson_id": lesson_id})
    assert r.status_code == 200, r.text
    return r.json()


def row_of(journal: dict, student_id: int) -> dict:
    return next(e for e in journal["entries"] if e["student_id"] == student_id)


# --- пересчёт задержки сервером ------------------------------------------------


def test_manual_edit_recomputes_delay(client: httpx.Client, marked_pair: dict) -> None:
    """Задержка считается из нового времени; в запросе её поля нет вообще."""
    start, _ = lesson_span(marked_pair)
    entry = start + timedelta(minutes=44, seconds=30)

    r = patch_record(client, marked_pair["record_id"], status="LATE",
                     entry_time=entry.isoformat())
    assert r.status_code == 200, r.text
    body = r.json()
    # 44.5 минуты -> вверх: 45. Полминуты здесь и нужны, чтобы отличить
    # округление вверх от отбрасывания дробной части.
    assert body["delay_minutes"] == 45, body
    assert body["record"]["delay_minutes"] == 45, body
    assert body["record"]["status"] == "LATE", body


def test_manual_present_keeps_delay_null(client: httpx.Client, marked_pair: dict) -> None:
    """PRESENT после начала пары остаётся без задержки.

    Проверка на CHECK late_iff_delay_present: наивная реализация «считать
    минуты для любого не-ABSENT» выдала бы строку (PRESENT, delay=44),
    которую база отвергает, и правка падала бы 500.
    """
    start, _ = lesson_span(marked_pair)
    entry = start + timedelta(minutes=44)

    r = patch_record(client, marked_pair["record_id"], status="PRESENT",
                     entry_time=entry.isoformat())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["record"]["status"] == "PRESENT", body
    assert body["delay_minutes"] is None, body
    assert body["record"]["delay_minutes"] is None, body


def test_manual_edit_accepts_status_without_time_for_absent(
    client: httpx.Client, marked_pair: dict
) -> None:
    """ABSENT принимается и без поля entry_time (отсутствует, а не null)."""
    r = patch_record(client, marked_pair["record_id"], status="ABSENT")
    assert r.status_code == 200, r.text
    assert r.json()["record"]["entry_time"] is None, r.json()


# --- ABSENT: время и кадр -------------------------------------------------------


def test_manual_absent_clears_time_and_frame(client: httpx.Client, marked_pair: dict) -> None:
    """ABSENT обнуляет время входа и снимает адрес кадра.

    Кадр был доказательством автоматического входа, который преподаватель
    отверг; оставить его - значит показать «вот подтверждение» напротив
    отметки, которая это подтверждение отрицает.
    """
    assert marked_pair["frame_key"], "до правки кадр обязан был быть"

    r = patch_record(client, marked_pair["record_id"], status="ABSENT", entry_time=None)
    assert r.status_code == 200, r.text
    record = r.json()["record"]
    assert record["status"] == "ABSENT", record
    assert record["entry_time"] is None, record
    assert record["frame_object_key"] is None, record
    assert record["delay_minutes"] is None, record


def test_manual_edit_ignores_time_for_absent(client: httpx.Client, marked_pair: dict) -> None:
    """ABSENT с присланным временем не создаёт противоречивую строку.

    Сервер обязан либо отбросить время, либо отказаться; оставить и то и
    другое нельзя - CHECK absent_iff_no_entry_time всё равно бы упал.
    """
    start, _ = lesson_span(marked_pair)
    r = patch_record(client, marked_pair["record_id"], status="ABSENT",
                     entry_time=(start + timedelta(minutes=10)).isoformat())
    assert r.status_code == 200, r.text
    assert r.json()["record"]["entry_time"] is None, r.json()


# --- флаг ручной правки --------------------------------------------------------


def test_manual_edit_sets_flag_permanently(client: httpx.Client, marked_pair: dict) -> None:
    """Флаг ставится и не снимается повторной правкой.

    На нём держится защита от перезаписи автоматикой (условие upsert),
    поэтому он обязан оставаться истинным, даже когда правка возвращает
    строку в «автоматический» статус.
    """
    start, _ = lesson_span(marked_pair)
    entry = (start + timedelta(minutes=5)).isoformat()

    first = patch_record(client, marked_pair["record_id"], status="PRESENT",
                         entry_time=entry).json()
    assert first["record"]["is_manually_edited"] is True, first
    assert first["edited_at"], first

    second = patch_record(client, marked_pair["record_id"], status="LATE",
                          entry_time=entry).json()
    assert second["record"]["is_manually_edited"] is True, second


def test_manual_edit_survives_later_event(client: httpx.Client, marked_pair: dict) -> None:
    """Отредактированную вручную строку автоматика не перетирает.

    Без этой гарантии решение преподавателя жило бы до следующей доставки
    события с камеры - то есть ровно до того момента, когда его заметят.
    """
    start, _ = lesson_span(marked_pair)
    entry = start + timedelta(minutes=40)
    patch_record(client, marked_pair["record_id"], status="PRESENT",
                 entry_time=entry.isoformat())

    # Более РАННИЙ проход: без флага именно он перезаписал бы отметку.
    later = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": marked_pair["id"],
            "student_id": marked_pair["student"]["id"],
            "captured_at": captured_for(marked_pair, 3),
            "frame_object_key": make_frame_key(marked_pair["id"]),
        },
    ).json()

    assert later["outcome"] == "kept_manual_edit", later
    assert later["record"]["status"] == "PRESENT", later
    assert later["record"]["delay_minutes"] is None, later


# --- границы времени -----------------------------------------------------------


def test_manual_edit_allows_time_after_lesson_end(client: httpx.Client, marked_pair: dict) -> None:
    """Время ПОСЛЕ конца пары разрешено - ради этого правка и существует.

    Правило «не позже конца пары» ограничивает автоматику. Преподаватель
    вправе засчитать опоздание, которое система отвергла бы, поэтому здесь
    ожидание ровно обратное автоматике.
    """
    _, end = lesson_span(marked_pair)
    entry = end + timedelta(minutes=25)

    r = patch_record(client, marked_pair["record_id"], status="LATE",
                     entry_time=entry.isoformat())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["record"]["status"] == "LATE", body
    # 08:30 -> 10:25 = 115 минут
    assert body["delay_minutes"] == 115, body


def test_manual_edit_rejects_other_day(client: httpx.Client, marked_pair: dict) -> None:
    """Время в другой календарный день отвергается: CHECK на окно пары в БД нет."""
    start, _ = lesson_span(marked_pair)
    r = patch_record(client, marked_pair["record_id"], status="LATE",
                     entry_time=(start + timedelta(days=3)).isoformat())
    assert r.status_code == 422, r.text
    assert "day" in r.json()["detail"].lower(), r.text


def test_manual_edit_requires_time_for_present(client: httpx.Client, marked_pair: dict) -> None:
    """PRESENT/LATE без времени входа - 422, а не 500 от CHECK."""
    for status in ("PRESENT", "LATE"):
        r = patch_record(client, marked_pair["record_id"], status=status, entry_time=None)
        assert r.status_code == 422, (status, r.text)


def test_manual_edit_rejects_unknown_status(client: httpx.Client, marked_pair: dict) -> None:
    """Неизвестный статус отвергается схемой, а не уходит в базу."""
    r = patch_record(client, marked_pair["record_id"], status="EXCUSED", entry_time=None)
    assert r.status_code == 422, r.text


def test_manual_edit_unknown_record_404(client: httpx.Client) -> None:
    r = patch_record(client, 10**9, status="ABSENT", entry_time=None)
    assert r.status_code == 404, r.text


# --- создание отметки там, где записи нет (вторая половина требования №7) ------


def test_set_record_creates_missing_entry(client: httpx.Client) -> None:
    """Отметку можно поставить студенту БЕЗ записи - до закрытия пары.

    Это ровно тот случай, который PATCH не покрывает: пока пара не закрыта,
    у студента нет строки, значит нет и record_id. Требование №7 говорит
    «добавление/редактирование», и без POST первая половина была бы
    недоступна.
    """
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])

    # до отметки журнал пуст
    assert get_journal(client, lesson["id"])["entries"] == []

    start, _ = lesson_span(lesson)
    entry = start + timedelta(minutes=9)
    r = set_record(client, lesson_id=lesson["id"], student_id=student["id"],
                   status="LATE", entry_time=entry.isoformat())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["delay_minutes"] == 9, body
    assert body["record"]["is_manually_edited"] is True, body
    assert body["record"]["frame_object_key"] is None, body

    row = row_of(get_journal(client, lesson["id"]), student["id"])
    assert row["status"] == "LATE", row
    assert row["delay_minutes"] == 9, row


def test_set_record_creates_absent_without_close(client: httpx.Client) -> None:
    """ABSENT можно выставить и до закрытия пары: запись создаётся сразу.

    Смысл в том, что «отсутствие» перестаёт быть следствием закрытия и
    становится решением преподавателя.
    """
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])

    r = set_record(client, lesson_id=lesson["id"], student_id=student["id"],
                   status="ABSENT")
    assert r.status_code == 201, r.text

    row = row_of(get_journal(client, lesson["id"]), student["id"])
    assert row["status"] == "ABSENT", row
    assert row["entry_time"] is None, row
    assert row["delay_minutes"] is None, row

    # закрытие пары после этого ничего не добавит: строка уже есть
    closed = client.post(f"/api/v1/attendance/lessons/{lesson['id']}/close").json()
    assert closed["absent_created"] == 0, closed


def test_set_record_overwrites_instead_of_duplicating(client: httpx.Client) -> None:
    """Повтор того же (пара, студент) не создаёт дубль.

    Ключ общий с UNIQUE и с upsert автоматики, поэтому «создать» и
    «исправить» - одна операция. Дубль здесь означал бы журнал с двумя
    противоречивыми отметками об одном человеке.
    """
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])
    start, _ = lesson_span(lesson)

    first = set_record(client, lesson_id=lesson["id"], student_id=student["id"],
                       status="LATE", entry_time=(start + timedelta(minutes=20)).isoformat())
    second = set_record(client, lesson_id=lesson["id"], student_id=student["id"],
                        status="PRESENT", entry_time=(start - timedelta(minutes=5)).isoformat())
    assert second.status_code == 201, second.text

    assert first.json()["record"]["id"] == second.json()["record"]["id"], (first.json(), second.json())
    journal = get_journal(client, lesson["id"])
    assert journal["total"] == 1, journal
    assert journal["entries"][0]["status"] == "PRESENT", journal
    assert journal["entries"][0]["delay_minutes"] is None, journal


def test_set_record_rejects_student_of_other_group(client: httpx.Client) -> None:
    """Студент чужой группы отвергается.

    Журнал пары строится по группе, и отметка «не из этой оперы» потом
    выглядела бы как данные, которых не может быть: её не видно в списке
    группы, но она остаётся в базе.
    """
    lesson = make_lesson_group(client)
    foreign = make_student(client, group=unique_group())

    r = set_record(client, lesson_id=lesson["id"], student_id=foreign["id"],
                   status="PRESENT", entry_time=captured_for(lesson, 0))
    assert r.status_code == 422, r.text
    assert "group" in r.json()["detail"].lower(), r.text


def test_set_record_unknown_lesson_and_student_404(client: httpx.Client) -> None:
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])

    assert set_record(client, lesson_id=10**9, student_id=student["id"],
                      status="ABSENT").status_code == 404
    assert set_record(client, lesson_id=lesson["id"], student_id=10**9,
                      status="ABSENT").status_code == 404


def test_set_record_shares_rules_with_patch(client: httpx.Client, marked_pair: dict) -> None:
    """POST и PATCH подчиняются одним и тем же правилам.

    Проверка на «две копии правил»: время в другой день отвергается обоими
    способами одинаковым кодом, потому что оба идут через
    normalize_manual_entry. Расхождение здесь - самый дорогой баг экрана:
    один вход создаёт противоречивые строки, а другой нет.
    """
    start, _ = lesson_span(marked_pair)
    wrong_day = (start + timedelta(days=4)).isoformat()

    via_post = set_record(client, lesson_id=marked_pair["id"],
                          student_id=marked_pair["student"]["id"],
                          status="LATE", entry_time=wrong_day)
    via_patch = patch_record(client, marked_pair["record_id"], status="LATE",
                             entry_time=wrong_day)

    assert via_post.status_code == via_patch.status_code == 422, (via_post.text, via_patch.text)
    assert via_post.json()["detail"] == via_patch.json()["detail"], (
        via_post.json(), via_patch.json())


def test_set_record_blocks_later_camera_event(client: httpx.Client) -> None:
    """Созданная вручную отметка защищена от перезаписи так же, как правка.

    Флаг ставится в обеих ветках, иначе «создал руками, а камера поправила»
    осталось бы нормой - то есть функция не решала бы свою задачу.
    """
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])
    start, _ = lesson_span(lesson)

    set_record(client, lesson_id=lesson["id"], student_id=student["id"],
               status="PRESENT", entry_time=(start - timedelta(minutes=3)).isoformat())

    later = client.post(
        "/api/v1/attendance/events",
        json={"lesson_id": lesson["id"], "student_id": student["id"],
              "captured_at": captured_for(lesson, 1),
              "frame_object_key": make_frame_key(lesson["id"])},
    ).json()

    assert later["outcome"] == "kept_manual_edit", later
    assert later["record"]["status"] == "PRESENT", later


# --- правка доходит до журнала --------------------------------------------------


def test_manual_edit_visible_in_journal(client: httpx.Client, marked_pair: dict) -> None:
    """Правка видна в GET /journal: статус, флаг, момент, отсутствие кадра.

    Фронт читает журнал, поэтому проверка только ответа PATCH не доказала бы,
    что преподаватель увидит результат.
    """
    start, _ = lesson_span(marked_pair)
    entry = start + timedelta(minutes=7)
    patch_record(client, marked_pair["record_id"], status="PRESENT",
                 entry_time=entry.isoformat())

    row = row_of(get_journal(client, marked_pair["id"]), marked_pair["student"]["id"])
    assert row["status"] == "PRESENT", row
    assert row["is_manually_edited"] is True, row
    assert row["edited_at"], row
    assert row["frame_object_key"] is None, row


def test_manual_edit_can_mark_absent_on_closed_pair(client: httpx.Client) -> None:
    """Отметку можно снять и на закрытой паре: ABSENT остаётся записью.

    Закрытая пара - типичный объект правки (спор возник после сдачи журнала),
    и отказ здесь обессмыслил бы функцию.
    """
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])
    client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, 4),
            "frame_object_key": make_frame_key(lesson["id"]),
        },
    )

    closed = client.post(f"/api/v1/attendance/lessons/{lesson['id']}/close")
    assert closed.status_code == 200, closed.text

    record_id = row_of(get_journal(client, lesson["id"]), student["id"])["id"]
    r = patch_record(client, record_id, status="ABSENT", entry_time=None)
    assert r.status_code == 200, r.text

    row = row_of(get_journal(client, lesson["id"]), student["id"])
    assert row["status"] == "ABSENT", row
    assert row["entry_time"] is None, row
    assert row["is_manually_edited"] is True, row


def test_manual_edit_returns_absent_student_to_journal(client: httpx.Client) -> None:
    """Обратный ход: помеченного отсутствующим можно вернуть в журнал.

    Ровно этот сценарий и есть «камера не узнала»: ABSENT поставило закрытие
    пары, а преподаватель знает, что человек был.
    """
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])

    closed = client.post(f"/api/v1/attendance/lessons/{lesson['id']}/close")
    assert closed.json()["absent_created"] == 1, closed.text

    row = row_of(get_journal(client, lesson["id"]), student["id"])
    assert row["status"] == "ABSENT", row

    start, _ = lesson_span(lesson)
    entry = start + timedelta(minutes=12)
    r = patch_record(client, row["id"], status="LATE", entry_time=entry.isoformat())
    assert r.status_code == 200, r.text

    after = row_of(get_journal(client, lesson["id"]), student["id"])
    assert after["status"] == "LATE", after
    assert after["delay_minutes"] == 12, after
    assert after["entry_time"], after
