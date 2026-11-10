# studentCV

# Стек
Frontend: Vite + React (+ Tailwind CSS, MUI или другие для быстрого создания таблиц).
Backend: Python 3.10+ + FastAPI.
Computer Vision / AI: OpenCV (захват RTSP-потока) + PyTorch/InsightFace для распознавания лиц (распознавание с GPU CUDA).
Database и ORM: PostgreSQL + SQLAlchemy + Alembic.
Storage (картинки): SeaweedFS (S3-совместимое хранилище, смонтировано в Docker).
Background Tasks: Redis + Celery.
Интеграции: requests / httpx.
Деплой: Docker + Docker Compose.

## Стек с описанием:
- Frontend (Vite + React + Tailwind CSS/MUI): Обеспечит быструю разработку и высокую производительность пользовательского интерфейса для удобной работы преподавателей с динамическими таблицами, дашбордами и отчетами посещаемости.
- Backend (Python 3.10+ + FastAPI): Выбран за встроенную асинхронность и высокую скорость работы, что критически необходимо для стабильной обработки параллельных запросов от интерфейса, камер и фоновых задач.
- Computer Vision / AI (OpenCV + PyTorch/InsightFace): Является ядром системы для захвата видеопотока в реальном времени (OpenCV) и обеспечения требуемой точности распознавания лиц не ниже 95% за счет аппаратного ускорения на видеокартах (InsightFace + CUDA (NVIDIA)).
- Database и ORM (PostgreSQL + SQLAlchemy + Alembic): Надежная реляционная база данных в связке с современными инструментами управления структурой (ORM/миграции) гарантирует безопасное хранение расписания, отчетов и связей с биометрическими профилями студентов.
- Storage (SeaweedFS): Локальное S3-совместимое хранилище позволяет безопасно и эффективно хранить эталонные фотографии (биометрию) и доказательные кадры изолированно от базы данных, предотвращая ее раздувание и падение производительности. Приложение говорит с ним по generic S3 API (aioboto3), поэтому замена продукта за эндпоинтом кода приложения не касается. MinIO был заменён: официальные образы недоступны для загрузки из нашей среды.
- Background Tasks (Redis + Celery): Связка необходима для обработки ресурсоемких задач в фоновом режиме, что исключает зависание интерфейса и гарантирует передачу отметок в электронный журнал КГУ без потерь даже при временных сбоях сети.
- Интеграции (requests / httpx): Эти HTTP-клиенты обеспечат надежную маршрутизацию и отправку данных из нашей системы напрямую во внешнее API существующего электронного журнала университета.
- Деплой (Docker + Docker Compose): Контейнеризация гарантирует быстрое, изолированное и безошибочное развертывание всей сложной архитектуры проекта (включая специфические зависимости нейросетей) на серверах КГУ.

# Схема БД
Исходная задача: Выделение категорий данных и построение реляционной схемы будущей базы данных. База должна учитывать хранение отчетов о посещаемости с привязкой к конкретной паре, предмету, расписанию, а также управлять биометрическими данными (добавление/удаление лиц студентов).

Описание таблиц + ERD в соответствии с требованиями и user story:
1. teachers. Закрывает требование — ограничение доступа — доступ только у авторизованного преподавателя.
id (Integer, Primary Key)
full_name (String) — ФИО преподавателя.
login (String, Unique) — Логин для входа в десктопное/веб приложение.
password_hash (String) — Хэш пароля (безопасность).

2. students. Закрывает историю — управление базовыми данными.
id (Integer, Primary Key)
full_name (String, Not Null) — ФИО.
group_number (String, Not Null) — Номер группы для фильтрации. (regex для группы '^\d{2}-[А-ЯЁ]{3,4}[а-яё]{0,3}-\d{2}$')
is_active (Boolean, Default True) — Мягкое удаление (soft delete), если студент отчислен, чтобы не ломать старые журналы.

