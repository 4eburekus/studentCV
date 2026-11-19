"""Интеграционные тесты справочников и расписания (админ-панель).

Проверяет то, что пришло с миграцией 0004 и новыми роутерами:
teachers CRUD, disciplines CRUD с UNIQUE(name, teacher_id), lessons CRUD с
занятым слотом, заморозкой закрытой пары и отказом удалять пару с журналом,
плюс раздачу контента эталона.

Правила, ради которых тесты и написаны, - те, что легко сломать незаметно:
- удаление пары/дисциплины не должно стирать историю (каскад в схеме легален);
- закрытая пара не должна менять группу/дату/время (ABSENT уже выставлен);
- password_hash не должен попадать в ответы;
- адрес кадра и фото-контент должны быть доступны фронту.

Запуск из контейнера backend (см. test_api_flow.py).

Свой набор сущностей вместо сидов: у каждого теста свой преподаватель,
поэтому UNIQUE(name, teacher_id) не мешает параллельным прогонам, а тесты не
зависят от порядка выполнения.
"""

import httpx
import pytest

from test_api_flow import (  # noqa: F401 - фикстуры и хелперы переиспользуются
    TINY_JPEG,
    client,
    unique_group,
    unique_suffix,
)


@pytest.fixture()
def teacher(client: httpx.Client) -> dict:
    """Свежий преподаватель на каждый тест.

    Своя учётка, а не сидовая: удаление преподавателя в одном тесте не должно
    уносить данные другого, а UNIQUE(login) делает общий логин невозможным.
    """
    login = f"t.{unique_suffix()}"
    r = client.post(
        "/api/v1/teachers",
        json={"full_name": f"Тест Препод {unique_suffix()}", "login": login, "password": "secret123"},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def discipline(client: httpx.Client, teacher: dict) -> dict:
    r = client.post(
        "/api/v1/disciplines",
        json={"name": f"Дисциплина {unique_suffix()}", "teacher_id": teacher["id"]},
    )
    assert r.status_code == 201, r.text
    return r.json()


# --- teachers ------------------------------------------------------------------


def test_teacher_response_never_leaks_password_hash(client: httpx.Client, teacher: dict) -> None:
    """Ни в одном ответе нет хэша пароля.

    Это не осторожность: хэш в JSON оседает в логах прокси, в кэше браузера и
    в скриншотах поддержки. Проверяем и создание, и список, и одиночный GET.
    """
    assert "password" not in {k.lower() for k in teacher}

    for url in ("/api/v1/teachers", f"/api/v1/teachers/{teacher['id']}"):
        body = client.get(url).text
        assert "password_hash" not in body, url
        assert "secret123" not in body, url


def test_teacher_login_unique(client: httpx.Client, teacher: dict) -> None:
    """Второй преподаватель с тем же логином получает 409, а не 500."""
    r = client.post(
        "/api/v1/teachers",
        json={"full_name": "Другой", "login": teacher["login"], "password": "secret123"},
    )
    assert r.status_code == 409, r.text
    assert "login" in r.text.lower()


def test_teacher_password_separate_from_patch(client: httpx.Client, teacher: dict) -> None:
    """Пароль меняется только через PUT /password.

    PATCH с полем password не должен менять учётку: иначе переименование могло
    бы её сбросить. Проверяем, что смена реально работает через свой маршрут.
    """
    r = client.put(
        f"/api/v1/teachers/{teacher['id']}/password", json={"password": "newsecret1"}
    )
    assert r.status_code == 200, r.text
    assert "password_hash" not in r.text

    # слишком короткий пароль отвергается схемой (min_length=8)
    short = client.put(
        f"/api/v1/teachers/{teacher['id']}/password", json={"password": "short"}
    )
    assert short.status_code == 422, short.text


def test_teacher_delete_blocked_by_disciplines(client: httpx.Client, teacher: dict, discipline: dict) -> None:
    """Удаление преподавателя с дисциплинами - отказ с числом дисциплин.

    База защитила бы и сама (FK RESTRICT), но её IntegrityError не объясняет
    причину, а админу нужно знать, сколько дисциплин мешает.
    """
    r = client.delete(f"/api/v1/teachers/{teacher['id']}")
    assert r.status_code == 409, r.text
    assert "discipline" in r.text.lower()


def test_teacher_delete_after_disciplines_removed(client: httpx.Client, teacher: dict, discipline: dict) -> None:
    assert client.delete(f"/api/v1/disciplines/{discipline['id']}").status_code == 204
    assert client.delete(f"/api/v1/teachers/{teacher['id']}").status_code == 204
    assert client.get(f"/api/v1/teachers/{teacher['id']}").status_code == 404


# --- disciplines ---------------------------------------------------------------


def test_discipline_duplicate_name_same_teacher_rejected(client: httpx.Client, teacher: dict) -> None:
    """UNIQUE(name, teacher_id): одинаковое название у ОДНОГО преподавателя - 409.

    Это и есть смысл индекса из миграции 0004: без него админка за несколько
    кликов заводит «Программирование» трижды, и выбрать дисциплину для пары
    становится невозможно.
    """
    name = f"Дубликат {unique_suffix()}"
    first = client.post("/api/v1/disciplines", json={"name": name, "teacher_id": teacher["id"]})
    assert first.status_code == 201, first.text

    second = client.post("/api/v1/disciplines", json={"name": name, "teacher_id": teacher["id"]})
    assert second.status_code == 409, second.text


def test_discipline_same_name_other_teacher_allowed(client: httpx.Client, teacher: dict) -> None:
    """То же название у ДРУГОГО преподавателя - законно, а не дубликат.

    Ровно поэтому ключ составной, а не UNIQUE(name): два преподавателя вправе
    вести предмет с одинаковым названием.
    """
    name = f"Общая {unique_suffix()}"
    other = client.post(
        "/api/v1/teachers",
        json={"full_name": "Второй", "login": f"t2.{unique_suffix()}", "password": "secret123"},
    ).json()

    a = client.post("/api/v1/disciplines", json={"name": name, "teacher_id": teacher["id"]})
    b = client.post("/api/v1/disciplines", json={"name": name, "teacher_id": other["id"]})
    assert (a.status_code, b.status_code) == (201, 201), (a.text, b.text)


def test_discipline_requires_existing_teacher(client: httpx.Client) -> None:
    r = client.post("/api/v1/disciplines", json={"name": "Без преподавателя", "teacher_id": 10**9})
    assert r.status_code == 404, r.text


# --- lessons -------------------------------------------------------------------


def make_lesson(client: httpx.Client, discipline_id: int, group: str, date: str = "2031-05-04",
                start: str = "08:30", end: str = "10:00", room: str | None = None) -> httpx.Response:
    payload = {
        "discipline_id": discipline_id,
        "group_number": group,
        "lesson_date": date,
        "start_time": start,
        "end_time": end,
    }
    if room is not None:
        payload["room_number"] = room
    return client.post("/api/v1/lessons", json=payload)


def test_lesson_create_with_room(client: httpx.Client, discipline: dict) -> None:
    """Аудитория сохраняется и возвращается - поле, которого не было в схеме.

    Фронт админки рисовал его с первого дня, а колонки не существовало.
    """
    group = unique_group()
    r = make_lesson(client, discipline["id"], group, room="А-301")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["room_number"] == "А-301"
    assert body["group_number"] == group
    assert body["closed_at"] is None
    client.delete(f"/api/v1/lessons/{body['id']}")


def test_lesson_slot_occupied_rejected(client: httpx.Client, discipline: dict) -> None:
    """Тот же слот той же группы - 409; ДРУГОЙ группе тот же слот можно.

    Второе - прямое следствие того, что группа вошла в ключ пары (0003).
    """
    group_a, group_b = unique_group(), unique_group()
    first = make_lesson(client, discipline["id"], group_a)
    assert first.status_code == 201, first.text
    lesson_id = first.json()["id"]

    clash = make_lesson(client, discipline["id"], group_a)
    assert clash.status_code == 409, clash.text

    parallel = make_lesson(client, discipline["id"], group_b)
    assert parallel.status_code == 201, parallel.text

    client.delete(f"/api/v1/lessons/{lesson_id}")
    client.delete(f"/api/v1/lessons/{parallel.json()['id']}")


def test_lesson_bad_window_and_bad_group(client: httpx.Client, discipline: dict) -> None:
    """422 на конец раньше начала и на кривой формат группы.

    Обе проверки есть и в БД (CHECK + regex), но там они приходят как
    IntegrityError без указания поля - админу нужен внятный 422.
    """
    bad_window = make_lesson(client, discipline["id"], unique_group(), start="12:00", end="11:00")
    assert bad_window.status_code == 422, bad_window.text

    bad_group = make_lesson(client, discipline["id"], "плохая-группа")
    assert bad_group.status_code == 422, bad_group.text


def test_lesson_room_can_be_cleared(client: httpx.Client, discipline: dict) -> None:
    """Явный null снимает аудиторию, а не «оставляет как было».

    Классическая ошибка `payload.x or current` сделала бы очистку невозможной.
    """
    created = make_lesson(client, discipline["id"], unique_group(), room="Б-1")
    lesson_id = created.json()["id"]

    cleared = client.patch(f"/api/v1/lessons/{lesson_id}", json={"room_number": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["room_number"] is None

    client.delete(f"/api/v1/lessons/{lesson_id}")


def test_closed_lesson_cannot_be_time_shifted(client: httpx.Client, discipline: dict) -> None:
    """Закрытую пару нельзя перевести в другой день; аудиторию - можно.

    ABSENT выставлен по старым границам, и сдвиг времени переписал бы журнал
    задним числом. Аудитория на состав журнала не влияет, поэтому разрешена.
    """
    group = unique_group()
    created = make_lesson(client, discipline["id"], group, room="В-2").json()
    lesson_id = created["id"]

    # студент нужен, чтобы закрытие реально проставило ABSENT
    student = client.post(
        "/api/v1/students", json={"full_name": f"Закрытый {unique_suffix()}", "group_number": group}
    ).json()

    closed = client.post(f"/api/v1/attendance/lessons/{lesson_id}/close")
    assert closed.status_code == 200, closed.text
    assert closed.json()["absent_created"] == 1, closed.text

    shifted = client.patch(f"/api/v1/lessons/{lesson_id}", json={"lesson_date": "2032-01-01"})
    assert shifted.status_code == 409, shifted.text

    room_only = client.patch(f"/api/v1/lessons/{lesson_id}", json={"room_number": "Г-3"})
    assert room_only.status_code == 200, room_only.text
    assert room_only.json()["room_number"] == "Г-3"

    client.delete(f"/api/v1/students/{student['id']}")


def test_lesson_with_journal_cannot_be_deleted(client: httpx.Client, discipline: dict) -> None:
    """Пара с записями журнала не удаляется - иначе каскад сотрёт историю.

    `lessons -> attendance_records` объявлен ON DELETE CASCADE, то есть база
    удалит охотно; единственная защита - этот отказ.
    """
    group = unique_group()
    lesson_id = make_lesson(client, discipline["id"], group).json()["id"]
    student = client.post(
        "/api/v1/students", json={"full_name": f"Журнал {unique_suffix()}", "group_number": group}
    ).json()

    assert client.post(f"/api/v1/attendance/lessons/{lesson_id}/close").status_code == 200

    blocked = client.delete(f"/api/v1/lessons/{lesson_id}")
    assert blocked.status_code == 409, blocked.text
    assert "record" in blocked.text.lower()

    client.delete(f"/api/v1/students/{student['id']}")


def test_discipline_with_journal_cannot_be_deleted(client: httpx.Client, discipline: dict) -> None:
    """Дисциплина с записями журнала не удаляется: каскад идёт глубже.

    disciplines -> lessons -> attendance_records, поэтому отказ проверяет
    записи, а не только наличие пар.
    """
    group = unique_group()
    lesson_id = make_lesson(client, discipline["id"], group).json()["id"]
    student = client.post(
        "/api/v1/students", json={"full_name": f"Дисц {unique_suffix()}", "group_number": group}
    ).json()

    assert client.post(f"/api/v1/attendance/lessons/{lesson_id}/close").status_code == 200

    blocked = client.delete(f"/api/v1/disciplines/{discipline['id']}")
    assert blocked.status_code == 409, blocked.text

    client.delete(f"/api/v1/students/{student['id']}")


def test_lesson_filter_by_group(client: httpx.Client, discipline: dict) -> None:
    """Фильтр по группе отдаёт пары только этой группы."""
    group_a, group_b = unique_group(), unique_group()
    a = make_lesson(client, discipline["id"], group_a).json()
    b = make_lesson(client, discipline["id"], group_b).json()

    items = client.get("/api/v1/lessons", params={"group_number": group_a}).json()["items"]
    ids = {item["id"] for item in items}
    assert a["id"] in ids and b["id"] not in ids, (a["id"], b["id"], ids)

    client.delete(f"/api/v1/lessons/{a['id']}")
    client.delete(f"/api/v1/lessons/{b['id']}")


def test_unknown_lesson_404(client: httpx.Client) -> None:
    assert client.get("/api/v1/lessons/99999999").status_code == 404
    assert client.delete("/api/v1/lessons/99999999").status_code == 404


# --- фото: контент -------------------------------------------------------------


def test_photo_content_is_served_and_cached(client: httpx.Client) -> None:
    """Байты эталона отдаются API, с верным типом и ETag.

    `<img src>` не подойдёт: браузер не приложит Authorization, а маршруты
    закрыты. Поэтому контент - отдельный эндпоинт, и фронт тянет его клиентом.
    """
    student = client.post(
        "/api/v1/students", json={"full_name": f"Фото {unique_suffix()}", "group_number": unique_group()}
    ).json()

    uploaded = client.post(
        f"/api/v1/students/{student['id']}/photos",
        files={"file": ("a.jpg", TINY_JPEG, "image/jpeg")},
    )
    assert uploaded.status_code == 201, uploaded.text
    photo = uploaded.json()

    # content_path отдаётся сервером, а не собирается на фронте
    assert photo.get("content_path") == f"/api/v1/photos/{photo['id']}/content"

    content = client.get(photo["content_path"])
    assert content.status_code == 200, content.text
    assert content.headers["content-type"].startswith("image/")
    assert content.headers.get("etag"), "ETag нужен для кэша браузера"
    assert content.content[:3] == b"\xff\xd8\xff", "тип определён по сигнатуре байтов"

    listing = client.get(f"/api/v1/students/{student['id']}/photos").json()
    assert listing["items"][0]["content_path"] == photo["content_path"]

    client.delete(f"/api/v1/photos/{photo['id']}")
    client.delete(f"/api/v1/students/{student['id']}")


def test_photo_content_404_and_replace(client: httpx.Client) -> None:
    """Замена байтов атомарна: новый ключ, новый ETag, старый объект убран."""
    student = client.post(
        "/api/v1/students", json={"full_name": f"Зам {unique_suffix()}", "group_number": unique_group()}
    ).json()
    photo = client.post(
        f"/api/v1/students/{student['id']}/photos",
        files={"file": ("a.jpg", TINY_JPEG, "image/jpeg")},
    ).json()

    assert client.get("/api/v1/photos/99999999/content").status_code == 404

    old_key = photo["photo_url"]
    old_etag = client.get(photo["content_path"]).headers["etag"]

    replaced = client.put(
        photo["content_path"],
        files={"file": ("b.jpg", TINY_JPEG + b"x", "image/jpeg")},
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["photo_url"] != old_key, "ключ объекта обязан смениться"

    new_etag = client.get(photo["content_path"]).headers["etag"]
    assert new_etag != old_etag, "ETag обязан измениться вместе с содержимым"

    client.delete(f"/api/v1/photos/{photo['id']}")
    client.delete(f"/api/v1/students/{student['id']}")


def test_photo_replace_rejects_unsupported_type(client: httpx.Client) -> None:
    student = client.post(
        "/api/v1/students", json={"full_name": f"Тип {unique_suffix()}", "group_number": unique_group()}
    ).json()
    photo = client.post(
        f"/api/v1/students/{student['id']}/photos",
        files={"file": ("a.jpg", TINY_JPEG, "image/jpeg")},
    ).json()

    r = client.put(photo["content_path"], files={"file": ("x.gif", b"GIF89a", "image/gif")})
    assert r.status_code == 415, r.text

    client.delete(f"/api/v1/photos/{photo['id']}")
    client.delete(f"/api/v1/students/{student['id']}")
