import React, { useCallback, useEffect, useState } from 'react';
import { DataTable } from '../../components/ui/DataTable';
import {
  createDiscipline,
  deleteDiscipline,
  getDisciplines,
  getTeachers,
  patchDiscipline,
} from '../../services/api';

export const DisciplinesPage = () => {
  const [disciplines, setDisciplines] = useState([]);
  // Список преподавателей нужен и таблицей (колонка «Преподаватель»), и
  // выпадающим списком формы. Сервер уже отдаёт teacher_name в дисциплинах,
  // поэтому select - единственная причина тянуть справочник целиком.
  const [teachers, setTeachers] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [formData, setFormData] = useState({ name: '', teacher_id: '' });
  const [isSaving, setIsSaving] = useState(false);
  const [formError, setFormError] = useState(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [disc, teachersData] = await Promise.all([
        getDisciplines(),
        // limit=500 - потолок сервера (см. pagination_params); справочник
        // заведомо меньше, но полагаться на дефолтные 50 здесь нельзя:
        // преподавателей может быть больше, и тогда часть исчезнет из select.
        getTeachers({ limit: 500 }),
      ]);
      setDisciplines(disc.items);
      setTeachers(teachersData.items);
    } catch (e) {
      setError(e.detail || e.message || 'Не удалось загрузить дисциплины');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openCreate = () => {
    setEditingItem(null);
    setFormData({ name: '', teacher_id: teachers[0] ? String(teachers[0].id) : '' });
    setFormError(null);
    setIsModalOpen(true);
  };

  const openEdit = (row) => {
    setEditingItem(row);
    setFormData({ name: row.name, teacher_id: String(row.teacher_id) });
    setFormError(null);
    setIsModalOpen(true);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setFormError(null);
    setIsSaving(true);
    const payload = { name: formData.name, teacher_id: Number(formData.teacher_id) };
    try {
      if (editingItem) {
        await patchDiscipline(editingItem.id, payload);
      } else {
        await createDiscipline(payload);
      }
      setIsModalOpen(false);
      await load();
    } catch (err) {
      // 409 — такая дисциплина у этого преподавателя уже есть (UNIQUE
      // name+teacher_id, миграция 0004). Без текста ошибки админ не поймёт,
      // что дубликат именно в связке с преподавателем.
      setFormError(err.detail || 'Не удалось сохранить');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`Удалить дисциплину «${row.name}»?`)) return;
    try {
      await deleteDiscipline(row.id);
      await load();
    } catch (err) {
      // 409 — у дисциплины есть пары с записями журнала: каскад утащил бы
      // за ними и посещаемость, поэтому сервер отказывает.
      window.alert(err.detail || 'Не удалось удалить');
    }
  };

  const columns = [
    { key: 'id', label: 'ID' },
    { key: 'name', label: 'Название дисциплины' },
    { key: 'teacher_name', label: 'Преподаватель' },
    {
      key: 'actions', label: 'Действия', sortable: false,
      render: (_, row) => (
        <div className="flex gap-3">
          <button onClick={() => openEdit(row)} className="text-blue-600 hover:underline">Ред.</button>
          <button onClick={() => handleDelete(row.id)} className="text-red-600 hover:underline">Удал.</button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-blue-900">Управление дисциплинами</h1>
        <button
          onClick={openCreate}
          disabled={teachers.length === 0}
          className="bg-blue-700 hover:bg-blue-800 text-white px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
        >
          + Добавить дисциплину
        </button>
      </div>

      {teachers.length === 0 && !isLoading && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 text-sm px-4 py-3 rounded-lg">
          Сначала заведите хотя бы одного преподавателя — дисциплина всегда
          привязана к конкретному преподавателю.
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-lg">
          {error}
          <button onClick={load} className="ml-3 underline">Повторить</button>
        </div>
      )}

      <DataTable
        data={disciplines}
        columns={columns}
        loading={isLoading}
        emptyMessage="Нет дисциплин"
      />

      {isModalOpen && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md overflow-hidden">
            <div className="bg-blue-800 text-white px-6 py-4 flex justify-between">
              <h2 className="font-bold">{editingItem ? 'Редактировать' : 'Новая'} дисциплина</h2>
              <button onClick={() => setIsModalOpen(false)}>✕</button>
            </div>
            <form onSubmit={handleSave} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-semibold mb-1">Название</label>
                <input required type="text" value={formData.name} onChange={e => setFormData({ ...formData, name: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-sm font-semibold mb-1">Преподаватель</label>
                <select value={formData.teacher_id} onChange={e => setFormData({ ...formData, teacher_id: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm" required>
                  {teachers.map(t => <option key={t.id} value={t.id}>{t.full_name}</option>)}
                </select>
              </div>
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
