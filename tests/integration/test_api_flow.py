"""Интеграционные тесты API против живого compose-стека.

Без моков: реальный PostgreSQL, реальное объектное хранилище (SeaweedFS),
реальные объекты в бакетах.
Запуск из контейнера backend (uvicorn уже слушает localhost:8000 внутри него):

    docker compose exec backend pytest tests/integration -q

Причина, почему тесты синхронные: httpx.Client не тянет asyncio-обвязку, а
S3-вызовы оборачиваются в asyncio.run(). Меньше движущихся частей, чем с
pytest-asyncio на каждом тесте.
"""

import asyncio
import hashlib
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

# 1x1 jpeg. Содержимое для API не важно: он проверяет content_type и
# непустоту, целостность изображения - дело CV-модуля.
TINY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300ffffffffffff"
    "ffffff2c272830302f3d3d34343d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d"
    "ffdd004301ffffffffffffffff3434343434343434343434343434343434343434"
    "ffc00011080001000103012200021101031101ffc4001f00000105010101010101"
    "00000000000000000102030405060708090a0bffc400b510000201030302040305"
    "59ffda000c03010002110311003f00"
) + b"\x00" * 64 + b"\xff\xd9"


def unique_suffix() -> str:
    return uuid.uuid4().hex[:6]


# Разрешённые буквы формата: весь диапазон [А-Я] без Ё (он тоже допустим
# регуляркой, но исключение убирает вопрос про collation из теста).
_CAPS = "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯ"
_LOWER = _CAPS.lower()


def unique_group() -> str:
    """Номер группы, который ВСЕГДА проходит формат и почти всегда уникален.

    Формат: ^\\d{2}-[А-ЯЁ]{3,4}[а-яё]{0,3}-\\d{2}$ - ОБЕ числовые части ровно
    по две цифры.

    Прежняя сборка f"0{unique_suffix()[-1]}-ТИПП-02" была багом в самом тесте:
    unique_suffix() возвращает hex, и его последний символ в ~37% случаев
    буква, тогда группа вида "0a-ТИПП-02" не проходит формат и запрос падал
    с 422. Тест оставался зелёным ровно пока везло - то есть проверка фильтра
    по группе время от времени вообще ничего не проверяла.

    Уникальность теперь в буквенной части (3 заглавных + 2 строчных = ~11 млн
    вариантов), а не в двух цифрах (100 вариантов), поэтому коллизия между
    запусками не вероятнее совпадения uuid.
    """
    digits = f"{uuid.uuid4().int % 100:02d}"
    caps = "".join(secrets.choice(_CAPS) for _ in range(3))
    lower = "".join(secrets.choice(_LOWER) for _ in range(2))
    return f"{digits}-{caps}{lower}-{digits}"


# Формат ключа из CHECK в student_photos: biometrics/<uuid4>.jpg
PHOTO_KEY_RE = re.compile(
    r"^biometrics/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jpg$"
)


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    # Заголовок обязателен: /api/v1/* требуют представления (сейчас - заглушка,
    # проверяется НАЛИЧИЕ заголовка, а не подлинность токена). Без него - 401.
    # /healthz живёт вне авторизации, лишний заголовок там безвреден.
    with httpx.Client(
        base_url=BASE_URL,
        timeout=30.0,
        headers={"Authorization": "Bearer stub-token"},
    ) as c:
        yield c


def test_api_requires_authorization() -> None:
    """Без Authorization - 401, и это часть контракта.

    Отдельный клиент без заголовка: именно его отсутствие - единственный
    случай, который заглушка умеет отсеивать. Срез реального входа обязан
    сохранить этот тест зелёным (поменяется только проверка токена внутри).
    """
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as bare:
        r = bare.get("/api/v1/students")
        assert r.status_code == 401, r.text
        assert "WWW-Authenticate" in r.headers, dict(r.headers)
        # healthz остаётся открытым: у healthcheck'а контейнера нет учётных данных
        assert bare.get("/healthz").status_code == 200


