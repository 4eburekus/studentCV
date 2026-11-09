"""Начальная схема StudentCV: 6 таблиц, нативный enum, CHECK-констрейнты.

Revision ID: 0001_init
Revises:
Create Date: 2026-11-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_init"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Нативный PG-enum: create_type=True просит SQLAlchemy создать тип
    # перед таблицей (хук before_create). Вручную тип не создаём -
    # иначе он создаётся дважды и PG падает с DuplicateObjectError.
    attendance_status = sa.Enum(
        "PRESENT",
        "LATE",
        "ABSENT",
        name="attendance_status",
        create_type=True,
    )

    op.create_table(
        "teachers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("login", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_teachers"),
        sa.UniqueConstraint("login", name="uq_teachers_login"),
    )

    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("group_number", sa.String(length=20), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_students"),
        sa.CheckConstraint(
            "group_number ~ '^\\d{2}-[А-ЯЁ]{3,4}[а-яё]{0,3}-\\d{2}$'",
            name="group_number_format",
        ),
    )
    op.create_index(
        "ix_students_group_number",
        "students",
        ["group_number"],
        unique=False,
    )
    op.create_index(
        "ix_students_is_active",
        "students",
        ["is_active"],
        unique=False,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "student_photos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("photo_url", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name="fk_student_photos_student_id_students",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_student_photos"),
        sa.UniqueConstraint("photo_url", name="uq_student_photos_photo_url"),
    )

    op.create_table(
        "disciplines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["teacher_id"],
            ["teachers.id"],
            name="fk_disciplines_teacher_id_teachers",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_disciplines"),
    )

    op.create_table(
        "lessons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("discipline_id", sa.Integer(), nullable=False),
        sa.Column("lesson_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "end_time > start_time",
            name="end_after_start",
        ),
        sa.ForeignKeyConstraint(
            ["discipline_id"],
            ["disciplines.id"],
            name="fk_lessons_discipline_id_disciplines",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_lessons"),
        sa.UniqueConstraint(
            "discipline_id",
            "lesson_date",
            "start_time",
            name="uq_lessons_discipline_date_start",
        ),
    )
    op.create_index(
        "ix_lessons_discipline_date",
        "lessons",
        ["discipline_id", "lesson_date"],
        unique=False,
    )

    op.create_table(
        "attendance_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("lesson_id", sa.Integer(), nullable=False),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", attendance_status, nullable=False),
        sa.Column("delay_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "is_manually_edited",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'LATE') = (delay_minutes IS NOT NULL)",
            name="late_iff_delay_present",
        ),
        sa.CheckConstraint(
            "delay_minutes >= 0",
            name="delay_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["lessons.id"],
            name="fk_attendance_records_lesson_id_lessons",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name="fk_attendance_records_student_id_students",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_attendance_records"),
        sa.UniqueConstraint(
            "student_id",
            "lesson_id",
            name="uq_attendance_records_student_lesson",
        ),
    )
    op.create_index(
        "ix_attendance_records_lesson_id",
        "attendance_records",
        ["lesson_id"],
        unique=False,
    )
    op.create_index(
        "ix_attendance_records_student_id",
        "attendance_records",
        ["student_id"],
        unique=False,
    )
    op.create_index(
        "ix_attendance_records_entry_time",
        "attendance_records",
        ["entry_time"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_attendance_records_entry_time", table_name="attendance_records")
    op.drop_index("ix_attendance_records_student_id", table_name="attendance_records")
    op.drop_index("ix_attendance_records_lesson_id", table_name="attendance_records")
    op.drop_table("attendance_records")

    op.drop_index("ix_lessons_discipline_date", table_name="lessons")
    op.drop_table("lessons")

    op.drop_table("disciplines")

    op.drop_table("student_photos")

    op.drop_index("ix_students_is_active", table_name="students")
    op.drop_index("ix_students_group_number", table_name="students")
    op.drop_table("students")

    op.drop_table("teachers")

    # Тип удаляем в конце: он мог бы остаться, если бы на него ссылались
    # другие объекты (сейчас - нет).
    sa.Enum(name="attendance_status").drop(op.get_bind(), checkfirst=True)
