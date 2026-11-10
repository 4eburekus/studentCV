"""Схема статуса S3-хранилища для healthz.

Строгие значения вместо "ok"|"down": состояние unknown отличает «проверили и
не поняли» от «MinIO/SeaweedFS лежит», и app.storage_warnings даёт оператору
причину без чтения логов.
"""

from typing import Literal

from pydantic import BaseModel

StorageStatus = Literal["ok", "down", "unconfigured", "degraded"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    # "ok" означает не только «порт отвечает», но и «бакеты созданы и
    # versioning включён» - иначе первая же запись эталона кончится 500,
    # пока healthz показывает зелёный.
    database: Literal["ok", "down"]
    storage: StorageStatus
    # Проблемы провижининга (например, хранилище старше 4.49 и не умеет
    # versioning). Здесь же причина состояния unconfigured.
    storage_warnings: list[str] = []
    version: str = "0.2"
