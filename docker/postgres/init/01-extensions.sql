-- Расширения PostgreSQL для проекта.
-- Выполняется один раз при первом создании volume pgdata.
-- Файл без shebang, чтобы docker-entrypoint исполнил его через psql, а не как shell-скрипт.

-- pgcrypto: gen_random_uuid() для генерации имён файлов биометрии в MinIO
CREATE EXTENSION IF NOT EXISTS pgcrypto;
