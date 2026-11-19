// src/features/attendance/LessonJournalPage.jsx
import React, { useState, useMemo, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { DataTable } from '../../components/ui/DataTable';
import { getJournal, getStudents } from '../../services/api';

const FaceIdIcon = () => (
  <svg className="w-4 h-4 text-blue-600 inline-block mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 008 11a4 4 0 118 0c0 1.017-.07 2.019-.203 3m-2.118 6.844A21.88 21.88 0 0015.171 17m3.839 1.132c.645-2.266.99-4.659.99-7.132A8 8 0 008 4.07M3 15.364c.64-1.319 1-2.8 1-4.364 0-1.457.39-2.823 1.07-4"></path><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 10h.01M15 10h.01"></path></svg>
);
const ManualIcon = () => (
  <svg className="w-4 h-4 text-gray-500 inline-block mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
);

// «Отсутствовал» — вычисляемое состояние, НЕ статус из API
const STATUS_META = {
  PRESENT: { label: 'Присутствовал', cls: 'bg-green-100 text-green-700 border-green-200' },
  LATE:    { label: 'Опоздал',       cls: 'bg-yellow-100 text-yellow-700 border-yellow-200' },
  ABSENT:  { label: 'Отсутствовал',  cls: 'bg-red-100 text-red-700 border-red-200' },
};

export const LessonJournalPage = () => {
  const { lessonId } = useParams(); // /lessons/:lessonId
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [journalRecords, setJournalRecords] = useState([]);
  const [groupStudents, setGroupStudents] = useState([]);

  // TODO: группа берётся из пары (getLessons / lesson.group_number). Пока — из журнала/мока.
  const [groupNumber, setGroupNumber] = useState('23-ИСбо-04');



/*  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      getJournal(lessonId),
      getStudents({ group: groupNumber, is_active: true, limit: 500 }),
    ])
      .then(([journal, studentsRes]) => {
        if (cancelled) return;
        setJournalRecords(Array.isArray(journal) ? journal : journal?.items ?? []);
        setGroupStudents(studentsRes?.items ?? studentsRes ?? []);
      })
      .catch((e) => !cancelled && setError(e))
      .finally(() => !cancelled && setLoading(false));

    return () => { cancelled = true; };
  }, [lessonId, groupNumber]); */

  useEffect(() => {
    // ВРЕМЕННАЯ ЗАГЛУШКА ДЛЯ ПРОСМОТРА ТАБЛИЦЫ
    setLoading(true);
    setTimeout(() => {
      setJournalRecords([
        { id: 1, student_id: 1, full_name: 'Охламон Григорий Алексеевич', group_number: '23-ИСбо-04', captured_at: '2026-11-16T08:32:00+03:00', status: 'LATE', delay_minutes: 2, is_manually_edited: false },
        { id: 2, student_id: 2, full_name: 'Великий Павел', group_number: '23-ИСбо-04', captured_at: '2026-11-16T08:45:00+03:00', status: 'LATE', delay_minutes: 15, is_manually_edited: true },
      ]);
      setGroupStudents([
        { id: 1, full_name: 'Охламон Григорий Алексеевич', group_number: '23-ИСбо-04', is_active: true },
        { id: 2, full_name: 'Великий Павел', group_number: '23-ИСбо-04', is_active: true },
        { id: 3, full_name: 'Смирнов Даниил Дмитриевич', group_number: '23-ИСбо-04', is_active: true }, // Этот будет "Отсутствовал"
      ]);
      setLoading(false);
    }, 500);
  }, [lessonId, groupNumber]);




  // Склейка: студенты группы + записи журнала → строки таблицы
  const rows = useMemo(() => {
    const byStudent = new Map(journalRecords.map(r => [r.student_id, r]));
    return groupStudents.map((s) => {
      const rec = byStudent.get(s.id);
      return {
        id: s.id,
        student_id: s.id,
        full_name: s.full_name,
        group_number: s.group_number,
        captured_at: rec?.captured_at ?? null,
        status: rec ? rec.status : 'ABSENT', // вычисляемое
        delay_minutes: rec?.delay_minutes ?? null,
        is_manually_edited: rec?.is_manually_edited ?? false,
        hasRecord: Boolean(rec),
      };
    });
  }, [journalRecords, groupStudents]);

  // --- Фильтры (серверные по-хорошему; для журнала пары — можно локально по группе) ---
  const [statusFilter, setStatusFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  const filteredRows = useMemo(() => rows.filter((r) => {
    const matchStatus = statusFilter ? r.status === statusFilter : true;
    const matchSearch = r.full_name.toLowerCase().includes(searchQuery.toLowerCase());
    return matchStatus && matchSearch;
  }), [rows, statusFilter, searchQuery]);

  // --- Пагинация (журнал пары обычно небольшой; page/limit — если бэк отдаёт total) ---
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 50;

  useEffect(() => { setCurrentPage(1); }, [statusFilter, searchQuery]);
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / itemsPerPage));
  const currentItems = filteredRows.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage);

  // --- Ручная правка ---
  const [editingRowId, setEditingRowId] = useState(null);
  const [editFormData, setEditFormData] = useState({});

  const startEditing = (row) => {
    // TODO (вопрос к Паше): ручная правка без frame_object_key пока невозможна —
    // POST /attendance/events требует frame_object_key. Ждём спец-эндпоинт ручной правки.
    console.warn('Ручная правка ждёт эндпоинт от бэкенда');
    // Заглушка: правка статуса present/late в локальном состоянии
    setEditingRowId(row.id);
    setEditFormData({ status: row.status === 'ABSENT' ? 'PRESENT' : row.status, captured_at: row.captured_at ?? '' });
  };
  const cancelEditing = () => { setEditingRowId(null); setEditFormData({}); };
  const saveEditing = (id) => {
    // TODO: заменить на реальный запрос, когда Паша даст эндпоинт ручной правки
    // Сейчас — только локально, с пометкой is_manually_edited
    setJournalRecords((prev) => {
      const idx = prev.findIndex(r => r.student_id === id);
      const next = [...prev];
      if (idx >= 0) {
        next[idx] = { ...next[idx], status: editFormData.status, is_manually_edited: true };
      } else {
        // создаём локальную запись, чтобы отобразить статус
        next.push({ student_id: id, status: editFormData.status, captured_at: editFormData.captured_at || new Date().toISOString(), is_manually_edited: true, id: -Date.now() });
      }
      return next;
    });
    setEditingRowId(null);
  };
  const handleEditChange = (field, value) => setEditFormData(prev => ({ ...prev, [field]: value }));

  // --- Кнопка «Стоп отметок» ---
  // TODO (вопрос к Паше): эндпоинта нет. Не эмулировать на клиенте — рассинхрон с бэком.
  const stopAttendance = () => {
    alert('Функция появится после реализации эндпоинта на бэкенде (вопрос к Паше).');
  };

  const columns = [
    { key: 'full_name', label: 'ФИО студента', render: (v) => <span className="font-semibold text-blue-900">{v}</span> },
    { key: 'group_number', label: 'Группа' },
    {
      key: 'captured_at', label: 'Время',
      render: (v) => v ? new Date(v).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : '—',
    },
    {
      key: 'status', label: 'Статус',
      render: (status, row) => {
        if (editingRowId === row.id) {
          return (
            <select value={editFormData.status} onChange={e => handleEditChange('status', e.target.value)} className="border border-blue-300 rounded px-2 py-1 text-xs font-bold outline-none focus:ring-2 focus:ring-blue-500">
              <option value="PRESENT">Присутствовал</option>
              <option value="LATE">Опоздал</option>
            </select>
          );
        }
        const meta = STATUS_META[status];
        if (!meta) return <span className="text-gray-400">—</span>;
        return <span className={`px-3 py-1 rounded-full text-xs font-bold border ${meta.cls}`}>{meta.label}</span>;
      },
    },
    {
      key: 'is_manually_edited', label: 'Источник', sortable: false,
      render: (manual) => <span className="flex items-center text-sm text-gray-500">{!manual ? <><FaceIdIcon /> Face ID</> : <><ManualIcon /> Вручную</>}</span>,
    },
    {
      key: 'actions', label: 'Действие', sortable: false,
      render: (_, row) => {
        const cls = 'flex items-center gap-2 min-w-[200px]';
        if (editingRowId === row.id) {
          return (
            <div className={cls}>
              <button onClick={() => saveEditing(row.student_id)} className="text-xs font-semibold bg-green-500 hover:bg-green-600 text-white px-3 py-1.5 rounded">Сохранить</button>
              <button onClick={cancelEditing} className="text-xs font-semibold bg-gray-200 hover:bg-gray-300 text-gray-700 px-3 py-1.5 rounded">Отмена</button>
            </div>
          );
        }
        return (
          <div className={cls}>
            <button onClick={() => startEditing(row)} className="text-xs font-semibold text-blue-600 hover:text-blue-800 hover:underline">Изменить</button>
          </div>
        );
      },
    },
  ];

  if (loading) return <div className="p-8 text-gray-500">Загрузка журнала…</div>;
  if (error) return <div className="p-8 text-red-600">Ошибка {error.status}: {typeof error.detail === 'string' ? error.detail : 'не удалось загрузить журнал'}</div>;

  return (
    <div className="min-h-screen bg-slate-100 p-4 md:p-8 font-sans">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="bg-white p-6 rounded-xl shadow-sm border border-blue-100 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <h1 className="text-2xl font-bold text-blue-900">Журнал пары #{lessonId}</h1>
            <p className="text-sm text-gray-500 mt-1">Группа {groupNumber} · управление посещаемостью</p>
          </div>
          <div className="flex gap-3">
            {/* TODO: эндпоинт «досрочно остановить отметки» — вопрос к Паше */}
            <button onClick={stopAttendance} className="bg-red-600 hover:bg-red-700 text-white px-5 py-2.5 rounded-lg text-sm font-medium shadow-sm">
              Завершить отметки досрочно
            </button>
          </div>
        </div>

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
      </div>
    </div>
  );
};