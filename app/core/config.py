"""Настройки приложения из переменных окружения.

Единственный источник значений конфигурации: модули не читают os.getenv
напрямую (кроме db/session.py, где DSN нужен для Alembic и сидов).
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Приложение ------------------------------------------------------------
    api_port: int = Field(default=8000, alias="API_PORT")
    sql_echo: bool = Field(default=False, alias="SQL_ECHO")

    # --- Хранилище S3 (SeaweedFS) ---------------------------------------------
    # s3_endpoint - адрес ВНУТРИ сети compose (http://storage:8333). Для
    # нативного CV-процесса с хост-машины это http://127.0.0.1:8333.
    s3_endpoint: str = Field(default="http://storage:8333", alias="S3_ENDPOINT")
    # Ключи называются STORAGE_ADMIN_*: это ровно та же пара, из которой
    # entrypoint хранилища генерирует s3.json. Второй пары (S3_ACCESS_KEY) в
    # .env быть не должно - иначе провижининг и приложение живут разными
    # учётками, и расхождение всплывёт как AccessDenied в рантайме.
    s3_access_key: str = Field(
        default="studentcv-backend", alias="STORAGE_ADMIN_ACCESS_KEY"
    )
    s3_secret_key: str = Field(
        default="change_me_storage_secret", alias="STORAGE_ADMIN_SECRET_KEY"
    )
    # Region для SigV4 обязателен, но SeaweedFS его содержательно не
    # интерпретирует - оставили us-east-1 как нейтральное значение.
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_bucket_biometrics: str = Field(
        default="biometrics", alias="S3_BUCKET_BIOMETRICS"
    )
    s3_bucket_frames: str = Field(default="frames", alias="S3_BUCKET_FRAMES")

    # ЗАГОТОВКА (не включена): подпись содержит хост endpoint_public -
    # internal http://storage:8333 браузер не достанет. Срез presigned-загрузки
    # начнётся с решения о топологии фронта, тогда же задаём http://127.0.0.1:8333.
    s3_endpoint_public: str | None = Field(
        default=None, alias="S3_ENDPOINT_PUBLIC"
    )

    # --- Авторизация ------------------------------------------------------------
    # STUB: требование №11 (доступ только у авторизованного преподавателя)
    # реальным входом не закрыто. См. app/dependencies.get_current_teacher.
    auth_stub_login: str = Field(default="teacher", alias="AUTH_STUB_LOGIN")
    auth_stub_enabled: bool = Field(default=True, alias="AUTH_STUB_ENABLED")

    # --- Бизнес-правила ---------------------------------------------------------
    # Требование №8: эталонных фото на студента от 1 до 5.
    # Нижняя граница НЕ блокирует удаление последнего: согласовано 10.11.2026
    # «разрешить и предупреждать». Состояние «эталонов меньше min_photos»
    # отдаётся полем warning в GET-списке фото - там, где фронтенд его и покажет;
    # в ответ DELETE (204 без тела) предупреждение поместить некуда.
    min_photos: int = Field(default=1, alias="MIN_PHOTOS")
    max_photos: int = Field(default=5, alias="MAX_PHOTOS")


@lru_cache
def get_settings() -> Settings:
    """Кэш значений: окружение не меняется между запросами."""
    return Settings()


def validate_settings(settings: Settings) -> None:
    """Проверка конфигурации при старте.

    Заглушка авторизации не имеет права уехать в прод по невнимательности:
    при AUTH_STUB_ENABLED=false приложение не поднимается, пока требование
    №11 не закрыто реальным входом (сессии/JWT, интеграция с ЕИОС).
    """
    if not settings.auth_stub_enabled:
        raise RuntimeError(
            "AUTH_STUB_ENABLED=false, но реальный вход ещё не реализован: "
            "требование N11 не закрыто. Включите заглушку (AUTH_STUB_ENABLED=true) "
            "для разработки либо дождитесь среза авторизации."
        )