def make_student(client: httpx.Client, group: str = "01-ФИИтт-01") -> dict:
    """Студент с уникальным ФИО, чтобы тесты не зависели от порядка."""
    payload = {
        "full_name": f"Тест Иванов {unique_suffix()}",
        "group_number": group,
    }
    r = client.post("/api/v1/students", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


# --- health -------------------------------------------------------------------


def test_healthz_reports_both_sources_up(client: httpx.Client) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["database"] == "ok", body
    assert body["storage"] == "ok", body


# --- студенты -----------------------------------------------------------------


def test_create_student_and_fetch(client: httpx.Client) -> None:
    student = make_student(client)
    r = client.get(f"/api/v1/students/{student['id']}")
    assert r.status_code == 200
    assert r.json()["group_number"] == "01-ФИИтт-01"
    assert r.json()["is_active"] is True


def test_invalid_group_number_rejected(client: httpx.Client) -> None:
    """Формат проверяется до БД: 422 с внятным текстом, а не ошибка констрейнта."""
    for bad in ("01-фиитт-01", "01-ФИтт-01", "1-ФИИтт-01", "01-ФИИтт-0"):
        r = client.post(
            "/api/v1/students",
            json={"full_name": "Тест Петров", "group_number": bad},
        )
        assert r.status_code == 422, (bad, r.text)
        assert "format" in r.text.lower(), (bad, r.text)


def test_filter_by_group(client: httpx.Client) -> None:
    # unique_group(), а не склейка с hex-суффиксом: та давала невалидные
    # номера ("0a-ТИПП-02") и тест время от времени ничего не проверял.
    group = unique_group()
    student = make_student(client, group=group)

    r = client.get("/api/v1/students", params={"group": group})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert all(item["group_number"] == group for item in body["items"])
    assert student["id"] in {item["id"] for item in body["items"]}


def test_search_by_name(client: httpx.Client) -> None:
    student = make_student(client)
    needle = student["full_name"].split()[1]  # фамилия
    r = client.get("/api/v1/students", params={"q": needle})
    assert r.status_code == 200
    assert student["id"] in {i["id"] for i in r.json()["items"]}


def test_delete_is_soft(client: httpx.Client) -> None:
    """DELETE не рвёт журнал: студент остаётся, становится is_active=false."""
    student = make_student(client)
    r = client.delete(f"/api/v1/students/{student['id']}")
    assert r.status_code == 204

    got = client.get(f"/api/v1/students/{student['id']}")
    assert got.status_code == 200
    assert got.json()["is_active"] is False

    # по умолчанию список отдаёт только активных
    listed = client.get("/api/v1/students", params={"group": student["group_number"]})
    assert student["id"] not in {i["id"] for i in listed.json()["items"]}


# --- фото и MinIO -------------------------------------------------------------


def upload_photo(client: httpx.Client, student_id: int, blob: bytes = None) -> httpx.Response:
    return client.post(
        f"/api/v1/students/{student_id}/photos",
        files={"file": ("sample.jpg", blob or TINY_JPEG, "image/jpeg")},
    )


def test_photo_upload_writes_object_to_storage(client: httpx.Client) -> None:
    """Главная проверка среза: байты легли в biometrics, хэш в БД совпал."""
    student = make_student(client)
    blob = TINY_JPEG + unique_suffix().encode()

    r = upload_photo(client, student["id"], blob)
    assert r.status_code == 201, r.text
    photo = r.json()

    expected_hash = hashlib.sha256(blob).hexdigest()
    assert photo["content_hash"] == expected_hash
    assert photo["photo_url"].startswith("biometrics/")
    assert PHOTO_KEY_RE.match(photo["photo_url"]), photo["photo_url"]

    from app.services import storage

    async def check() -> bool:
        return await storage.object_exists("biometrics", photo["photo_url"])

    assert asyncio.run(check()) is True, "объект не найден в бакете biometrics"


def test_sixth_photo_rejected(client: httpx.Client) -> None:
    """Требование №8: эталонных фото не больше пяти."""
    student = make_student(client)
    for i in range(5):
        r = upload_photo(client, student["id"], TINY_JPEG + f"{i}-{unique_suffix()}".encode())
        assert r.status_code == 201, (i, r.text)

    r = upload_photo(client, student["id"], TINY_JPEG + b"6")
    assert r.status_code == 422, r.text
    assert "max" in r.text.lower() or "5" in r.text


def test_delete_photo_removes_row_and_object(client: httpx.Client) -> None:
    """Осиротевшие файлы нам не нужны: удаляется и строка, и объект."""
    student = make_student(client)
    photo = upload_photo(client, student["id"], TINY_JPEG + b"del").json()

    r = client.delete(f"/api/v1/photos/{photo['id']}")
    assert r.status_code == 204, r.text

    listing = client.get(f"/api/v1/students/{student['id']}/photos").json()
    assert photo["id"] not in {p["id"] for p in listing["items"]}

    from app.services import storage

    assert asyncio.run(storage.object_exists("biometrics", photo["photo_url"])) is False


def test_photo_for_missing_student_404(client: httpx.Client) -> None:
    r = upload_photo(client, 999999)
    assert r.status_code == 404, r.text


def test_wrong_content_type_rejected(client: httpx.Client) -> None:
    student = make_student(client)
    r = client.post(
        f"/api/v1/students/{student['id']}/photos",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 415, r.text


# --- посещаемость -------------------------------------------------------------


def first_lesson(client: httpx.Client) -> dict:
    r = client.get("/api/v1/lessons", params={"limit": 1})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, "нет ни одной пары - выполните python -m db.seeds"
    return items[0]


def make_frame_key(lesson_id: int, blob: bytes = None) -> str:
    """Кладёт доказательный кадр в frames руками «CV-модуля» (root-креды)."""
    from app.services import storage

    key = storage.new_frame_key(lesson_id)
    asyncio.run(storage.put_object("frames", key, blob or TINY_JPEG))
    return key


def captured_for(lesson: dict, minutes_late: int) -> str:
    """Момент прохода ОТНОСИТЕЛЬНО ДАТЫ ПАРЫ, а не сегодняшнего дня.

    Сиды ставят пары на ближайший понедельник; если строить время от сегодня,
    событие окажется в другом дне, а границы теперь берутся из lesson_date
    (правило 10.11.2026) - и любое «опоздание» стало бы PRESENT. Так тесты
    молча проверяли бы не то. Здесь - та же дата, что у пары, с той же парой
    часов и минут.
    """
    y, m, d = (int(x) for x in lesson["lesson_date"].split("-")[:3])
    hour, minute = (int(x) for x in lesson["start_time"].split(":")[:2])
    start = datetime(y, m, d, hour, minute, tzinfo=timezone.utc)
    return (start + timedelta(minutes=minutes_late)).isoformat()


def lesson_span(lesson: dict) -> tuple[datetime, datetime]:
    """Границы пары как моменты времени - для тестов прохода после конца."""
    y, m, d = (int(x) for x in lesson["lesson_date"].split("-")[:3])
    sh, sm = (int(x) for x in lesson["start_time"].split(":")[:2])
    eh, em = (int(x) for x in lesson["end_time"].split(":")[:2])
    return (
        datetime(y, m, d, sh, sm, tzinfo=timezone.utc),
        datetime(y, m, d, eh, em, tzinfo=timezone.utc),
    )


def test_event_late_computes_delay(client: httpx.Client) -> None:
    lesson = first_lesson(client)
    student = make_student(client)
    key = make_frame_key(lesson["id"])

    r = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, 12),
            "frame_object_key": key,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["outcome"] == "recorded"
    assert body["record"]["status"] == "LATE"
    assert body["record"]["delay_minutes"] == 12


def test_event_repeat_keeps_earlier_entry(client: httpx.Client) -> None:
    """Правило 10.11.2026: при повторе побеждает САМЫЙ РАННИЙ вход.

    Первый проход - опоздание на 5 минут. Повтор - ровно в начало (раньше
    записанного): строка та же, дубля нет, но данные ПЕРЕСЧИТАНЫ - LATE 0.
    Обратный порядок (сначала ранний, потом поздний) проверяется вторым
    запросом ниже: там уже ничего не меняется.
    """
    lesson = first_lesson(client)
    student = make_student(client)
    key = make_frame_key(lesson["id"])

    first = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, 5),
            "frame_object_key": key,
        },
    ).json()
    assert first["outcome"] == "recorded"
    assert first["record"]["status"] == "LATE"
    assert first["record"]["delay_minutes"] == 5

    # Раннее событие (ровно начало) перебивает позднее записанное.
    second = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, 0),
            "frame_object_key": key,
        },
    )
    assert second.status_code == 201, second.text
    body = second.json()

    assert body["outcome"] == "recorded"
    assert body["record"]["id"] == first["record"]["id"]
    assert body["record"]["status"] == "LATE"
    assert body["record"]["delay_minutes"] == 0

    # А более позднее событие раннее уже НЕ перебивает.
    third = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, 20),
            "frame_object_key": key,
        },
    )
    assert third.status_code == 200, third.text
    third_body = third.json()
    assert third_body["outcome"] == "kept_earlier_entry"
    assert third_body["record"]["delay_minutes"] == 0

    journal = client.get(
        "/api/v1/attendance/journal", params={"lesson_id": lesson["id"]}
    ).json()
    rows = [e for e in journal["entries"] if e["student_id"] == student["id"]]
    assert len(rows) == 1, f"дубль в журнале: {len(rows)} записей"


