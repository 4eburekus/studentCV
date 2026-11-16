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


def db_call(fn):
    """Выполнить асинхронную функцию с СОБСТВЕННЫМ движком и своим циклом.

    Тесты ходят в БД напрямую там, где для этого нет эндпоинта (создать пару,
    поставить флаг ручной правки, проверить констрейнт). Глобальный SessionLocal
    для этого не годится: asyncio.run создаёт новый цикл на каждый вызов, а пул
    глобального движка переживает его и отдаёт соединение, присоединённое к
    закрытому циклу - RuntimeError "attached to a different loop". Ошибка
    плавающая (зависит от того, был ли пул прогрет в этом процессе), поэтому
    каждый такой вызов получает движок, который умирает вместе со своим циклом.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from db.session import DATABASE_URL

    async def main():
        engine = create_async_engine(DATABASE_URL, pool_size=1, max_overflow=0)
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            async with factory() as session:
                return await fn(session)
        finally:
            await engine.dispose()

    return asyncio.run(main())


def make_lesson_group(client: httpx.Client) -> dict:
    """Своя пара со СВОЕЙ группой на завтра - фундамент тестов посещаемости.

    Почему нельзя было взять «первую пару из расписания», как делали раньше:
    ABSENT теперь тоже строка журнала, и планировщик закрывает истёкшие пары.
    Сидовые пары стоят на текущую учебную неделю, вечером они истекают - и
    чужой фоновый прогон вставлял бы строки ABSENT в журнал ровно в тот момент,
    когда тест проверяет «этого студента в журнале нет». Гонка, а не проверка.

    Здесь же пара изолирована дважды:
    - group_number уникальна, поэтому в состав журнала входит ровно один
      студент - тот, кого создал этот тест (у сидовых групп десятки студентов
      из прошлых прогонов);
    - lesson_date завтрашняя, поэтому пара не может ни истечь, ни быть закрытой
      ни при каком времени суток - тесты не зависят от часового пояса и от
      того, когда их запустили.

    Пишем в БД напрямую, а не через API: расписание ведётся отдельным контуром,
    POST /lessons в этом срезе нет (см. LessonRead в app/schemas/lesson.py).
    """
    from datetime import date, time

    from db.models import Lesson

    base = first_lesson_any(client)
    group = unique_group()
    lesson_date = date.today() + timedelta(days=1)

    async def create(s) -> int:
        lesson = Lesson(
            discipline_id=base["discipline_id"],
            group_number=group,
            # Завтра: пара не может истечь ни при каком времени суток, поэтому
            # фоновое закрытие до неё не доберётся никогда.
            lesson_date=lesson_date,
            start_time=time(8, 30),
            end_time=time(10, 0),
        )
        s.add(lesson)
        await s.commit()
        return lesson.id

    lesson_id = db_call(create)
    return {
        "id": lesson_id,
        "discipline_id": base["discipline_id"],
        "group_number": group,
        "lesson_date": (date.today() + timedelta(days=1)).isoformat(),
        "start_time": "08:30",
        "end_time": "10:00",
        "closed_at": None,
    }


def first_lesson_any(client: httpx.Client) -> dict:
    """Любая существующая пара - нужна только чтобы взять её дисциплину."""
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
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])
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
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])
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

    # Раннее событие (ровно начало) перебивает позднее записанное. Кадр у него
    # СВОЙ: вместе со временем входа обязан перезаписаться и его адрес, иначе в
    # журнале остался бы снимок от более позднего прохода.
    early_key = make_frame_key(lesson["id"])
    second = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, 0),
            "frame_object_key": early_key,
        },
    )
    assert second.status_code == 201, second.text
    body = second.json()

    assert body["outcome"] == "recorded"
    assert body["record"]["id"] == first["record"]["id"]
    assert body["record"]["status"] == "LATE"
    assert body["record"]["delay_minutes"] == 0
    assert body["record"]["frame_object_key"] == early_key, (
        "доказательство обязано соответствовать засчитанному входу"
    )

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
    # И ключ тоже остался от РАННЕГО входа: поздний кадр не затёрт.
    assert third_body["record"]["frame_object_key"] == early_key, third_body

    journal = client.get(
        "/api/v1/attendance/journal", params={"lesson_id": lesson["id"]}
    ).json()
    rows = [e for e in journal["entries"] if e["student_id"] == student["id"]]
    assert len(rows) == 1, f"дубль в журнале: {len(rows)} записей"


def test_event_at_start_time_is_late_zero(client: httpx.Client) -> None:
    """Ровно в начало - LATE с 0 минутами (согласовано 10.11.2026).

    Прежнее имя и ожидание (PRESENT) закрепляли наше допущение, а не правило.
    """
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])
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
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])
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
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])
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
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])
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

    from sqlalchemy import text as sa_text

    async def mark_manual(s) -> None:
        await s.execute(
            sa_text(
                "update attendance_records set is_manually_edited = true "
                "where id = :id"
            ),
            {"id": first["record"]["id"]},
        )
        await s.commit()

    db_call(mark_manual)

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
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])
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
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])
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
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])

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
    lesson = make_lesson_group(client)
    journal = client.get(
        "/api/v1/attendance/journal", params={"lesson_id": lesson["id"]}
    ).json()
    assert journal["end_time"], journal
    assert journal["end_time"] > journal["start_time"], journal


def test_journal_carries_discipline_name(client: httpx.Client) -> None:
    """Раньше имя дисциплины было пустой строкой - фронтенду нечего показать."""
    lesson = make_lesson_group(client)
    journal = client.get(
        "/api/v1/attendance/journal", params={"lesson_id": lesson["id"]}
    ).json()
    assert journal["discipline_name"], journal
    assert journal["lesson_date"] == lesson["lesson_date"]


def test_event_returns_and_stores_frame_key(client: httpx.Client) -> None:
    """Адрес снимка должен ДОХОДИТЬ до читателя, а не только записываться.

    Смысл колонки ровно один: открыть кадр у спорной отметки перед ручной
    правкой. Если API её не отдаёт, колонка бесполезна для фронта, и проверка
    «ключ где-то лежит в базе» этого не поймает - поэтому проверяем и ответ
    события, и строку журнала.
    """
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])
    key = make_frame_key(lesson["id"])

    body = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, 7),
            "frame_object_key": key,
        },
    ).json()

    assert body["record"]["frame_object_key"] == key, body
    assert body["outcome"] == "recorded", body

    entry = journal(client, lesson["id"])["entries"][0]
    assert entry["frame_object_key"] == key, entry
    assert entry["status"] == "LATE", entry


def test_closed_absent_row_has_no_frame_key(client: httpx.Client) -> None:
    """У ABSENT от закрытия пары кадра нет - и это проверка на обе стороны.

    Обратный случай (у закрытой пары появился адрес снимка) означал бы, что
    закрытие выдумало доказательство входа, которого не было.
    """
    lesson = make_lesson_group(client)
    make_student(client, group=lesson["group_number"])

    close(client, lesson["id"])

    entry = journal(client, lesson["id"])["entries"][0]
    assert entry["status"] == "ABSENT", entry
    assert entry["frame_object_key"] is None, entry
    assert entry["entry_time"] is None, entry


# --- закрытие пары и ABSENT как запись ----------------------------------------
#
# Общий смысл этих проверок: отсутствие студента теперь ВЫРАЖЕНО строкой.
# До этого «записи нет» значило «не пришёл», и журнал не мог показать состав
# группы вообще. Поэтому тут проверяются не только статусы, но и то, чего
# раньше в модели не было: entry_time IS NULL у ABSENT, идемпотентность
# закрытия и неприкосновенность живой отметки.


def close(client: httpx.Client, lesson_id: int) -> dict:
    """Нажатие кнопки «завершить пару»."""
    r = client.post(f"/api/v1/attendance/lessons/{lesson_id}/close")
    assert r.status_code == 200, r.text
    return r.json()


def journal(client: httpx.Client, lesson_id: int) -> dict:
    r = client.get("/api/v1/attendance/journal", params={"lesson_id": lesson_id})
    assert r.status_code == 200, r.text
    return r.json()


def test_close_creates_absent_rows(client: httpx.Client) -> None:
    """Закрытие проставляет ABSENT тому, кто не отметился.

    Проверяем суть, а не только код ответа: строка обязана быть именно
    записью с null-временем входа, иначе «отсутствие» по-прежнему было бы
    отсутствием строки.
    """
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])

    before = journal(client, lesson["id"])
    assert before["entries"] == [], "у новой пары не должно быть записей"
    assert before["closed_at"] is None

    body = close(client, lesson["id"])
    assert body["absent_created"] == 1, body
    assert body["already_recorded"] == 0, body
    assert body["was_already_closed"] is False, body
    assert body["group_number"] == lesson["group_number"], body

    after = journal(client, lesson["id"])
    assert after["total"] == 1, after
    entry = after["entries"][0]
    assert entry["status"] == "ABSENT", entry
    assert entry["entry_time"] is None, entry
    assert entry["delay_minutes"] is None, entry
    assert entry["student_id"] == student["id"], entry
    assert after["closed_at"], "закрытая пара обязана показать момент закрытия"


def test_close_is_idempotent(client: httpx.Client) -> None:
    """Повторное закрытие не удваивает отсутствий и не портит журнал.

    Это опора и на кнопку (двойной клик, запрос повторно), и на планировщик:
    они вызывают одну функцию, и если бы она была неидемпотентна, журнал
    набивался бы дублями на каждом тике.
    """
    lesson = make_lesson_group(client)
    make_student(client, group=lesson["group_number"])
    make_student(client, group=lesson["group_number"])

    first = close(client, lesson["id"])
    assert first["absent_created"] == 2, first

    second = close(client, lesson["id"])
    assert second["absent_created"] == 0, second
    assert second["was_already_closed"] is True, second

    after = journal(client, lesson["id"])
    assert after["total"] == 2, after
    assert after["closed_at"] == first["closed_at"] or after["closed_at"], after


def test_close_keeps_existing_marks(client: httpx.Client) -> None:
    """Закрытие только добавляет отсутствующее, но не трогает отметку.

    Без этой гарантии кнопка стирала бы реальные посещения: студент,
    пришедший вовремя, получил бы ABSENT просто потому, что пару закрыли.
    """
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])
    key = make_frame_key(lesson["id"])

    posted = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, 5),
            "frame_object_key": key,
        },
    ).json()
    assert posted["record"]["status"] == "LATE", posted

    body = close(client, lesson["id"])
    assert body["absent_created"] == 0, body
    assert body["already_recorded"] == 1, body

    entry = journal(client, lesson["id"])["entries"][0]
    assert entry["status"] == "LATE", entry
    assert entry["delay_minutes"] == 5, entry
    assert entry["entry_time"] is not None, entry


def test_absent_is_overwritten_by_earlier_event(client: httpx.Client) -> None:
    """«Самолечение» ранним событием: ABSENT -> LATE.

    Именно ради этого в upsert добавлена ветка entry_time IS NULL: без неё
    NULL > captured_at даёт NULL, условие не выполняется, и студента,
    замеченного камерой ПОСЛЕ случайного раннего закрытия пары, система
    оставила бы отсутствующим навсегда. Это же делает досрочное нажатие
    кнопки безопасной операцией.
    """
    lesson = make_lesson_group(client)
    student = make_student(client, group=lesson["group_number"])

    close(client, lesson["id"])
    assert journal(client, lesson["id"])["entries"][0]["status"] == "ABSENT"

    key = make_frame_key(lesson["id"])
    result = client.post(
        "/api/v1/attendance/events",
        json={
            "lesson_id": lesson["id"],
            "student_id": student["id"],
            "captured_at": captured_for(lesson, 20),
            "frame_object_key": key,
        },
    ).json()

    assert result["outcome"] == "recorded", result
    entry = journal(client, lesson["id"])["entries"][0]
    assert entry["status"] == "LATE", entry
    assert entry["delay_minutes"] == 20, entry
    assert entry["entry_time"] is not None, entry


def test_close_skips_inactive_students(client: httpx.Client) -> None:
    """Отчисленный не появляется в журнале как прогульщик (требование №6).

    Закрытие берёт только is_active = true. Проверка на несуществующем
    студенте была бы декоративной, поэтому сначала убеждаемся, что строки
    действительно нет.
    """
    lesson = make_lesson_group(client)
    active = make_student(client, group=lesson["group_number"])
    inactive = make_student(client, group=lesson["group_number"])

    r = client.delete(f"/api/v1/students/{inactive['id']}")
    assert r.status_code == 204, r.text

    body = close(client, lesson["id"])
    assert body["absent_created"] == 1, body

    ids = {e["student_id"] for e in journal(client, lesson["id"])["entries"]}
    assert ids == {active["id"]}, ids


def test_close_unknown_lesson_404(client: httpx.Client) -> None:
    r = client.post("/api/v1/attendance/lessons/999999/close")
    assert r.status_code == 404, r.text


def test_journal_of_open_lesson_has_no_absent(client: httpx.Client) -> None:
    """Пока пара не закрыта, отсутствующих в журнале нет - это осознанно.

    Иначе журнал врал бы в разгар пары: опоздавший ещё не отмечен, а ABSENT
    уже стоит. Различить «ещё идёт» и «все пришли» фронт может по closed_at.
    """
    lesson = make_lesson_group(client)
    make_student(client, group=lesson["group_number"])

    body = journal(client, lesson["id"])
    assert body["entries"] == [], body
    assert body["closed_at"] is None


def test_schedule_exposes_group_and_closed_at(client: httpx.Client) -> None:
    """Расписание отдаёт группу и момент закрытия: без них кнопка бесполезна.

    Наличие строк ABSENT про закрытие не говорит - на пару могли прийти все,
    поэтому closed_at и есть единственный корректный признак.
    """
    lesson = make_lesson_group(client)
    close(client, lesson["id"])

    items = client.get(
        "/api/v1/lessons", params={"group_number": lesson["group_number"]}
    ).json()["items"]
    assert len(items) == 1, items
    assert items[0]["group_number"] == lesson["group_number"], items
    assert items[0]["closed_at"], items


def test_schedule_filter_by_group_isolates_lessons(client: httpx.Client) -> None:
    """Фильтр по группе различает параллельные пары одной дисциплины.

    Это ровно то, что стало возможным после входа группы в ключ пары: две
    группы в одном слоте больше не коллизия.
    """
    a = make_lesson_group(client)
    b = make_lesson_group(client)
    assert a["start_time"] == b["start_time"], "слоты должны совпадать по построению"
    assert a["id"] != b["id"], (a, b)

    only_a = client.get(
        "/api/v1/lessons", params={"group_number": a["group_number"]}
    ).json()["items"]
    assert [i["id"] for i in only_a] == [a["id"]], only_a


def test_same_slot_same_group_rejected(client: httpx.Client) -> None:
    """Две пары одной группы в один слот невозможны - ключ по-прежнему защищает.

    Группа добавлена в UNIQUE, а не заменила его: дисциплина + группа + дата +
    время обязаны быть уникальны вместе.
    """
    from datetime import date, time

    from sqlalchemy.exc import IntegrityError

    from db.models import Lesson

    lesson = make_lesson_group(client)

    async def duplicate(s) -> None:
        base = await s.get(Lesson, lesson["id"])
        s.add(
            Lesson(
                discipline_id=base.discipline_id,
                group_number=base.group_number,
                lesson_date=base.lesson_date,
                start_time=base.start_time,
                end_time=base.end_time,
            )
        )
        with pytest.raises(IntegrityError):
            await s.commit()

    db_call(duplicate)


def test_absent_requires_null_entry_time(client: httpx.Client) -> None:
    """CHECK связывает статус и время входа в обе стороны.

    Без него абстрактно можно было бы записать «отсутствовал, но вошёл в
    09:15» - журнал начал бы противоречить сам себе. Проверяем прямым SQL,
    потому что ни один эндпоинт такой строку не создаёт: нарушение констрейнта
    тестируется на том уровне, где он живёт.
    """
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy import text as sa_text

    lesson = make_lesson_group(client)
    # Студент на каждую попытка ОБЯЗАТЕЛЬНО свой: UNIQUE (student_id, lesson_id)
    # иначе отклонил бы вторую и третью вставки раньше, чем до очередь дошла до
    # CHECK, и проверка «констрейнт работает» проходила бы по неверной причине.
    ids = [make_student(client, group=lesson["group_number"])["id"] for _ in range(3)]
    # 09:00 - ПОСЛЕ начала пары (08:30): иначе вставка упала бы на CHECK
    # «entry_time не раньше начала занятия», и проверка CHECK статуса
    # проходила бы по неверной причине.
    entry_time = f"{lesson['lesson_date']}T09:00:00+00:00"

    attempts = [
        ("ABSENT", None, ids[0]),
        ("ABSENT", entry_time, ids[1]),
        ("PRESENT", None, ids[2]),
    ]

    async def run_attempts(s) -> list[bool]:
        results: list[bool] = []
        for status, entry, student_id in attempts:
            try:
                await s.execute(
                    sa_text(
                        "insert into attendance_records "
                        "(student_id, lesson_id, entry_time, status, "
                        " delay_minutes, is_manually_edited) "
                        "values (:st, :le, :et, :stt, null, false)"
                    ),
                    {
                        "st": student_id,
                        "le": lesson["id"],
                        "et": entry,
                        "stt": status,
                    },
                )
                await s.rollback()
                results.append(True)
            except DBAPIError:
                await s.rollback()
                results.append(False)
        return results

    ok_absent, bad_absent, bad_present = db_call(run_attempts)
    assert ok_absent, "ABSENT без времени входа - единственная корректная форма"
    assert not bad_absent, "ABSENT с временем входа обязан нарушать CHECK"
    assert not bad_present, "PRESENT без времени входа обязан нарушать CHECK"
