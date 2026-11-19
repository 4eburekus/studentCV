import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { DataTable } from '../../components/ui/DataTable';
import {
  createLesson,
  deleteLesson,
  getDisciplines,
  getLessons,
  getStudents,
  patchLesson,
} from '../../services/api';

// Формат номера группы тот же, что проверяют БД и backend (GROUP_NUMBER_REGEX
// в db/models.py): 01-ФИИтт-01. Паттерн поля - только раннее предупреждение,
// настоящей проверкой остаётся сервер: 422 с текстом приходит и сюда, и в
// smoke, и в API-вызов без фронтенда.
const GROUP_PATTERN = /^\d{2}-[А-ЯЁ]{3,4}[а-яё]{0,3}-\d{2}$/;

const timeHM = (value) => (value ? String(value).slice(0, 5) : '');

export const LessonsPage = () => {
  const [lessons, setLessons] = useState([]);
  const [disciplines, setDisciplines] = useState([]);
  const [groups, setGroups] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [formError, setFormError] = useState(null);
  const [formData, setFormData] = useState({
    discipline_id: '', group_number: '', lesson_date: '',
    start_time: '', end_time: '', room_number: '',
  });

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [ls, ds, ss] = await Promise.all([
        getLessons({ limit: 500 }),
        getDisciplines({ limit: 500 }),
        // Уникальные группы нужны списком выбора: группа пары обязана
        // совпадать с group_number студентов, иначе журнал закроется пустым.
        getStudents({ limit: 500 }),
      ]);
      setLessons(ls.items);
      setDisciplines(ds.items);
      setGroups([...new Set(ss.items.map((s) => s.group_number))].sort());
    } catch (e) {
      setError(e.detail || e.message || 'Не удалось загрузить занятия');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openCreate = () => {
    setEditingItem(null);
    setFormData({
      discipline_id: disciplines[0] ? String(disciplines[0].id) : '',
      group_number: groups[0] || '',
      lesson_date: new Date().toISOString().split('T')[0],
      start_time: '08:30',
      end_time: '10:00',
      room_number: '',
    });
    setFormError(null);
    setIsModalOpen(true);
  };

  const openEdit = (row) => {
    setEditingItem(row);
    setFormData({
      discipline_id: String(row.discipline_id),
      group_number: row.group_number,
      lesson_date: row.lesson_date,
      start_time: timeHM(row.start_time),
      end_time: timeHM(row.end_time),
      room_number: row.room_number || '',
    });
    setFormError(null);
    setIsModalOpen(true);
  };

  // Закрытую пару нельзя переводить в другую группу/день/время: ABSENT уже
    // проставлен по старым границам, и сервер ответит 409. Поля блокируются
  // заранее, чтобы отказ не выглядел поломкой формы.
  const isFrozen = Boolean(editingItem?.closed_at);

  const handleSave = async (e) => {
    e.preventDefault();
    setFormError(null);

    if (!GROUP_PATTERN.test(formData.group_number)) {
      setFormError('Формат группы: 01-ФИИтт-01 (две цифры, 3–4 буквы, две цифры)');
      return;
    }
    if (formData.end_time <= formData.start_time) {
      setFormError('Время конца должно быть позже начала');
      return;
    }

    setIsSaving(true);
    const base = {
      discipline_id: Number(formData.discipline_id),
      lesson_date: formData.lesson_date,
      start_time: formData.start_time,
      end_time: formData.end_time,
      // Пустая строка -> null: иначе «очистить аудиторию» отправило бы ""
      room_number: formData.room_number.trim() ? formData.room_number.trim() : null,
    };
    try {
      if (editingItem) {
        await patchLesson(editingItem.id, isFrozen ? { room_number: base.room_number } : base);
      } else {
        await createLesson({ ...base, group_number: formData.group_number });
      }
      setIsModalOpen(false);
      await load();
    } catch (err) {
      setFormError(err.detail || 'Не удалось сохранить');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`Удалить занятие «${row.discipline_name}» ${row.lesson_date} ${timeHM(row.start_time)}?`)) {
      return;
    }
    try {
      await deleteLesson(row.id);
      await load();
    } catch (err) {
      // 409 — у пары есть записи журнала. Каскад утащил бы посещаемость,
      // поэтому сервер отказывает; текст приходит с количеством записей.
      window.alert(err.detail || 'Не удалось удалить');
    }
  };

  const columns = useMemo(() => [
    { key: 'id', label: 'ID' },
    { key: 'discipline_name', label: 'Дисциплина' },
    { key: 'group_number', label: 'Группа' },
    { key: 'lesson_date', label: 'Дата' },
    { key: 'start_time', label: 'Начало', render: (v) => timeHM(v) },
    { key: 'end_time', label: 'Конец', render: (v) => timeHM(v) },
    { key: 'room_number', label: 'Аудитория', render: (v) => v || '—' },
    {
      key: 'closed_at', label: 'Закрыта',
      render: (v) => (v ? <span className="text-emerald-700">да</span> : <span className="text-gray-400">нет</span>),
    },
    {
      key: 'actions', label: 'Действия', sortable: false,
      render: (_, row) => (
        <div className="flex gap-3">
          <button onClick={() => openEdit(row)} className="text-blue-600 hover:underline">Ред.</button>
          <button onClick={() => handleDelete(row.id)} className="text-red-600 hover:underline">Удал.</button>
        </div>
      ),
    },
  ], [disciplines]);

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-blue-900">Управление занятиями</h1>
        <button
          onClick={openCreate}
          disabled={disciplines.length === 0}
          className="bg-blue-700 hover:bg-blue-800 text-white px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
        >
          + Добавить занятие
        </button>
      </div>

      {disciplines.length === 0 && !isLoading && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 text-sm px-4 py-3 rounded-lg">
          Сначала заведите дисциплины — занятие всегда привязано к паре
          «дисциплина + группа».
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

      {isModalOpen && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md overflow-hidden">
            <div className="bg-blue-800 text-white px-6 py-4 flex justify-between">
              <h2 className="font-bold">{editingItem ? 'Редактировать' : 'Новое'} занятие</h2>
              <button onClick={() => setIsModalOpen(false)}>✕</button>
            </div>
            <form onSubmit={handleSave} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-semibold mb-1">Дисциплина</label>
                <select value={formData.discipline_id} disabled={isFrozen} onChange={e => setFormData({ ...formData, discipline_id: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm disabled:bg-gray-100" required>
                  {disciplines.map(d => <option key={d.id} value={d.id}>{d.name} — {d.teacher_name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-semibold mb-1">Группа</label>
                <input
                  required
                  type="text"
                  list="known-groups"
                  disabled={isFrozen}
                  value={formData.group_number}
                  onChange={e => setFormData({ ...formData, group_number: e.target.value })}
                  className="w-full border rounded-lg px-3 py-2 text-sm disabled:bg-gray-100"
                  placeholder="01-ФИИтт-01"
                />
                <datalist id="known-groups">
                  {groups.map(g => <option key={g} value={g} />)}
                </datalist>
                <p className="text-xs text-gray-500 mt-1">
                  Студенты этой группы попадут в журнал пары
                </p>
              </div>
              <div>
                <label className="block text-sm font-semibold mb-1">Дата</label>
                <input required type="date" disabled={isFrozen} value={formData.lesson_date} onChange={e => setFormData({ ...formData, lesson_date: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm disabled:bg-gray-100" />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold mb-1">Начало</label>
                  <input required type="time" disabled={isFrozen} value={formData.start_time} onChange={e => setFormData({ ...formData, start_time: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm disabled:bg-gray-100" />
                </div>
                <div>
                  <label className="block text-sm font-semibold mb-1">Конец</label>
                  <input required type="time" disabled={isFrozen} value={formData.end_time} onChange={e => setFormData({ ...formData, end_time: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm disabled:bg-gray-100" />
                </div>
              </div>
              <div>
                <label className="block text-sm font-semibold mb-1">Аудитория</label>
                <input type="text" value={formData.room_number} onChange={e => setFormData({ ...formData, room_number: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="А-301" />
              </div>

              {isFrozen && (
                <div className="bg-amber-50 border border-amber-200 text-amber-800 text-xs px-3 py-2 rounded">
                  Занятие закрыто {new Date(editingItem.closed_at).toLocaleString('ru-RU')} —
                  группа, дата и время зафиксированы, изменена может быть только
                  аудитория.
                </div>
              )}

              {formError && (
                <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2 rounded">
                  {formError}
                </div>
              )}

              <div className="pt-2 flex gap-3">
                <button type="button" onClick={() => setIsModalOpen(false)} className="flex-1 py-2 border rounded-lg hover:bg-gray-50">Отмена</button>
                <button type="submit" disabled={isSaving} className="flex-1 py-2 bg-blue-700 text-white rounded-lg hover:bg-blue-800 disabled:opacity-50">
                  {isSaving ? 'Сохранение…' : 'Сохранить'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
