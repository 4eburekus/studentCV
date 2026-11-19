import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { DataTable } from '../../components/ui/DataTable';
import { closeLesson, getLessons } from '../../services/api';

const timeHM = (v) => (v ? String(v).slice(0, 5) : '');

export const AdminSchedulePage = () => {
  const navigate = useNavigate();
  const [lessons, setLessons] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [closing, setClosing] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getLessons({ limit: 500 });
      setLessons(data.items);
    } catch (e) {
      setError(e.detail || e.message || 'Не удалось загрузить расписание');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Кнопка «Стоп» — это POST /attendance/lessons/{id}/close.
  // Она идемпотентна: повторный клик вернёт absent_created = 0 и
  // was_already_closed = true, поэтому предупреждение ниже говорит именно о
  // том, что произойдёт, а не о необратимости.
  const handleStop = async (row) => {
    if (!window.confirm(
      `Завершить занятие «${row.discipline_name}» ${row.lesson_date} ${timeHM(row.start_time)}?\n\n` +
      'Всем студентам группы без отметки будет проставлено «Отсутствовал». ' +
      'Тех, кого камера зафиксирует позже, это исправит автоматически.'
    )) return;

    setClosing(row.id);
    setNotice(null);
    try {
      const res = await closeLesson(row.id);
      setNotice(
        res.absent_created > 0
          ? `Проставлено отсутствий: ${res.absent_created}` +
            (res.already_recorded ? `, уже отмечено: ${res.already_recorded}` : '')
          : res.was_already_closed
            ? 'Занятие уже было завершено — ничего не изменено'
            : 'Все студенты уже отмечены, отсутствующих нет',
      );
      await load();
    } catch (err) {
      setError(err.detail || 'Не удалось завершить занятие');
    } finally {
      setClosing(null);
    }
  };

  const columns = [
    { key: 'discipline_name', label: 'Дисциплина' },
    { key: 'group_number', label: 'Группа' },
    { key: 'lesson_date', label: 'Дата' },
    { key: 'start_time', label: 'Время', render: (v, row) => `${timeHM(v)}–${timeHM(row.end_time)}` },
    { key: 'room_number', label: 'Аудитория', render: (v) => v || '—' },
    {
      key: 'closed_at', label: 'Закрыта',
      render: (v) => (v
        ? <span className="text-emerald-700 font-semibold" title={new Date(v).toLocaleString('ru-RU')}>да</span>
        : <span className="text-gray-400">нет</span>),
    },
    {
      key: 'actions', label: 'Действия', sortable: false,
      render: (_, row) => (
        <div className="flex gap-2">
          <button
            onClick={() => navigate(`/lessons/${row.id}`)}
            className="px-3 py-1 bg-blue-100 text-blue-700 rounded text-xs font-bold hover:bg-blue-200"
          >
            Журнал
          </button>
          <button
            onClick={() => handleStop(row)}
            disabled={Boolean(row.closed_at) || closing === row.id}
            className={`px-3 py-1 rounded text-xs font-bold ${
              row.closed_at
                ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                : 'bg-red-100 text-red-700 hover:bg-red-200'
            }`}
            title={row.closed_at ? 'Занятие уже закрыто' : 'Проставить отсутствующим ABSENT'}
          >
            {closing === row.id ? '…' : row.closed_at ? 'Завершено' : 'Стоп'}
          </button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-blue-900">Расписание и управление</h1>
        <button onClick={load} className="text-sm text-blue-700 hover:underline">Обновить</button>
      </div>

      {notice && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm px-4 py-3 rounded-lg">
          {notice}
        </div>
      )}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-lg">
          {error}
          <button onClick={load} className="ml-3 underline">Повторить</button>
        </div>
      )}

      <DataTable
        data={lessons}
        columns={columns}
        loading={isLoading}
        emptyMessage="Нет занятий"
      />

      <p className="text-xs text-gray-500">
        «Стоп» проставляет «Отсутствовал» тем, кого ещё не отметили. Пары
        закрываются и автоматически по расписанию — кнопка нужна, чтобы сделать
        это раньше (отменили пару, ушли из аудитории).
      </p>
    </div>
  );
};