def test_event_at_start_time_is_late_zero(client: httpx.Client) -> None:
    """Ровно в начало - LATE с 0 минутами (согласовано 10.11.2026).

    Прежнее имя и ожидание (PRESENT) закрепляли наше допущение, а не правило.
    """
    lesson = first_lesson(client)
    student = make_student(client)
    key = make_frame_key(lesson["id"])

    r = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, 0),
            "frame_object_key": key,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["outcome"] == "recorded"
    assert body["record"]["status"] == "LATE"
    assert body["record"]["delay_minutes"] == 0


def test_event_before_start_is_present(client: httpx.Client) -> None:
    """Раньше начала - PRESENT без опоздания (минуты могут быть отрицательны)."""
    lesson = first_lesson(client)
    student = make_student(client)
    key = make_frame_key(lesson["id"])

    body = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, -8),
            "frame_object_key": key,
        },
    ).json()
    assert body["record"]["status"] == "PRESENT"
    assert body["record"]["delay_minutes"] is None


def test_event_after_lesson_end_is_not_recorded(client: httpx.Client) -> None:
    """Вход не раньше конца пары не записывается: студент остаётся ABSENT.

    Это НЕ ошибка: данные валидны, их сознательно не учитываем, поэтому 200,
    record=None и строки в журнале нет.
    """
    lesson = first_lesson(client)
    student = make_student(client)
    key = make_frame_key(lesson["id"])
    _start, end = lesson_span(lesson)

    r = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": (end + timedelta(minutes=3)).isoformat(),
            "frame_object_key": key,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "ignored_after_lesson_end"
    assert body["record"] is None

    journal = client.get(
        "/api/v1/attendance/journal", params={"lesson_id": lesson["id"]}
    ).json()
    assert student["id"] not in {e["student_id"] for e in journal["entries"]}


