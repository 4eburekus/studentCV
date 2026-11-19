// src/features/attendance/LessonJournalPage.jsx
//
// Журнал пары на реальном API + ручное редактирование (задача 3.3.1).
//
// Что здесь важно знать, если вы читаете этот файл впервые:
//
// 1. «Отсутствовал» - настоящая запись в журнале, а не отсутствие строки.
//    Она появляется, когда пару закрыли (кнопкой или планировщиком). Строка
//    без записи означает «пара ещё не закрыта и этого студента не отметили».
//
// 2. Время везде показывается и собирается ЧЕРЕЗ UTC (см. scheduleTime.js):
//    расписание и отметки живут в одной условной зоне, и обычный
//    toLocaleTimeString перевёл бы вход 08:37 в 11:37 на машине с +03:00.
//    Тогда же форма правки отправила бы обратно сдвинутое время и каждый раз
//    портила отметку на три часа.
//
// 3. Опоздание в форму не отправляется - сервер считает его сам из времени
//    той же формулой, что и автоматика. Здесь оно только предпросмотрено, и
//    предпросмотр обязан совпадать с тем, что ляжет в журнал.

import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { DataTable } from '../../components/ui/DataTable';
import {
  closeLesson,
  getJournal,
  getLesson,
  getStudents,
  patchAttendanceRecord,
  setAttendanceRecord,
} from '../../services/api';
import {
  formatScheduleMoment,
  parseScheduleTime,
  previewDelayMinutes,
  scheduleHM,
  scheduleHMS,
} from './scheduleTime';

const FaceIdIcon = () => (
  <svg className="w-4 h-4 text-blue-600 inline-block mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 008 11a4 4 0 118 0c0 1.017-.07 2.019-.203 3m-2.118 6.844A21.88 21.88 0 0015.171 17m3.839 1.132c.645-2.266.99-4.659.99-7.132A8 8 0 008 4.07M3 15.364c.64-1.319 1-2.8 1-4.364 0-1.457.39-2.823 1.07-4"></path><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 10h.01M15 10h.01"></path></svg>
);
const ManualIcon = () => (
  <svg className="w-4 h-4 text-gray-500 inline-block mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
);

const STATUS_META = {
  PRESENT: { label: 'Присутствовал', cls: 'bg-green-100 text-green-700 border-green-200' },
  LATE: { label: 'Опоздал', cls: 'bg-yellow-100 text-yellow-700 border-yellow-200' },
  ABSENT: { label: 'Отсутствовал', cls: 'bg-red-100 text-red-700 border-red-200' },
};

const timeHM = (v) => (v ? String(v).slice(0, 5) : '');

/** Форма ручной отметки: статус + время. Права на «свою» запись у сервера
 * пока нет (авторизация - заглушка, требование №11), поэтому форма одна для
 * создания и правки: различает их только вызываемый метод. */
