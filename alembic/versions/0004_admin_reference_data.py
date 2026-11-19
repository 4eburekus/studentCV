"""Справочники для админки: уникальность дисциплин и аудитория пары.

Revision ID: 0004_admin_reference_data
Revises: 0003_absent_record
Create Date: 2026-11-16

Два изменения, оба нужны, чтобы админ-панель могла управлять справочниками, а
не только читать их.

1. disciplines: UNIQUE (name, teacher_id). До этого у названия не было никакой
   защиты, и «различимость дисциплин» (требование №3) держалась только на
   аккуратности того, кто заводит данные.
2. lessons.room_number: фронт админки рисует поле «Аудитория» с первого дня,
   а в схеме такой колонки нет - UI честно просит данные, которых у нас нет.
   Колонка nullable: на расчёт посещаемости аудитория не влияет, и старые пары
   её не имеют.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_admin_reference_data"
down_revision: Union[str, None] = "0003_absent_record"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Дубликаты сливаются в одну запись, а не удаляются: у дубля могут быть свои
# пары, а у пар - журнал. Выживает дисциплина с бо́льшим числом записей
# журнала, так история остаётся целой; при равенстве берётся минимальный id,
# чтобы результат не зависел от порядка обхода.
DUPLICATE_GROUPS = """
select name, teacher_id,
       (array_agg(id order by recs desc, id))[1] as keep_id,
       count(*) - 1 as duplicates
from (
    select d.id, d.name, d.teacher_id,
           (select count(*)
            from attendance_records a
            join lessons l on l.id = a.lesson_id
            where l.discipline_id = d.id) as recs
    from disciplines d
) x
group by name, teacher_id
having count(*) > 1
"""

# Пары переезжают в выжившую дисциплину. Делать это вслепую нельзя: если у
# дубля есть пара в том же слоте и той же группе, что у выжившей, переезд
# нарушит UNIQUE пары (0003). Такие случаи - единственное, на что миграции
# разумно отвечать отказом.
SLOT_COLLISIONS = """
select count(*)
from lessons l1
join lessons l2
  on l2.discipline_id = :keep
 and l2.group_number = l1.group_number
 and l2.lesson_date = l1.lesson_date
 and l2.start_time = l1.start_time
where l1.discipline_id = :old
"""

OLD_DISCIPLINES = """
select id from disciplines
where name = :name and teacher_id = :teacher and id <> :keep
order by id
"""


def upgrade() -> None:
    bind = op.get_bind()

    for group in bind.execute(sa.text(DUPLICATE_GROUPS)).mappings().all():
        keep_id = group["keep_id"]

        for old_id in bind.execute(
            sa.text(OLD_DISCIPLINES),
            {
                "name": group["name"],
                "teacher": group["teacher_id"],
                "keep": keep_id,
            },
        ).scalars().all():
            clash = bind.execute(
                sa.text(SLOT_COLLISIONS), {"keep": keep_id, "old": old_id}
            ).scalar()
            if clash:
                raise RuntimeError(
                    f"disciplines {old_id} and {keep_id} ({group['name']!r}) "
                    f"share {clash} identical lesson slot(s) for the same "
                    "group: merging them would violate the unique lesson key. "
                    "Move or delete those lessons before migrating."
                )

            bind.execute(
                sa.text(
                    "update lessons set discipline_id = :keep "
                    "where discipline_id = :old"
                ),
                {"keep": keep_id, "old": old_id},
            )
            bind.execute(sa.text("delete from disciplines where id = :old"), {"old": old_id})

        print(
            f"merged {group['duplicates']} duplicate discipline(s) "
            f"{group['name']!r} into id={keep_id}"
        )

    op.create_unique_constraint(
        "uq_disciplines_name_teacher_id", "disciplines", ["name", "teacher_id"]
    )

    op.add_column(
        "lessons",
        sa.Column("room_number", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("lessons", "room_number")
    op.drop_constraint(
        "uq_disciplines_name_teacher_id", "disciplines", type_="unique"
    )
    # Слитые дисциплины не восстанавливаются: дедупликация односторонняя,
    # обратного пути у неё по определению нет.
