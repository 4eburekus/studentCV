"""ABSENT как запись: время входа становится nullable, пара получает группу.

Revision ID: 0003_absent_record
Revises: 0002_photo_storage
Create Date: 2026-11-15

Открытый вопрос плана 3.2.2 (п. 9.5) решён так: отсутствие студента - это
строка со status='ABSENT' и entry_time IS NULL, а не отсутствие строки.
Причина не вкусовая: без записи журнал не может показать состав группы
(«кто должен был быть»), а ручное заполнение (задача 3.3.1) не имеет объекта -
нечем править то, чего в таблице нет.

Заодно пара привязывается к группе (lessons.group_number): это и есть тот
состав, которого в схеме раньше не было.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_absent_record"
down_revision: Union[str, None] = "0002_photo_storage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Формат номера группы. Совпадает с GROUP_NUMBER_REGEX в db/models.py -
# синхронизация обязательна (модель, миграция, README).
GROUP_NUMBER_REGEX = r"^\d{2}-[А-ЯЁ]{3,4}[а-яё]{0,3}-\d{2}$"

# Формат ключа кадра. Совпадает с FRAME_KEY_REGEX в db/models.py - то же
# соглашение, что и с regex группы выше. В миграции локальная копия неизбежна:
# импорт приложения связал бы историю схемы с кодом, который меняется быстрее.
FRAME_KEY_REGEX = (
    r"^frames/[0-9]+/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}"
    r"-[0-9a-f]{4}-[0-9a-f]{12}\.jpg$"
)

# Пара без группы невозможна, но в базе уже могут лежать пары, заведенные до
# этого среза. Какую группу им приписать, из данных не вывести, поэтому
# backfill берёт первую группу из students; если студентов нет - падает,
# вместо того чтобы молча оставить NULL и не пройти NOT NULL.
DEFAULT_GROUP_SELECT = "select group_number from students order by id limit 1"


def upgrade() -> None:
    bind = op.get_bind()

    # --- attendance_records: entry_time становится nullable ------------------
    # Порядок важен: старый CHECK absent_iff_no_entry_time добавляется ПОСЛЕ
    # того, как колонка разрешает NULL, и ПОСЛЕ drop прежних правил.
    op.alter_column(
        "attendance_records",
        "entry_time",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )

    op.create_check_constraint(
        "absent_iff_no_entry_time",
        "attendance_records",
        "(status = 'ABSENT') = (entry_time IS NULL)",
    )

    # --- attendance_records: адрес доказательного снимка -------------------
    # Ключ кадра раньше только проверялся на существование и выбрасывался:
    # через месяц нельзя было подтвердить ни одну отметку, а для ручной
    # правки (задача 3.3.1) след нужен. Старые строки остаются с NULL -
    # CHECK допускает пустое значение, backfill не требуется.
    op.add_column(
        "attendance_records",
        sa.Column("frame_object_key", sa.String(length=512), nullable=True),
    )

    op.create_check_constraint(
        "frame_key_format",
        "attendance_records",
        f"frame_object_key IS NULL OR frame_object_key ~ '{FRAME_KEY_REGEX}'",
    )
    op.create_check_constraint(
        "frame_key_requires_entry",
        "attendance_records",
        "entry_time IS NOT NULL OR frame_object_key IS NULL",
    )

    # --- lessons: момент закрытия пары ----------------------------------------
    # Нужен фронту: кнопка «завершить пару» должна отличать «ещё не закрыта»
    # от «уже закрыта», не догадываясь об этом по наличию строк ABSENT (пара,
    # на которой все пришли, закрыта, но отсутствий в ней нет).
    op.add_column(
        "lessons",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- lessons: группа, для которой пара -----------------------------------
    op.add_column(
        "lessons",
        sa.Column("group_number", sa.String(length=20), nullable=True),
    )

    existing = bind.execute(
        sa.text("select count(*) from lessons where group_number is null")
    ).scalar()
    if existing:
        default_group = bind.execute(sa.text(DEFAULT_GROUP_SELECT)).scalar()
        if default_group is None:
            raise RuntimeError(
                f"{existing} rows in lessons need a group_number, but students "
                "table is empty: there is no group to backfill them with"
            )
        bind.execute(
            sa.text(
                "update lessons set group_number = :group "
                "where group_number is null"
            ),
            {"group": default_group},
        )

    op.alter_column(
        "lessons",
        "group_number",
        existing_type=sa.String(length=20),
        nullable=False,
    )

    # Имя без префикса ck_: naming_convention добавляет его и здесь.
    op.create_check_constraint(
        "group_number_format",
        "lessons",
        f"group_number ~ '{GROUP_NUMBER_REGEX}'",
    )

    # Уникальный ключ пары пересобирается с группой: одна дисциплина в одно
    # время может идти у двух групп, и без группы в ключе такая пара
    # невводима. Индекс переименовываем полностью, старое имя не переиспользуем.
    op.drop_constraint(
        "uq_lessons_discipline_date_start", "lessons", type_="unique"
    )
    op.create_unique_constraint(
        "uq_lessons_discipline_group_date_start",
        "lessons",
        ["discipline_id", "group_number", "lesson_date", "start_time"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_lessons_discipline_group_date_start", "lessons", type_="unique"
    )

    # Обратный ключ соберётся только если в базе нет двух групп в одном слоте;
    # если есть - downgrade должен упасть, а не сломать данные.
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text(
            "select count(*) from ("
            "  select discipline_id, lesson_date, start_time, count(*) as c"
            "  from lessons group by 1, 2, 3 having count(*) > 1"
            ") d"
        )
    ).scalar()
    if duplicates:
        raise RuntimeError(
            f"{duplicates} lesson slots are used by more than one group: "
            "the old unique constraint cannot be restored"
        )

    op.create_unique_constraint(
        "uq_lessons_discipline_date_start",
        "lessons",
        ["discipline_id", "lesson_date", "start_time"],
    )

    op.drop_constraint("group_number_format", "lessons", type_="check")
    op.drop_column("lessons", "closed_at")
    op.drop_column("lessons", "group_number")

    op.drop_constraint("frame_key_requires_entry", "attendance_records", type_="check")
    op.drop_constraint("frame_key_format", "attendance_records", type_="check")
    op.drop_column("attendance_records", "frame_object_key")

    op.drop_constraint(
        "absent_iff_no_entry_time", "attendance_records", type_="check"
    )

    # Записи ABSENT при откате девать некуда: колонка снова NOT NULL.
    # Удаляем их - это ровно те строки, которые до этого среза не существовали.
    bind.execute(
        sa.text("delete from attendance_records where status = 'ABSENT'")
    )
    op.alter_column(
        "attendance_records",
        "entry_time",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