3. student_photos (биометрия). Закрывает требования — хранение от 1 до 5 фото для устойчивости распознавания к очкам/прическам.
id (Integer, Primary Key)
student_id (Integer, Foreign Key) — Связь со студентом.
photo_url (String, Not Null) — Здесь хранится не сама картинка, а ключ объекта в S3-хранилище: biometrics/<uuid4>.jpg (формат закреплен CHECK'ом ck_student_photos_photo_key_format).
created_at (DateTime) — Дата загрузки (полезно для обновления базы лиц).

4. disciplines. Закрывает требование — ведение журнала по схеме «Один журнал - одна дисциплина».
id (Integer, Primary Key)
name (String) — Название дисциплины.
teacher_id (Integer, Foreign Key) — Привязка дисциплины к преподавателю.

5. lessons. Закрывает историю — база для расчета опозданий.
id (Integer, Primary Key)
discipline_id (Integer, Foreign Key) — К какой дисциплине относится пара.
lesson_date (Date) — Дата пары.
start_time (Time) — Время начала (с ним AI-модуль будет сравнивать время входа студента).
end_time (Time) — Время окончания.

6. attendance_records (журнал посещаемости). Закрывает истории — фиксация точного времени захода студента в аудиторию; автоматическая фиксация статуса; возможность ручного редактирования записей журнала.
id (Integer, Primary Key)
student_id (Integer, Foreign Key) — Кто пришел.
lesson_id (Integer, Foreign Key) — На какую пару пришел.
entry_time (DateTime) — Точный штамп времени захода в аудиторию.
status (Enum: PRESENT, LATE, ABSENT) — Статус. Вычисляется автоматически при записи.
delay_minutes (Integer, Nullable) — Время задержки в минутах (если статус LATE).
is_manually_edited (Boolean, Default False) — Индикатор «Отредактировано вручную».
edited_at (DateTime, Nullable) — Когда преподаватель внес изменения (опционально, для логов).

# Шаблонное рассписание времени пар
1 пара 8:30-10:00
2 пара 10:10-11:40
3 пара 11:50-13:20
4 пара 14:00-15:30
5 пара 15:40-17:10
6 пара 17:20-18:50
7 пара 19:00-20:30

# Как поднять окружение
Docker: БД, S3-хранилище и backend живут в контейнерах, распознавание лиц - нативным процессом Windows (GPU и камера).

## Первый запуск
```
cp .env.example .env
docker compose up -d
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend python -m db.seeds
docker compose run --rm backend uvicorn app.main:app --host 0.0.0.0 --port 8000
```
- API: http://127.0.0.1:8000 (Swagger: http://127.0.0.1:8000/docs)
- PostgreSQL: 127.0.0.1:5433
- pgAdmin 4: http://127.0.0.1:5050 (логин/пароль - в .env)
- S3-хранилище (SeaweedFS): http://127.0.0.1:8333 - internal-порты наружу не публикуются

Бакеты biometrics и frames создаёт само приложение при старте (app.services.storage.ensure_buckets) и включает в них версионирование - отдельного шага провижининга нет.

## Команды
```
docker compose ps                                              # состояние сервисов
docker compose logs -f db                                      # логи БД
docker compose logs -f storage                                 # логи хранилища
docker compose run --rm backend alembic current
docker compose run --rm backend python -m db.seeds
docker compose exec backend python -m pytest tests -q          # тесты (в контейнере)
docker compose exec db psql -U studentcv -d studentcv
docker compose down                                            # остановить (данные сохранятся)
docker compose down -v                                         # ВНИМАНИЕ: удалить volume с БД И с хранилищем
```

# Правила посещаемости
Как событие распознавания превращается в статус (договорённость 10.11.2026). Границы считаются от даты и времени пары (lessons.lesson_date + start_time/end_time):

| Время прохода | Результат |
| --- | --- |
| раньше начала пары | PRESENT, delay_minutes = NULL |
| ровно в начало пары | LATE, delay_minutes = 0 |
| позже начала, но раньше конца | LATE, delay_minutes = округление вверх |
| не раньше конца пары | событие НЕ записывается, студент остаётся ABSENT |

- При повторной доставке по одной паре побеждает самое РАННЕЕ время входа: более позднее событие не перебивает записанное (UNIQUE student_id + lesson_id, дублей нет).
- Запись с is_manually_edited = TRUE автоматическим событием не меняется: правка преподавателя важнее кадра.
- Отсутствие строки = ABSENT. Отдельного статуса "пришёл после конца пары" нет, и по данным журнала эти два случая неразличимы (вопрос заказчику, см. «План. База данных и ORM.md» §9).

# Бэкап
Данных ДВА: строки в PostgreSQL и объекты в S3-хранилище. Ключи фото хранит база, поэтому резервные копии снимаются и восстанавливаются только парой.
```
powershell -ExecutionPolicy Bypass -File scripts\backup.ps1           # база -> ./backups/*.dump
powershell -ExecutionPolicy Bypass -File scripts\backup_storage.ps1   # объекты -> ./backups/storage-<stamp>/
powershell -ExecutionPolicy Bypass -File scripts\restore.ps1          # восстановить базу
powershell -ExecutionPolicy Bypass -File scripts\restore_storage.ps1  # восстановить объекты
powershell -ExecutionPolicy Bypass -File scripts\restore_storage.ps1 -VerifyOnly  # проверить дампа на целостность, не трогая хранилище
```
pgdata - volume, данные не переносятся копированием папки: только дампом. Восстановление хранилища раскладывает объекты файлами по бакетам и сверяет sha256 каждого.