def test_manual_edit_is_not_overwritten(client: httpx.Client) -> None:
    """Ручная правка переживает любое автоматическое событие (требование №7).

    Эндпоинта правки ещё нет, поэтому флаг ставим прямо в БД - ровно так,
    как его поставит будущий редактирующий контур.
    """
    lesson = first_lesson(client)
    student = make_student(client)
    key = make_frame_key(lesson["id"])

    first = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, 30),
            "frame_object_key": key,
        },
    ).json()
    entry_time = first["record"]["entry_time"]

    import asyncio
    from sqlalchemy import text as sa_text

    from db.session import SessionLocal

    async def mark_manual() -> None:
        async with SessionLocal() as s:
            await s.execute(
                sa_text(
                    "update attendance_records set is_manually_edited = true "
                    "where id = :id"
                ),
                {"id": first["record"]["id"]},
            )
            await s.commit()

    asyncio.run(mark_manual())

    # Ранний вход из камеры - он ВЫГЛЯДТ выгоднее для студента, но ручную
    # отметку не имеет права перебивать.
    r = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, 0),
            "frame_object_key": key,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "kept_manual_edit"
    assert body["record"]["entry_time"] == entry_time, "ручная запись изменена"


def test_event_with_missing_frame_rejected(client: httpx.Client) -> None:
    """Кадр - доказательство отметки. Нет объекта - нет записи."""
    lesson = first_lesson(client)
    student = make_student(client)
    ghost = f"frames/{lesson['id']}/{uuid.uuid4()}.jpg"

    r = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, 3),
            "frame_object_key": ghost,
        },
    )
    assert r.status_code == 422, r.text
    assert "frame" in r.text.lower()


