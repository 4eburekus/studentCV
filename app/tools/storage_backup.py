"""Дамп и восстановление объектного хранилища (S3-API).

    python -m app.tools.storage_backup dump    --dir /backups/storage-<stamp>
    python -m app.tools.storage_backup restore --dir /backups/storage-<stamp>
    python -m app.tools.storage_backup verify  --dir /backups/storage-<stamp>

Почему на уровне S3-API, а не weed filer.backup:
 - weed-механизмы (filer.backup/replicate/sync) рассчитаны на НЕПРЕРЫВНУЮ
   репликацию между кластерами с replication.toml и чекпойнтами; симметричной
   команды импорта для разового дампа нет. Нам нужна пара dump/restore в духе
   pg_dump.
 - инструмент не зависит от того, какое хранилище за эндпоинтом (generic S3,
   aioboto3): переживёт замену SeaweedFS обратно на MinIO или на настоящий S3
   без правки.
 - запуск внутри контейнера backend: там уже есть aioboto3 и креды, а отдельного
   mc/rclone на машине преподавателя в поставке нет.

Дамп раскладывается файлами по дереву бакетов + manifest.json, а не tar: дамп
обозрим (можно открыть один эталон), восстанавливается частично, а контрольная
сумма каждого объекта сверяется.

`verify` намеренно НЕ ходит в хранилище: вопрос «цел ли дамп на диске» должен
получать ответ и при лежащем storage - иначе проверка бэкапа превращается в
ещё одну зависимость от того, что она страхует.
"""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import aioboto3

from app.core.config import get_settings


def _read_manifest(from_dir: Path) -> dict:
    manifest_path = from_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"manifest.json not found in {from_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "buckets" not in manifest:
        raise SystemExit(f"manifest.json in {from_dir} has no buckets - corrupt")
    return manifest


def _client_cm(settings):
    session = aioboto3.Session()
    return session.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )


async def dump(out_dir: Path) -> int:
    settings = get_settings()
    manifest: dict = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": settings.s3_endpoint,
        "buckets": {},
    }

    async with _client_cm(settings) as client:
        for bucket in (settings.s3_bucket_biometrics, settings.s3_bucket_frames):
            bucket_dir = out_dir / bucket
            bucket_dir.mkdir(parents=True, exist_ok=True)
            entries = []

            paginator = client.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=bucket):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    target = bucket_dir / key.replace("/", "__")
                    resp = await client.get_object(Bucket=bucket, Key=key)
                    async with resp["Body"] as stream:
                        data = await stream.read()
                    target.write_bytes(data)

                    entries.append(
                        {
                            "key": key,
                            "file": target.name,
                            "size": len(data),
                            # sha256 считаем сами: ETag у S3-совместимых
                            # шлюзов не всегда равен sha256 (multipart), и
                            # полагаться на него в контрольной сумме нельзя.
                            "sha256": hashlib.sha256(data).hexdigest(),
                            # ContentType сохраняем: без него restore вернул бы
                            # PNG эталон как image/jpeg (браузер и CV-клиент
                            # смотрят на него).
                            "content_type": resp.get("ContentType", "application/octet-stream"),
                        }
                    )
            manifest["buckets"][bucket] = entries
            print(f"dumped {len(entries)} objects from {bucket}")

    manifest["total_objects"] = sum(len(v) for v in manifest["buckets"].values())
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"manifest: {manifest['total_objects']} objects -> {out_dir}")
    return manifest["total_objects"]


def verify(from_dir: Path) -> int:
    """Локальная проверка дампа: файлы на месте и хэши совпадают.

    Хранилище не трогаем совсем - см. модульный докстринг.
    """
    manifest = _read_manifest(from_dir)
    checked = 0
    bad: list[str] = []

    for bucket, entries in manifest["buckets"].items():
        for entry in entries:
            src = from_dir / bucket / entry["file"]
            if not src.exists():
                bad.append(f"missing: {src}")
                continue
            h = hashlib.sha256()
            with src.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            digest = h.hexdigest()
            if digest != entry["sha256"]:
                bad.append(
                    f"checksum mismatch: {entry['key']} "
                    f"({digest[:12]} != {entry['sha256'][:12]})"
                )
            checked += 1

    if bad:
        for line in bad:
            print("BAD", line, file=sys.stderr)
        raise SystemExit(f"dump is not intact: {len(bad)} problem(s) of {checked} checked")

    print(f"verified {checked} objects from {from_dir}")
    return checked


async def restore(from_dir: Path) -> int:
    settings = get_settings()
    manifest = _read_manifest(from_dir)

    restored = 0
    async with _client_cm(settings) as client:
        for bucket, entries in manifest["buckets"].items():
            # Бакет должен существовать: при чистом volume его создаёт
            # ensure_buckets() при старте backend, но дамп мог сниматься до
            # первого запуска приложения, а restore - идти на пустое хранилище.
            try:
                await client.head_bucket(Bucket=bucket)
            except Exception:  # noqa: BLE001
                await client.create_bucket(Bucket=bucket)
            try:
                await client.put_bucket_versioning(
                    Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
                )
            except Exception as exc:  # noqa: BLE001 - версии не критичны для дампа
                print(f"warning: versioning for {bucket}: {exc}")

            for entry in entries:
                src = from_dir / bucket / entry["file"]
                if not src.exists():
                    raise SystemExit(f"dump file missing: {src}")
                # Один проход: читаем байты и по ним же сверяем хэш - раньше
                # файл читался дважды (хэш отдельно, потом снова для put).
                data = src.read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                if digest != entry["sha256"]:
                    raise SystemExit(
                        f"checksum mismatch for {entry['key']}: dump is corrupt "
                        f"({digest[:12]} != {entry['sha256'][:12]}). "
                        "Run 'verify' before restoring."
                    )
                await client.put_object(
                    Bucket=bucket,
                    Key=entry["key"],
                    Body=data,
                    ContentType=entry.get("content_type", "application/octet-stream"),
                )
                restored += 1
            print(f"restored {len(entries)} objects -> {bucket}")

    print(f"done: {restored} objects")
    return restored


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="S3 dump / restore / verify")
    parser.add_argument("action", choices=["dump", "restore", "verify"])
    parser.add_argument("--dir", required=True, help="каталог дампа")
    args = parser.parse_args(argv)

    target = Path(args.dir)
    if args.action == "dump":
        target.mkdir(parents=True, exist_ok=True)
        asyncio.run(dump(target))
    elif args.action == "verify":
        verify(target)
    else:
        asyncio.run(restore(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
