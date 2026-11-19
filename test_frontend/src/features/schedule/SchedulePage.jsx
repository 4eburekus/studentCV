// src/features/schedule/SchedulePage.jsx
import React, { useEffect, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { getLessons } from '../../services/api';

export const SchedulePage = () => {
  const navigate = useNavigate();
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [view, setView] = useState('day'); // 'day' | 'week'
  const [lessons, setLessons] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

/*  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getLessons({ date, limit: 500 })
      .then((res) => !cancelled && setLessons(res?.items ?? res ?? []))
      .catch((e) => !cancelled && setError(e))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [date]); */


    useEffect(() => {
    // ВРЕМЕННАЯ ЗАГЛУШКА ДЛЯ ПРОСМОТРА ДИЗАЙНА
    setLoading(true);
    setTimeout(() => {
      setLessons([
        { id: 1, lesson_date: new Date().toISOString().slice(0, 10), start_time: '08:30', end_time: '10:00', discipline: 'Управление проектами', group_number: '23-ИСбо-04', auditorium: 'А-301' },
        { id: 2, lesson_date: new Date().toISOString().slice(0, 10), start_time: '10:15', end_time: '11:45', discipline: 'Веб-разработка', group_number: '23-ИСбо-04', auditorium: 'А-204' }
      ]);
      setLoading(false);
    }, 500); // имитация загрузки
  }, [date]); // Зависимость от date оставили, чтобы при смене даты список обновлялся


  
  // Для недельного вида — фильтрация по диапазону на клиенте (или отдельные запросы по датам)
  const visibleLessons = useMemo(() => {
    if (view === 'day') return lessons.filter(l => l.lesson_date === date);
    return lessons;
  }, [lessons, date, view]);

  return (
    <div className="min-h-screen bg-slate-100 p-4 md:p-8 font-sans">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="bg-white p-6 rounded-xl shadow-sm border border-blue-100 flex flex-col md:flex-row justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-blue-900">Расписание</h1>
            <p className="text-sm text-gray-500 mt-1">Пары преподавателя</p>
          </div>
          <div className="flex gap-3 items-end">
            <div>
              <label className="block text-xs font-semibold text-gray-500 mb-1 uppercase">Дата</label>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="border border-gray-300 rounded-lg px-4 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-500 mb-1 uppercase">Вид</label>
              <select value={view} onChange={(e) => setView(e.target.value)} className="border border-gray-300 rounded-lg px-4 py-2 text-sm">
                <option value="day">День</option>
                <option value="week">Неделя</option>
              </select>
            </div>
          </div>
        </div>

        {loading && <div className="text-gray-500">Загрузка…</div>}
        {error && <div className="text-red-600">Ошибка {error.status}: {typeof error.detail === 'string' ? error.detail : 'не удалось загрузить'}</div>}

        {!loading && !error && (
          <div className="grid gap-3">
            {visibleLessons.length === 0 && <div className="text-gray-500">Нет пар</div>}
            {visibleLessons.map((l) => (
              <button
                key={l.id}
                onClick={() => navigate(`/lessons/${l.id}`)}
                className="text-left bg-white p-4 rounded-xl shadow-sm border border-blue-100 hover:border-blue-300 hover:shadow transition"
              >
                <div className="flex justify-between items-center">
                  <div>
                    <div className="font-semibold text-blue-900">{l.discipline}</div>
                    <div className="text-sm text-gray-500">{l.group_number} · ауд. {l.auditorium}</div>
                  </div>
                  <div className="text-sm font-mono text-gray-700">{l.start_time}–{l.end_time}</div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};