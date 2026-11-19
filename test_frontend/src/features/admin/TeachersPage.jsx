import React, { useCallback, useEffect, useState } from 'react';
import { DataTable } from '../../components/ui/DataTable';
import {
  createTeacher,
  deleteTeacher,
  getTeachers,
  patchTeacher,
  setTeacherPassword,
} from '../../services/api';

const emptyForm = { full_name: '', login: '', password: '' };

export const TeachersPage = () => {
  const [teachers, setTeachers] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [formData, setFormData] = useState(emptyForm);
  const [isSaving, setIsSaving] = useState(false);
  const [formError, setFormError] = useState(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getTeachers();
      setTeachers(data.items);
    } catch (e) {
      setError(e.detail || e.message || 'Не удалось загрузить преподавателей');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openCreate = () => {
    setEditingItem(null);
    setFormData(emptyForm);
    setFormError(null);
    setIsModalOpen(true);
  };

  const openEdit = (row) => {
    setEditingItem(row);
    // Пароль не отдаётся сервером и не заполняется: менять его можно только
    // явным действием, иначе правка ФИО молча сбрасывала бы учётку.
    setFormData({ full_name: row.full_name, login: row.login, password: '' });
    setFormError(null);
    setIsModalOpen(true);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setFormError(null);
    setIsSaving(true);
    try {
      if (editingItem) {
        await patchTeacher(editingItem.id, {
          full_name: formData.full_name,
          login: formData.login,
        });
      } else {
        await createTeacher({
          full_name: formData.full_name,
          login: formData.login,
          password: formData.password,
        });
      }
      setIsModalOpen(false);
      await load();
    } catch (err) {
      // 409 — логин занят; приходит текстом detail и показывается как есть,
      // потому что админу нужно знать, какое именно поле конфликтует.
      setFormError(err.detail || 'Не удалось сохранить');
    } finally {
      setIsSaving(false);
    }
  };

  const handlePassword = async (row) => {
    const password = window.prompt(`Новый пароль для «${row.full_name}» (минимум 8 символов)`);
    if (!password) return;
    try {
      await setTeacherPassword(row.id, password);
      window.alert('Пароль изменён');
    } catch (err) {
      window.alert(err.detail || 'Не удалось изменить пароль');
    }
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`Удалить преподавателя «${row.full_name}»?`)) return;
    try {
      await deleteTeacher(row.id);
      await load();
    } catch (err) {
      // 409 — за преподавателем числятся дисциплины: удаление задело бы
      // журнал, поэтому сервер отказывает. Показываем это текстом.
      window.alert(err.detail || 'Не удалось удалить');
    }
  };

  const columns = [
    { key: 'id', label: 'ID' },
    { key: 'full_name', label: 'ФИО' },
    { key: 'login', label: 'Логин' },
    {
      key: 'actions', label: 'Действия', sortable: false,
      render: (_, row) => (
        <div className="flex gap-3">
          <button onClick={() => openEdit(row)} className="text-blue-600 hover:underline">Ред.</button>
          <button onClick={() => handlePassword(row)} className="text-gray-600 hover:underline">Пароль</button>
          <button onClick={() => handleDelete(row)} className="text-red-600 hover:underline">Удал.</button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-blue-900">Управление преподавателями</h1>
        <button onClick={openCreate} className="bg-blue-700 hover:bg-blue-800 text-white px-4 py-2 rounded-lg text-sm font-medium">
          + Добавить преподавателя
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-lg">
          {error}
          <button onClick={load} className="ml-3 underline">Повторить</button>
        </div>
      )}

      <DataTable
        data={teachers}
        columns={columns}
        loading={isLoading}
        emptyMessage="Нет преподавателей"
      />

      {isModalOpen && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md overflow-hidden">
            <div className="bg-blue-800 text-white px-6 py-4 flex justify-between">
              <h2 className="font-bold">{editingItem ? 'Редактировать' : 'Новый'} преподаватель</h2>
              <button onClick={() => setIsModalOpen(false)}>✕</button>
            </div>
            <form onSubmit={handleSave} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-semibold mb-1">ФИО</label>
                <input required type="text" value={formData.full_name} onChange={e => setFormData({ ...formData, full_name: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-sm font-semibold mb-1">Логин</label>
                <input required type="text" value={formData.login} onChange={e => setFormData({ ...formData, login: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm" />
              </div>
              {!editingItem && (
                <div>
                  <label className="block text-sm font-semibold mb-1">Пароль</label>
                  <input required minLength={8} type="password" value={formData.password} onChange={e => setFormData({ ...formData, password: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm" />
                  <p className="text-xs text-gray-500 mt-1">Минимум 8 символов</p>
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
