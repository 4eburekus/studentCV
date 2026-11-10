"""Клиент объектного хранилища (S3-совместимый API SeaweedFS).

Клиент асинхронный (aioboto3) принципиально: синхронный boto3 внутри
async-обработчика блокирует event loop на время сетевого запроса.

Приложение НЕ знает, какое хранилище за эндпоинтом: весь код говорит по
generic S3 (SigV4, path-style). Отличие SeaweedFS от MinIO учтено здесь только
в двух местах - версионирование доступно с 4.49 (см. ensure_buckets) и
don't-care про region.

Бакеты:
 - biometrics - эталонные фото, ключ <uuid4>.jpg, владеет API;
 - frames     - доказательные кадры, ключ <lesson_id>/<uuid4>.jpg,
                пишет нативный CV-процесс, API только проверяет существование.
"""

import hashlib
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

import aioboto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings, get_settings


class ObjectNotFound(Exception):
    """Объекта в бакете нет. Отличаем от сетевой ошибки намеренно:
    это штатный ответ предметной области (404/422), а не авария."""

    def __init__(self, bucket: str, key: str) -> None:
        super().__init__(f"object {key} not found in bucket {bucket}")
        self.bucket = bucket
        self.key = key


class StorageError(Exception):
    """Хранилище недоступно или отклонило операцию. Отвечать за это 404
    нельзя - это 503 для клиента и сигнал оператору."""


class ProvisioningError(StorageError):
    """Хранилище отвечает, но бакета нет: провижининг не выполнился.

    Отдельный класс, а не подкласс StorageError, чтобы healthz различал
    «гейтвей лежит» и «гейтвей жив, конфигурации нет» - у них разные
    действия оператора (ждать/перезапустить storage vs перезапустить backend).
    """


@lru_cache
def _session() -> aioboto3.Session:
    """Один Session на процесс: клиенты строятся дёшево, сессия держит конфигурацию."""
    return aioboto3.Session()


@asynccontextmanager
async def _client(settings: Settings) -> AsyncIterator:
    """Клиент S3.

    try/except ВОКРУГ `yield` здесь ставить нельзя. Когда код вызывающего
    слоя бросает исключение внутри `async with _client(...) as client:`,
    Python через athrow поднимает его ровно на строке `yield` - и blanket
    except перехватил бы ObjectNotFound вызывающего и превратил в
    StorageError. На приёмке это дало healthz "storage: down" при живом
    MinIO, а приёмник событий потерял бы различие «кадра нет» (422) /
    «MinIO упал» (503). Ошибки транслируются в каждой операции отдельно.
    """
    async with _session().client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    ) as client:
        yield client


def _wrap(exc: Exception, bucket: str, key: str, operation: str) -> Exception:
    """ClientError/BotoCoreError -> ObjectNotFound (404) либо StorageError."""
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NoSuchBucket", "NotFound"):
            return ObjectNotFound(bucket, key)
        return StorageError(f"{operation} {key} rejected: {exc}")
    return StorageError(f"storage unavailable for {operation} {key}: {exc}")


# Префикс ключа объекта. ИМЕННО он входит в photo_url и проверяется CHECK'ом
# (PHOTO_KEY_REGEX в db/models.py), поэтому это константа, а НЕ имя бакета
# из настроек: иначе переименование бакета через env сломало бы вставку
# в student_photos с невнятной ошибкой констрейнта.
BIOMETRICS_KEY_PREFIX = "biometrics"
FRAMES_KEY_PREFIX = "frames"


def new_biometric_key() -> str:
    """Ключ эталонного фото: biometrics/<uuid4>.jpg (см. PHOTO_KEY_REGEX)."""
    return f"{BIOMETRICS_KEY_PREFIX}/{uuid.uuid4()}.jpg"


def new_frame_key(lesson_id: int) -> str:
    """Ключ доказательного кадра: frames/<lesson_id>/<uuid4>.jpg."""
    return f"{FRAMES_KEY_PREFIX}/{lesson_id}/{uuid.uuid4()}.jpg"


# Формат ключа кадра. Единственный источник - этот модуль: он же генерирует
# ключ (new_frame_key), он же проверяет приходящий из CV-процесса. В БД ключ
# не хранится, CHECK на него невозможен, поэтому в db/models.py его нет
# намеренно - вторая копия схемы всегда разъезжается с первой.
FRAME_KEY_RE = re.compile(
    r"^frames/[0-9]+/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}"
    r"-[0-9a-f]{4}-[0-9a-f]{12}\.jpg$"
)


def is_frame_key(key: str) -> bool:
    """Проверка формата ключа кадра до обращения к хранилищу.

    Формат проверяем раньше head_object: мусорный ключ - ошибка контракта
    (422, правка на стороне CV-процесса), а "хороший ключ, объекта нет" -
    совсем другой случай, и путать их нельзя.
    """
    return bool(FRAME_KEY_RE.match(key))


def compute_content_hash(payload: bytes) -> str:
    """SHA-256 содержимого, hex, нижний регистр, 64 символа (CHAR(64) в БД)."""
    return hashlib.sha256(payload).hexdigest()


async def put_object(
    bucket: str,
    key: str,
    payload: bytes,
    content_type: str = "image/jpeg",
) -> None:
    """Загрузка объекта.

    Ошибку не глотаем: вызывающий сервис обязан удалить осиротевший объект,
    если вставка строки в БД не удалась.
    """
    async with _client(get_settings()) as client:
        try:
            await client.put_object(
                Bucket=bucket,
                Key=key,
                Body=payload,
                ContentType=content_type,
            )
        except (ClientError, BotoCoreError) as exc:
            raise _wrap(exc, bucket, key, "put_object") from exc


