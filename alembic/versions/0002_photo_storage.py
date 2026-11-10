"""Photo storage: content_hash и жёсткий формат ключа объекта.

Revision ID: 0002_photo_storage
Revises: 0001_init
Create Date: 2026-11-10

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_photo_storage"
down_revision: Union[str, None] = "0001_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Формат ключа объекта. Совпадает с PHOTO_KEY_REGEX в db/models.py -
# синхронизация обязательна (модель, миграция, README).
PHOTO_KEY_REGEX = (
    r"^biometrics/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}"
    r"-[0-9a-f]{4}-[0-9a-f]{12}\.jpg$"
)


def upgrade() -> None:
    op.add_column(
        "student_photos",
        sa.Column("content_hash", sa.CHAR(length=64), nullable=True),
    )
    op.create_index(
        "ix_student_photos_content_hash",
        "student_photos",
        ["content_hash"],
        unique=False,
    )

    # Существующие ключи (демо-строки среза БД вида biometrics/demo-0001.jpg)
    # не проходят новый формат. Без this UPDATE CHECK не пройдёт валидацию
    # при добавлении. Ключ меняется на uuid4 - старый объект в бакете при этом
    # не переименовывается: на момент миграции реальных файлов в MinIO ещё нет.
    bind = op.get_bind()
    existing = bind.execute(
        sa.text("select id, photo_url from student_photos where photo_url !~ :regex"),
        {"regex": PHOTO_KEY_REGEX},
    ).fetchall()
    for row in existing:
        new_key = f"biometrics/{uuid.uuid4()}.jpg"
        bind.execute(
            sa.text("update student_photos set photo_url = :url where id = :id"),
            {"url": new_key, "id": row[0]},
        )

    # Проверяем, что переименование закрыло все строки: если в базе остался
    # ключ неизвестной формы, CHECK надо добавлять отдельной миграцией,
    # а не молча ронять upgrade.
    remaining = bind.execute(
        sa.text("select count(*) from student_photos where photo_url !~ :regex"),
        {"regex": PHOTO_KEY_REGEX},
    ).scalar()
    if remaining:
        raise RuntimeError(
            f"{remaining} rows in student_photos still violate the key format"
        )

    op.create_check_constraint(
        "photo_key_format",
        "student_photos",
        f"photo_url ~ '{PHOTO_KEY_REGEX}'",
    )


def downgrade() -> None:
    # Имя передаём БЕЗ префикса ck_: naming_convention оборачивает и
    # drop_constraint - иначе получается ck_student_photos_ck_student_photos_...
    op.drop_constraint("photo_key_format", "student_photos", type_="check")
    op.drop_index("ix_student_photos_content_hash", table_name="student_photos")
    op.drop_column("student_photos", "content_hash")
