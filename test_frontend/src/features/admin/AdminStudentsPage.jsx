import React, { useCallback, useEffect, useState } from 'react';
import { DataTable } from '../../components/ui/DataTable';
import { StudentPhotos } from '../photos/StudentPhotos';
import {
  createStudent,
  deactivateStudent,
  getStudents,
  patchStudent,
} from '../../services/api';

const GROUP_PATTERN = /^\d{2}-[А-ЯЁ]{3,4}[а-яё]{0,3}-\d{2}$/;

export const AdminStudentsPage = () => {
  const [students, setStudents] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [showInactive, setShowInactive] = useState(false);

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [formData, setFormData] = useState({ full_name: '', group_number: '' });
  const [formError, setFormError] = useState(null);
  const [isSaving, setIsSaving] = useState(false);

  const [photoTarget, setPhotoTarget] = useState(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      // is_active не передаём при showInactive: сервер по умолчанию отдаёт
      // только активных, а «показать всех» выражается отсутствием фильтра.
      const data = await getStudents({
        limit: 500,
        q: search.trim() || undefined,
        ...(showInactive ? {} : { is_active: true }),
      });
      setStudents(data.items);
    } catch (e) {
      setError(e.detail || e.message || 'Не удалось загрузить студентов');
    } finally {
      setIsLoading(false);
    }
  }, [search, showInactive]);

  useEffect(() => {
    // поиск с задержкой: без неё каждый символ — отдельный запрос
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, search]);

  const openCreate = () => {
    setEditingItem(null);
    setFormData({ full_name: '', group_number: '' });
    setFormError(null);
    setIsModalOpen(true);
  };

  const openEdit = (row) => {
    setEditingItem(row);
    setFormData({ full_name: row.full_name, group_number: row.group_number });
    setFormError(null);
    setIsModalOpen(true);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setFormError(null);
    if (!GROUP_PATTERN.test(formData.group_number)) {
      setFormError('Формат группы: 01-ФИИтт-01 (две цифры, 3–4 буквы, две цифры)');
      return;
    }
    setIsSaving(true);
    try {
      if (editingItem) {
        await patchStudent(editingItem.id, formData);
      } else {
        await createStudent(formData);
      }
      setIsModalOpen(false);
      await load();
    } catch (err) {
      setFormError(err.detail || 'Не удалось сохранить');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDeactivate = async (row) => {
    if (!window.confirm(
      `Деактивировать «${row.full_name}»?\n\nСтудент останется в базе, исчезнет из списков и перестанет попадать в новые отметки. Журнал сохранится.`
    )) return;
    try {
      await deactivateStudent(row.id);
      await load();
    } catch (err) {
      window.alert(err.detail || 'Не удалось деактивировать');
    }
  };

  const handleActivate = async (row) => {
    try {
      await patchStudent(row.id, { is_active: true });
      await load();
    } catch (err) {
      window.alert(err.detail || 'Не удалось активировать');
    }
  };

  const columns = [
    { key: 'id', label: 'ID' },
    {
      key: 'full_name', label: 'ФИО',
      render: (v) => <span className="font-semibold text-blue-900">{v}</span>,
    },
    { key: 'group_number', label: 'Группа' },
    {
      key: 'is_active', label: 'Статус',
      render: (v) => (v
        ? <span className="text-green-600 font-bold">Активен</span>
        : <span className="text-red-500 font-bold">Деактивирован</span>),
    },
    {
      key: 'photos', label: 'Фото', sortable: false,
      // Числа фото в списке нет: сервер отдаёт студентов без вложенных
      // массивов. Кнопка ведёт в галерею, которая грузит фото сама.
      render: (_, row) => (
        <button
          onClick={() => setPhotoTarget(row)}
          className="text-blue-600 hover:underline font-semibold"
        >
          Эталоны
        </button>
      ),
    },
    {
      key: 'actions', label: 'Действия', sortable: false,
      render: (_, row) => (
        <div className="flex gap-3">
          <button onClick={() => openEdit(row)} className="text-blue-600 hover:underline">Ред.</button>
          {row.is_active
            ? <button onClick={() => handleDeactivate(row)} className="text-red-600 hover:underline">Деактив.</button>
            : <button onClick={() => handleActivate(row)} className="text-green-700 hover:underline">Актив.</button>}
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-blue-900">Управление студентами</h1>
        <button onClick={openCreate} className="bg-blue-700 hover:bg-blue-800 text-white px-4 py-2 rounded-lg text-sm font-medium">
          + Добавить студента
        </button>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-center">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Поиск по ФИО или группе…"
          className="flex-1 border border-gray-300 rounded-lg px-4 py-2 text-sm"
        />
        <label className="flex items-center gap-2 text-sm text-gray-700 select-none">
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
          Показывать деактивированных
        </label>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-lg">
          {error}
          <button onClick={load} className="ml-3 underline">Повторить</button>
        </div>
      )}

      <DataTable
        data={students}
        columns={columns}
        loading={isLoading}
        emptyMessage="Нет студентов"
      />

      {isModalOpen && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md overflow-hidden">
            <div className="bg-blue-800 text-white px-6 py-4 flex justify-between">
              <h2 className="font-bold">{editingItem ? 'Редактировать' : 'Новый'} студент</h2>
              <button onClick={() => setIsModalOpen(false)}>✕</button>
            </div>
            <form onSubmit={handleSave} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-semibold mb-1">ФИО</label>
                <input required type="text" value={formData.full_name} onChange={e => setFormData({ ...formData, full_name: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-sm font-semibold mb-1">Группа</label>
                <input required type="text" value={formData.group_number} onChange={e => setFormData({ ...formData, group_number: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="01-ФИИтт-01" />
                {editingItem && formData.group_number !== editingItem.group_number && (
                  <p className="text-xs text-amber-700 mt-1">
                    Уже выставленные «Отсутствовал» останутся за парой прежней
                    группы: новый состав группы учитывается только у будущих
                    занятий.
                  </p>
                )}
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

      {photoTarget && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl overflow-hidden">
            <div className="bg-blue-800 text-white px-6 py-4 flex justify-between items-center">
              <h2 className="font-bold">Эталоны: {photoTarget.full_name}</h2>
              <button onClick={() => setPhotoTarget(null)} className="text-blue-200 hover:text-white">✕</button>
            </div>
            <div className="p-6">
              <StudentPhotos
                studentId={photoTarget.id}
                onChanged={load}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