async def get_object(bucket: str, key: str) -> bytes:
    """Скачивание объекта целиком.

    Применимо только к эталонным фото (единичные кадры небольшого размера);
    для будущих объёмов нужна потоковая выдача.
    """
    async with _client(get_settings()) as client:
        try:
            response = await client.get_object(Bucket=bucket, Key=key)
            async with response["Body"] as stream:
                return await stream.read()
        except (ClientError, BotoCoreError) as exc:
            raise _wrap(exc, bucket, key, "get_object") from exc


async def head_object(bucket: str, key: str) -> dict:
    """Проверка существования без скачивания. Возвращает метаданные объекта.

    Именно эта операция - основа сверки «строка в БД ↔ объект в бакете»
    вместе с content_hash.
    """
    async with _client(get_settings()) as client:
        try:
            return await client.head_object(Bucket=bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            raise _wrap(exc, bucket, key, "head_object") from exc


async def object_exists(bucket: str, key: str) -> bool:
    try:
        await head_object(bucket, key)
        return True
    except ObjectNotFound:
        return False


async def list_probe(bucket: str) -> None:
    """Зонд «бакет существует и доступен» для healthz.

    ListObjectsV2 выбран не случайно: head_object на отсутствующий ключ
    даёт 404 и по нему не отличить «ключ нет» от «бакет нет», а успешный
    list - это 200 даже для пустого бакета. 404/NoSuchBucket здесь значит
    ровно одно: бакета нет, провижининг не выполнен.
    """
    async with _client(get_settings()) as client:
        try:
            await client.list_objects_v2(Bucket=bucket, MaxKeys=1)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchBucket", "404", "NotFound"):
                raise ProvisioningError(f"bucket {bucket!r} does not exist") from exc
            raise StorageError(f"list_probe {bucket} rejected: {exc}") from exc
        except (BotoCoreError, OSError) as exc:
            raise StorageError(f"storage unavailable for list_probe {bucket}: {exc}") from exc


async def delete_object(bucket: str, key: str) -> bool:
    """Удаление объекта.

    Возвращает True, если объект был удалён, False - если его уже нет.
    MinIO отвечает успехом и на удаление несуществующего ключа, поэтому
    предварительный head - не лишняя проверка, а источник честного результата.
    """
    try:
        await head_object(bucket, key)
    except ObjectNotFound:
        return False

    async with _client(get_settings()) as client:
        try:
            await client.delete_object(Bucket=bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            raise _wrap(exc, bucket, key, "delete_object") from exc
    return True


async def ensure_buckets() -> list[str]:
    """Создать бакеты и включить versioning. Вызывается из lifespan приложения.

    Почему из приложения, а не init-контейнером (как было с MinIO):
     1) versioning обязан быть включён ДО первой записи - версии объектов,
        созданных до включения, не появляются задним числом;
     2) учётки SeaweedFS декларативны (s3.json строит entrypoint), а создание
        бакетов и версий это обычный S3 API - отдельный сервис и гонка
        "backend успел раньше провижининга" просто не нужны.

    Idempotent: AlreadyOwned/AlreadyExists считаем успехом. Возвращает список
    проблем, о которых стоит узнать оператору (например, версия хранилища не
    умеет versioning) - падать из-за них приложение не должно.
    """
    settings = get_settings()
    problems: list[str] = []

    async with _client(settings) as client:
        for bucket in (settings.s3_bucket_biometrics, settings.s3_bucket_frames):
            try:
                await client.create_bucket(Bucket=bucket)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                # AlreadyExists - бакет есть (наш или чужой), BucketAlreadyOwnedByYou
                # - стандартный ответ S3 на повторное создание.
                if code not in ("BucketAlreadyExists", "BucketAlreadyOwnedByYou"):
                    problems.append(f"create_bucket {bucket}: {code}")
                    continue

            try:
                await client.put_bucket_versioning(
                    Bucket=bucket,
                    VersioningConfiguration={"Status": "Enabled"},
                )
            except (ClientError, BotoCoreError) as exc:
                # NotImplemented = хранилище старше 4.49 (на 3.83 проверено:
                # 501). Не фатально: эталоны защищены ключом-uuid (новый файл =
                # новый ключ), но ретентера нет - оператор должен это видеть.
                problems.append(f"versioning {bucket}: {code_of(exc)}")

    return problems


def code_of(exc: Exception) -> str:
    """Краткий код ошибки для логов и предупреждений healthz."""
    if isinstance(exc, ClientError):
        return exc.response.get("Error", {}).get("Code", "Unknown")
    return type(exc).__name__


async def presigned_put_url(bucket: str, key: str, expires_in: int = 300) -> str:
    """Presigned URL для прямой загрузки из браузера.

    ЗАГОТОВКА, из эндпоинтов не вызывается: выдача зависит от топологии
    фронта (S3_ENDPOINT_PUBLIC), и URL, подписанный внутренним адресом
    http://storage:8333, браузер не достанет. Работоспособность presigned на
    SeaweedFS подтверждена прогоном 10.11.2026 (aioboto3 -> валидный URL с
    хостом из endpoint_public). Включается срезом presigned-загрузки.
    """
    settings = get_settings()
    endpoint = settings.s3_endpoint_public or settings.s3_endpoint
    async with _session().client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    ) as client:
        try:
            return await client.generate_presigned_url(
                "put_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except (ClientError, BotoCoreError) as exc:
            raise _wrap(exc, bucket, key, "presign") from exc