const EditModal = ({ lesson, row, onClose, onSaved }) => {
  const [status, setStatus] = useState(row.status ?? 'PRESENT');
  // value у <input type="time"> берём из времени РАСПИСАНИЯ, а не из
  // локального: иначе открытие формы и сохранение без единого изменения
  // сдвинули бы отметку на разницу зон.
  const [time, setTime] = useState(
    row.entry_time ? scheduleHMS(row.entry_time) : defaultTime(lesson),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const needsTime = status !== 'ABSENT';
  const entryIso = needsTime ? parseScheduleTime(lesson.lesson_date, time) : null;
  const preview = needsTime ? previewDelayMinutes(lesson.lesson_date, lesson.start_time, entryIso) : null;

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      // PATCH если запись уже есть, POST если её нет: до закрытия пары у
      // студента строки в журнале не существует, и править нечего.
      if (row.hasRecord) {
        await patchAttendanceRecord(row.record_id, { status, entry_time: entryIso });
      } else {
        await setAttendanceRecord({
          lesson_id: Number(lesson.id),
          student_id: row.student_id,
          status,
          entry_time: entryIso,
        });
      }
      await onSaved();
    } catch (err) {
      setError(typeof err.detail === 'string' ? err.detail : 'Сервер отклонил отметку');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <form onSubmit={submit} className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="bg-blue-800 text-white px-6 py-4 flex justify-between items-center">
          <h2 className="font-bold">Ручная отметка</h2>
          <button type="button" onClick={onClose} className="text-blue-200 hover:text-white">✕</button>
        </div>

        <div className="p-6 space-y-4">
          <div className="text-sm text-gray-600">
            <div className="font-semibold text-blue-900">{row.full_name}</div>
            <div className="text-xs text-gray-500">
              {lesson.lesson_date} · {timeHM(lesson.start_time)}–{timeHM(lesson.end_time)} · группа {lesson.group_number}
            </div>
          </div>

          <div>
            <label className="block text-sm font-semibold mb-1">Статус</label>
            <select value={status} onChange={(e) => setStatus(e.target.value)}
              className="w-full border rounded-lg px-3 py-2 text-sm">
              <option value="PRESENT">Присутствовал</option>
              <option value="LATE">Опоздал</option>
              <option value="ABSENT">Отсутствовал</option>
            </select>
          </div>

          {needsTime && (
            <div>
              <label className="block text-sm font-semibold mb-1">Время входа</label>
              <input type="time" step="1" required value={time}
                onChange={(e) => setTime(e.target.value)}
                className="w-full border rounded-lg px-3 py-2 text-sm" />
              <p className="text-xs text-gray-500 mt-1">
                Опоздание: <strong>{preview === null ? '—' : `${preview} мин`}</strong>
                {' '}(считает сервер, здесь только предпросмотр)
              </p>
              {/* Время после конца пары разрешено намеренно: правило «не позже
                  конца» ограничивает автоматику, а ручная отметка существует
                  именно для исключений. Предупреждение - чтобы преподаватель
                  видел, что засчитывает большое опоздание, а не ошибся в дате.
                  Сравнение строк корректно: формат HH:MM(:SS) нулезаполнен, и
                  лексикографический порядок в нём совпадает с хронологическим. */}
              {needsTime && time.slice(0, 5) > timeHM(lesson.end_time) && (
                <p className="text-xs text-amber-700 mt-1">
                  Время позже конца пары ({timeHM(lesson.end_time)}) — будет
                  засчитано опоздание {preview} мин.
                </p>
              )}
            </div>
          )}

          {!needsTime && (
            <p className="text-xs text-gray-500">
              Время входа при «Отсутствовал» не сохраняется - отметки о приходе нет.
            </p>
          )}

          {row.frame_object_key && (
            <div className="bg-amber-50 border border-amber-200 text-amber-800 text-xs px-3 py-2 rounded">
              У текущей отметки есть кадр с камеры. После ручной правки он будет
              снят: кадр был доказательством автоматического входа, который вы
              заменяете.
            </div>
          )}

          {row.hasRecord && row.is_manually_edited && (
            <p className="text-xs text-gray-500">
              Отметка уже правилась вручную ({formatScheduleMoment(row.edited_at)}) -
              камера её больше не перетирает.
            </p>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2 rounded">
              {error}
            </div>
          )}

          <div className="pt-2 flex gap-3">
            <button type="button" onClick={onClose}
              className="flex-1 py-2 border rounded-lg hover:bg-gray-50">Отмена</button>
            <button type="submit" disabled={saving || (needsTime && !time)}
              className="flex-1 py-2 bg-blue-700 text-white rounded-lg hover:bg-blue-800 disabled:opacity-50">
              {saving ? 'Сохранение…' : 'Сохранить'}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
};

/** Значение времени по умолчанию: начало пары. Не «сейчас»: правка создаётся
 * про конкретное занятие, и подставлять текущее время означало бы иногда
 * ставить отметку вне суток пары (сервер ответит 422). */
const defaultTime = (lesson) => `${timeHM(lesson.start_time)}:00`;

export const LessonJournalPage = () => {
  const { lessonId } = useParams();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lesson, setLesson] = useState(null);
  const [journal, setJournal] = useState(null);
  const [groupStudents, setGroupStudents] = useState([]);
  const [closing, setClosing] = useState(false);
  const [notice, setNotice] = useState(null);
  const [editing, setEditing] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Сначала пара: из неё берём группу, и только потом студентов группы.
      const lessonData = await getLesson(lessonId);
      const [journalData, studentsData] = await Promise.all([
        getJournal(lessonId),
        getStudents({ group: lessonData.group_number, limit: 500 }),
      ]);
      setLesson(lessonData);
      setJournal(journalData);
      setGroupStudents(studentsData.items);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [lessonId]);

  useEffect(() => { load(); }, [load]);

  // Склейка состава группы и записей журнала.
  const rows = useMemo(() => {
    const records = journal?.entries ?? [];
    const byStudent = new Map(records.map((r) => [r.student_id, r]));
    const byId = new Map(groupStudents.map((s) => [s.id, s]));

    const merged = groupStudents.map((s) => {
      const rec = byStudent.get(s.id);
      return {
        id: s.id,
        student_id: s.id,
        record_id: rec?.id ?? null,
        full_name: s.full_name,
        group_number: s.group_number,
        entry_time: rec?.entry_time ?? null,
        status: rec?.status ?? null,
        delay_minutes: rec?.delay_minutes ?? null,
        is_manually_edited: rec?.is_manually_edited ?? false,
        frame_object_key: rec?.frame_object_key ?? null,
        edited_at: rec?.edited_at ?? null,
        hasRecord: Boolean(rec),
      };
    });

    // Студенты с записью, которых нет в текущем составе группы (переведены
    // после закрытия пары). Молча выбрасывать их нельзя: это ровно те строки,
    // из-за которых отчёты не сходятся.
    for (const rec of records) {
      if (!byId.has(rec.student_id)) {
        merged.push({
          id: rec.student_id,
          student_id: rec.student_id,
          record_id: rec.id,
          full_name: rec.full_name,
          group_number: rec.group_number,
          entry_time: rec.entry_time,
          status: rec.status,
          delay_minutes: rec.delay_minutes,
          is_manually_edited: rec.is_manually_edited,
          frame_object_key: rec.frame_object_key,
          edited_at: rec.edited_at,
          hasRecord: true,
          foreign: true,
        });
      }
    }
    return merged;
  }, [journal, groupStudents]);

  const [statusFilter, setStatusFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  const filteredRows = useMemo(() => rows.filter((r) => {
    const matchStatus = statusFilter
      ? (statusFilter === 'UNMARKED' ? !r.hasRecord : r.status === statusFilter)
      : true;
    const matchSearch = r.full_name.toLowerCase().includes(searchQuery.toLowerCase());
    return matchStatus && matchSearch;
  }), [rows, statusFilter, searchQuery]);

  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 50;
  useEffect(() => { setCurrentPage(1); }, [statusFilter, searchQuery]);
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / itemsPerPage));
  const currentItems = filteredRows.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage);

  const handleClose = async () => {
    if (!window.confirm(
      'Завершить занятие досрочно?\n\n' +
      'Всем студентам группы без отметки будет проставлено «Отсутствовал». ' +
      'Отметки, пришедшие с камеры позже, исправят это автоматически.'
    )) return;
    setClosing(true);
    setNotice(null);
    try {
      const res = await closeLesson(lessonId);
      setNotice(
        res.absent_created > 0
          ? `Проставлено отсутствий: ${res.absent_created}`
          : res.was_already_closed
            ? 'Занятие уже было завершено'
            : 'Все студенты уже отмечены',
      );
      await load();
    } catch (e) {
      setError(e);
    } finally {
      setClosing(false);
    }
  };

  const columns = [
    {
      key: 'full_name', label: 'ФИО студента',
      render: (v, row) => (
        <span className={row.foreign ? 'font-semibold text-amber-800' : 'font-semibold text-blue-900'}>
          {v}
          {row.foreign && <span className="text-xs text-amber-600"> (не в группе пары)</span>}
        </span>
      ),
    },
    { key: 'group_number', label: 'Группа' },
    {
      key: 'entry_time', label: 'Время входа',
      render: (v) => (v ? scheduleHM(v) : '—'),
    },
    {
      key: 'status', label: 'Статус',
      render: (status, row) => {
        if (!row.hasRecord) {
          return (
            <span className="px-3 py-1 rounded-full text-xs font-bold border bg-gray-100 text-gray-500 border-gray-200">
              Не отмечен
            </span>
          );
        }
        const meta = STATUS_META[status];
        if (!meta) return <span className="text-gray-400">—</span>;
        return <span className={`px-3 py-1 rounded-full text-xs font-bold border ${meta.cls}`}>{meta.label}</span>;
      },
    },
    {
      key: 'delay_minutes', label: 'Опоздание',
      render: (v) => (v === null || v === undefined ? '—' : `${v} мин`),
    },
    {
      key: 'is_manually_edited', label: 'Источник', sortable: false,
      render: (manual, row) => {
        if (!row.hasRecord) return <span className="text-xs text-gray-400">—</span>;
        return (
          <span className="flex items-center text-sm text-gray-500" title={manual && row.edited_at ? `Изменено: ${formatScheduleMoment(row.edited_at)}` : undefined}>
            {manual ? <><ManualIcon /> Вручную</> : <><FaceIdIcon /> Face ID</>}
          </span>
        );
      },
    },
    {
      // sortable: false обязательно: без него DataTable сортирует по полю
      // 'edit', которого в строках нет, и порядок журнала становится
      // непредсказуемым от пустого, но кликабельного заголовка.
      key: 'edit', label: '', sortable: false,
      render: (_, row) => (
        <button
          onClick={() => setEditing(row)}
          className="px-3 py-1 rounded-lg border border-blue-200 text-blue-700 text-xs font-semibold hover:bg-blue-50"
        >
          {row.hasRecord ? 'Править' : 'Отметить'}
        </button>
      ),
    },
  ];

  if (loading) return <div className="p-8 text-gray-500">Загрузка журнала…</div>;
  if (error && !editing) {
    return (
      <div className="p-8 text-red-600">
        Ошибка {error.status}: {typeof error.detail === 'string' ? error.detail : 'не удалось загрузить журнал'}
        <button onClick={load} className="ml-4 underline">Повторить</button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-100 p-4 md:p-8 font-sans">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="bg-white p-6 rounded-xl shadow-sm border border-blue-100 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <h1 className="text-2xl font-bold text-blue-900">Журнал пары #{lessonId}</h1>
            <p className="text-sm text-gray-500 mt-1">
              {lesson?.discipline_name} · группа {lesson?.group_number} ·{' '}
              {lesson?.lesson_date} {timeHM(lesson?.start_time)}–{timeHM(lesson?.end_time)}
              {lesson?.room_number ? ` · ауд. ${lesson.room_number}` : ''}
            </p>
            <p className="text-xs mt-1">
              {journal?.closed_at
                ? <span className="text-emerald-700">Занятие закрыто: {formatScheduleMoment(journal.closed_at)}</span>
                : <span className="text-gray-500">Занятие не закрыто — отсутствия ещё не проставлены</span>}
            </p>
          </div>
          <div className="flex gap-3">
            <button
              onClick={handleClose}
              disabled={closing || Boolean(journal?.closed_at)}
              className="bg-red-600 hover:bg-red-700 text-white px-5 py-2.5 rounded-lg text-sm font-medium shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
              title={journal?.closed_at ? 'Занятие уже закрыто' : 'Проставить отсутствующим ABSENT'}
            >
              {closing ? 'Завершение…' : journal?.closed_at ? 'Завершено' : 'Завершить отметки досрочно'}
            </button>
          </div>
        </div>

        {notice && (
          <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm px-4 py-3 rounded-lg">
            {notice}
          </div>
        )}

        <div className="flex flex-col lg:flex-row gap-4 bg-white p-5 rounded-xl shadow-sm border border-blue-100">
          <div className="flex-1">
            <label className="block text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wider">Поиск по ФИО</label>
            <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} className="w-full border border-gray-300 rounded-lg px-4 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none bg-gray-50" placeholder="Введите имя..." />
          </div>
          <div className="flex-1">
            <label className="block text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wider">Статус</label>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="w-full border border-gray-300 rounded-lg px-4 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none bg-gray-50">
              <option value="">Все статусы</option>
              <option value="PRESENT">Присутствовал</option>
              <option value="LATE">Опоздал</option>
              <option value="ABSENT">Отсутствовал</option>
              <option value="UNMARKED">Не отмечен</option>
            </select>
          </div>
        </div>

        <DataTable data={currentItems} columns={columns} emptyMessage="По вашему запросу ничего не найдено" />

        <div className="flex flex-col sm:flex-row justify-between items-center text-sm text-gray-500 bg-white p-4 rounded-xl shadow-sm border border-blue-100 gap-4">
          <span>Показано <strong className="text-blue-900">{currentItems.length}</strong> из {filteredRows.length}</span>
          <div className="flex gap-2">
            <button onClick={() => setCurrentPage(p => Math.max(p - 1, 1))} disabled={currentPage === 1} className="px-4 py-2 border border-gray-300 rounded-lg bg-white hover:bg-gray-50 disabled:opacity-50 font-medium">Назад</button>
            <button onClick={() => setCurrentPage(p => Math.min(p + 1, totalPages))} disabled={currentPage === totalPages} className="px-4 py-2 border border-gray-300 rounded-lg bg-white hover:bg-gray-50 disabled:opacity-50 font-medium">Вперед</button>
          </div>
        </div>

        <p className="text-xs text-gray-500">
          Ручная отметка ставится по статусу и времени; опоздание считает сервер.
          После ручной правки камера больше не перетирает строку.
        </p>
      </div>

      {editing && lesson && (
        <EditModal
          lesson={lesson}
          row={editing}
          onClose={() => setEditing(null)}
          onSaved={async () => { setEditing(null); await load(); }}
        />
      )}
    </div>
  );
};
