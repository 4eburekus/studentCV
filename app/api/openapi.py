"""Обязательства в OpenAPI, которые нельзя вывести из кода молча.

FastAPI сам описывает успешный код и автоматическую валидацию тела, но НЕ
описывает коды, которые обработчик поднимает через HTTPException, и НЕ
описывает требование авторизации. Из-за этого /openapi.json обещал ровно два
кода (201 и 422) на приёмнике событий, хотя по факту и по тестам их шесть, а
securitySchemes отсутствовали вовсе: фронтенд, который пишется по этому
контракту, не узнавал, что /api/v1/* требуют преподавателя.

Всё, что здесь задекларировано, сверено с поведением (FastAPI 0.115):
 - HTTPBearer(auto_error=True) отдаёт 403, поэтому для честного 401 в
   dependencies.py используется auto_error=False и своя проверка;
 - объявленный вручную "422" в responses= ПЕРЕЗАТИРАЕТ схему HTTPValidationError,
   которую FastAPI добавляет сам. Оба тела приходят по факту (ручная ошибка -
   {detail: "текст"}, автовалидация - {detail: [{loc,msg,type}]}), поэтому
   HTTPErrorBody описывает detail как строку, объект И список: иначе контракт
   врал бы про автовалидацию.

Фронт строится по OpenAPI - значит здесь обязано быть всё, что делает API.
"""

from typing import Any

from pydantic import BaseModel

# Схема из app/dependencies.py. Экспортируем её здесь, а не создаём вторую:
# FastAPI регистрирует securityScheme по объекту зависимости, и второй экземпляр
# дал бы в спеке две схемы авторизации при одной реальной.
from app.dependencies import bearer_scheme

__all__ = [
    "bearer_scheme",
    "HTTPErrorBody",
    "error",
    "error422",
    "ok",
    "merge",
    "R401",
    "R404",
    "R409",
    "R415",
    "R422",
    "R503",
]


class HTTPErrorBody(BaseModel):
    """Тело ошибки FastAPI.

    detail - строка, объект ИЛИ список:
      * строка - обычные HTTPException;
      * объект - структурированные ошибки (нарушение правила 1-5 отдаёт
        message, photos_total, min_photos, max_photos);
      * список - автоматическая валидация тела/параметров (HTTPValidationError).
    """

    detail: str | dict[str, Any] | list[dict[str, Any]]


def error(description: str) -> dict:
    """Описание кода ошибки для responses=..."""
    return {
        "description": description,
        "content": {
            "application/json": {"schema": HTTPErrorBody.model_json_schema()}
        },
    }


def ok(description: str, model) -> dict:
    """Описание УСПЕШНОГО кода, отличного от основного status_code.

    Нужен для приёмника событий: маршрут объявлен как 201, но по правилу
    "проигнорировано" возвращает 200. FastAPI схему для второго кода сам не
    подставит, а без неё клиент получил бы недокументированный ответ.
    model - pydantic-класс.
    """
    return {
        "description": description,
        "content": {"application/json": {"schema": model.model_json_schema()}},
    }


# Формулировки живут здесь, а не в каждом обработчике: один и тот же случай не
# должен описываться в разных эндпоинтах по-разному.
R401 = {"401": error(
    "Клиент не представился: заголовок Authorization отсутствует. "
    "Проверка подлинности токена сейчас не выполняется (заглушка, "
    "требование №11 закрыто частично)."
)}
R404 = {"404": error("Объект не найден.")}
R409 = {"409": error(
    "Конфликт состояния: студент выбыл, запись исправлена руками "
    "или объект уже существует."
)}
R415 = {"415": error("Неподдерживаемый тип содержимого: принимаются только jpeg и png.")}
R503 = {"503": error("Зависимость недоступна: база данных или хранилище не отвечают.")}

# 204 здесь намеренно нет: у ответа нет тела, и FastAPI описывает его сам.
# Объявлять content для 204 - значит вруть в контракте.


def error422(description: str) -> dict:
    """422 как oneOf: ручная ошибка формата И автоматическая валидация тела.

    Объявленный вручную "422" в responses= перезатрает схему
    HTTPValidationError, которую FastAPI добавляет сам (проверено). Один только
    HTTPErrorBody описывал бы ручные ошибки и молчал про прокидывание
    min_length/неизвестных полей; одна только HTTPValidationError - наоборот.
    Здесь оба случая, и ни одна из сторон не врёт.
    """
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": {
                    "oneOf": [
                        {"$ref": "#/components/schemas/HTTPValidationError"},
                        HTTPErrorBody.model_json_schema(),
                    ]
                }
            }
        },
    }


R422 = {
    "422": error422(
        "Данные не подходят контракту: неверный формат (номера группы или "
        "ключа кадра), нарушение лимита 1-5 или невалидное тело запроса."
    )
}


def merge(*groups: dict) -> dict:
    """Собирает responses= из нескольких наборов.

    Нужен, чтобы обработчик не переписывал литерал заново каждый раз, когда
    добавляется ещё один код: слияние словарей оставляет только последний
    набор при пересечении ключей, поэтому ключи в группах не должны повторяться.
    """
    out: dict = {}
    for group in groups:
        for key, value in group.items():
            if key in out:
                raise ValueError(f"duplicate response code in contract: {key}")
            out[key] = value
    return out