def test_event_for_inactive_student_rejected(client: httpx.Client) -> None:
    lesson = first_lesson(client)
    student = make_student(client)
    key = make_frame_key(lesson["id"])
    client.delete(f"/api/v1/students/{student['id']}")

    r = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, 3),
            "frame_object_key": key,
        },
    )
    assert r.status_code == 409, r.text


def test_event_invalid_frame_key_format(client: httpx.Client) -> None:
    """Неверный формат ключа - ошибка контракта CV-процесса, не «кадра нет».

    Формат проверяется до обращения к хранилищу, поэтому текст ответа должен
    говорить про формат: иначе причину искали бы в бакете.
    """
    lesson = first_lesson(client)
    student = make_student(client)

    r = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, 3),
            "frame_object_key": "frames/latest.jpg",
        },
    )
    assert r.status_code == 422, r.text
    assert "format" in r.text.lower(), r.text


def test_event_unknown_lesson_404(client: httpx.Client) -> None:
    student = make_student(client)
    r = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": 999999,
            "student_id": student["id"],
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "frame_object_key": f"frames/1/{uuid.uuid4()}.jpg",
        },
    )
    assert r.status_code == 404, r.text


def test_event_bad_group_rejected_before_write(client: httpx.Client) -> None:
    """Кривая группа отсекается на вводе, а не на записи журнала."""
    r = client.post(
        "/api/v1/students",
        json={"full_name": "Тест Невалидный", "group_number": "01-Ф-01"},
    )
    assert r.status_code == 422, r.text


def test_journal_exposes_lesson_window(client: httpx.Client) -> None:
    """Журнал обязан отдавать и конец пары: по нему читатель отличает
    «опоздал» от «пришёл слишком поздно и не учтён»."""
    lesson = first_lesson(client)
    journal = client.get(
        "/api/v1/attendance/journal", params={"lesson_id": lesson["id"]}
    ).json()
    assert journal["end_time"], journal
    assert journal["end_time"] > journal["start_time"], journal


def test_journal_carries_discipline_name(client: httpx.Client) -> None:
    """Раньше имя дисциплины было пустой строкой - фронтенду нечего показать."""
    lesson = first_lesson(client)
    journal = client.get(
        "/api/v1/attendance/journal", params={"lesson_id": lesson["id"]}
    ).json()
    assert journal["discipline_name"], journal
    assert journal["lesson_date"] == lesson["lesson_date"]
