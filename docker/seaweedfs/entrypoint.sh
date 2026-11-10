#!/bin/sh
# Entrypoint для SeaweedFS (studentCV).
#
# SeaweedFS читает учётки S3 из JSON-файла (-s3.config, высший приоритет).
# Файл с секретами в git попасть не может, поэтому конфиг генерируется при
# старте из переменных окружения и кладётся в каталог данных (volume).
#
# Идемпотентность: identities описываются декларативно (один источник истины -
# .env), пересоздание файла ничего не меняет. Права на бакеты задаются
# bucket-scoped действиями (Read:frames/Write:frames/List:frames) - CV-процесс
# физически не может тронуть эталонные фото.
#
# tr -d '\r' ниже не нужен (этот файл исполняется как entrypoint с CRLF
# ломается) - .gitattributes задаёт eol=lf для *.sh.

set -eu

CONFIG_DIR="${WEED_CONFIG_DIR:-/data/seaweedfs}"
CONFIG_FILE="${CONFIG_DIR}/s3.json"

STORAGE_ADMIN_ACCESS_KEY="${STORAGE_ADMIN_ACCESS_KEY:?STORAGE_ADMIN_ACCESS_KEY is required}"
STORAGE_ADMIN_SECRET_KEY="${STORAGE_ADMIN_SECRET_KEY:?STORAGE_ADMIN_SECRET_KEY is required}"
CV_ACCESS_KEY="${CV_ACCESS_KEY:?CV_ACCESS_KEY is required}"
CV_SECRET_KEY="${CV_SECRET_KEY:?CV_SECRET_KEY is required}"

BUCKET_BIOMETRICS="${S3_BUCKET_BIOMETRICS:-biometrics}"
BUCKET_FRAMES="${S3_BUCKET_FRAMES:-frames}"

mkdir -p "${CONFIG_DIR}"

# Только actions:frames: писать и читать кадры, без права создавать бакеты и
# без доступа к biometrics. Удаление входит в Write (проверено живым прогоном).
cat > "${CONFIG_FILE}" <<EOF
{
  "identities": [
    {
      "name": "backend",
      "credentials": [
        {"accessKey": "${STORAGE_ADMIN_ACCESS_KEY}", "secretKey": "${STORAGE_ADMIN_SECRET_KEY}"}
      ],
      "actions": ["Admin", "Read", "Write", "List", "Tagging"]
    },
    {
      "name": "cv-writer",
      "credentials": [
        {"accessKey": "${CV_ACCESS_KEY}", "secretKey": "${CV_SECRET_KEY}"}
      ],
      "actions": ["Write:${BUCKET_FRAMES}", "Read:${BUCKET_FRAMES}", "List:${BUCKET_FRAMES}"]
    }
  ]
}
EOF

chmod 600 "${CONFIG_FILE}"
echo "generated ${CONFIG_FILE} (backend + cv-writer identities)"

# weed server = master + volume + filer + s3 в одном процессе: наша топология
# - одна машина преподавателя, кластер не нужен.
#
# Флаги взяты из живых прогонов 10.11.2026: weed server -s3 -ip=127.0.0.1
# -ip.bind=0.0.0.0 -s3.port=8333 -s3.config=... поднялся и отвечал другому
# контейнеру по сети. -s3.ip.bind НЕ ставим: в --help у weed s3 такого флага
# нет (есть только -ip.bind), а -ip=127.0.0.1 нужен, чтобы master/volume/filer
# договорились между собой на localhost.
#
# -volume.max=0 - НЕ косметика, а фикс реальной поломки. Дефолт "8": SeaweedFS
# даёт каждому бакету собственный том и резервирует их сразу, поэтому 8 томов
# исчерпываются на втором же бакете, а третий пишет "No writable volumes and no
# free volumes left" -> PutObject отдаёт InternalError (наблюдали: biometrics
# писался, frames - нет). При 0 лимит считается как свободное место / размер
# тома, т.е. ограничен диском машины - ровно то поведение, которое нужно
# локальному хранилищу. volumeSizeLimitMB=64 оставляем маленьким: том - это
# единица выделения, а не весь диск; compaction/vacuum чистят удалённое.
exec weed server \
    -s3 \
    -dir=/data \
    -ip=127.0.0.1 \
    -ip.bind=0.0.0.0 \
    -volume.max=0 \
    -master.volumeSizeLimitMB=64 \
    -s3.port=8333 \
    -s3.config="${CONFIG_FILE}" \
    "$@"
