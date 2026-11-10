"""Модели StudentCV.

Схема - 1:1 с README.md, раздел «Схема БД». Дополнения относительно README
зафиксированы в «План. База данных и ORM.md» §3 и обоснованы там.
"""

from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.enums import AttendanceStatus

# Формат номера группы: 99-АААаа-99 (например, 01-ФИИтт-01).
# Зафиксирован по решению от 08.11.2026: 3-4 заглавных, 0-3 строчных,
# номер курса двумя цифрами. Реальные номера групп КГУ встречаются
# и как ФИИтт (3+2), и как ТИПП (4+0), поэтому длины заданы диапазоном.
GROUP_NUMBER_REGEX = r"^\d{2}-[А-ЯЁ]{3,4}[а-яё]{0,3}-\d{2}$"

# Формат ключа объекта эталонного фото в бакете biometrics:
# biometrics/<uuid4>.jpg. Жёсткий формат нужен, чтобы CV-модуль и API
# не разошлись в допущениях об именах файлов: ключ проверяется CHECK'ом.
# Совпадает с str(uuid.uuid4()) + ".jpg" (нижний регистр, дефисы).
PHOTO_KEY_REGEX = (
    r"^biometrics/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}"
    r"-[0-9a-f]{4}-[0-9a-f]{12}\.jpg$"
)

# Ключ доказательного кадра задаёт НЕ модель, а app/services/storage.py:
# new_frame_key() - единственная точка генерации, FRAME_KEY_RE - валидатор на
# входе. В БД ключ кадра не хранится и CHECK на него невозможен, поэтому
# дублировать схему здесь смысла нет: два описания одного контракта
# неизбежно разъезжаются (правило, которое мы уже проходили на regex номера
# группы).


class TimestampMixin:
    """created_at с server_default - чтобы заполняла сама БД."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Teacher(Base, TimestampMixin):
    """Преподаватель - владелец журналов дисциплин.

    Закрывает требование ограничения доступа: вход только у авторизованного
    преподавателя.
    """

    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    login: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    disciplines: Mapped[list["Discipline"]] = relationship(
        back_populates="teacher",
        lazy="selectin",
    )


class Student(Base, TimestampMixin):
    """Студент - базовые данные для фильтрации по группам."""

    __tablename__ = "students"
    __table_args__ = (
        CheckConstraint(
            f"group_number ~ '{GROUP_NUMBER_REGEX}'",
            name="group_number_format",
        ),
        Index("ix_students_group_number", "group_number"),
        Index(
            "ix_students_is_active",
            "is_active",
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    group_number: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="true",
        default=True,
    )

    photos: Mapped[list["StudentPhoto"]] = relationship(
        back_populates="student",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    attendance_records: Mapped[list["AttendanceRecord"]] = relationship(
        back_populates="student",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class StudentPhoto(Base, TimestampMixin):
    """Эталонное фото студента для распознавания.

    Хранится не картинка, а ключ объекта в бакете MinIO
    (biometrics/<uuid4>.jpg), формат проверяется CHECK'ом.
    Правило "от 1 до 5 фото" проверяется в сервисном слое (app/services/photos.py):
    ограничение на количество строк через CHECK не выражается.
    """

    __tablename__ = "student_photos"
    __table_args__ = (
        UniqueConstraint("photo_url", name="uq_student_photos_photo_url"),
        CheckConstraint(
            f"photo_url ~ '{PHOTO_KEY_REGEX}'",
            name="photo_key_format",
        ),
        # Поиск дубликатов эталонов (одно лицо на нескольких фото) и
        # сверка «БД <-> бакет» идут по этому индексу.
        Index("ix_student_photos_content_hash", "content_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )
    photo_url: Mapped[str] = mapped_column(String(512), nullable=False)
    # SHA-256 содержимого объекта (hex, нижний регистр, 64 символа).
    # Нужен, чтобы сверять «строка есть - объект на месте» без скачивания
    # файлов. Nullable: демо-строки среза БД хэша не имеют.
    content_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)

    student: Mapped["Student"] = relationship(back_populates="photos")


class Discipline(Base, TimestampMixin):
    """Дисциплина. Схема журнала: один журнал - одна дисциплина."""

    __tablename__ = "disciplines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    teacher_id: Mapped[int] = mapped_column(
        # RESTRICT: журнал не должен исчезнуть вместе с преподавателем.
        ForeignKey("teachers.id", ondelete="RESTRICT"),
        nullable=False,
    )

    teacher: Mapped["Teacher"] = relationship(back_populates="disciplines")
    lessons: Mapped[list["Lesson"]] = relationship(
        back_populates="discipline",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Lesson(Base, TimestampMixin):
    """Пара: база для расчета опозданий."""

    __tablename__ = "lessons"
    __table_args__ = (
        CheckConstraint("end_time > start_time", name="end_after_start"),
        UniqueConstraint(
            "discipline_id",
            "lesson_date",
            "start_time",
            name="uq_lessons_discipline_date_start",
        ),
        Index("ix_lessons_discipline_date", "discipline_id", "lesson_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discipline_id: Mapped[int] = mapped_column(
        ForeignKey("disciplines.id", ondelete="CASCADE"),
        nullable=False,
    )
    lesson_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    discipline: Mapped["Discipline"] = relationship(back_populates="lessons")
    attendance_records: Mapped[list["AttendanceRecord"]] = relationship(
        back_populates="lesson",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class AttendanceRecord(Base, TimestampMixin):
    """Запись журнала посещаемости.

    UNIQUE (student_id, lesson_id) - ключевое дополнение к схеме README:
    повторная доставка события от камеры или из очереди не должна создавать
    дубль, а должна обновлять существующую запись.
    """

    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "lesson_id",
            name="uq_attendance_records_student_lesson",
        ),
        CheckConstraint(
            "(status = 'LATE') = (delay_minutes IS NOT NULL)",
            name="late_iff_delay_present",
        ),
        CheckConstraint("delay_minutes >= 0", name="delay_non_negative"),
        Index("ix_attendance_records_lesson_id", "lesson_id"),
        Index("ix_attendance_records_student_id", "student_id"),
        Index("ix_attendance_records_entry_time", "entry_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )
    lesson_id: Mapped[int] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
    )
    entry_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    status: Mapped[AttendanceStatus] = mapped_column(
        SAEnum(
            AttendanceStatus,
            name="attendance_status",
            native_enum=True,
            values_callable=lambda enum_cls: [m.name for m in enum_cls],
        ),
        nullable=False,
    )
    delay_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_manually_edited: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
        default=False,
    )
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    student: Mapped["Student"] = relationship(back_populates="attendance_records")
    lesson: Mapped["Lesson"] = relationship(back_populates="attendance_records")
