import React, { useState } from 'react';
import { DataTable } from '../../components/ui/DataTable';

// Моки по ERD
const initialTeachers = [
  { id: 1, full_name: 'Иванов Иван Иванович', login: 'teacher_ivan' },
  { id: 2, full_name: 'Петров Петр Петрович', login: 'teacher_petr' },
];

export const TeachersPage = () => {
  const [teachers, setTeachers] = useState(initialTeachers);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);

  const [formData, setFormData] = useState({ full_name: '', login: '', password: '' });

  const openCreate = () => {
    setEditingItem(null);
    setFormData({ full_name: '', login: '', password: '' });
    setIsModalOpen(true);
  };

  const openEdit = (row) => {
    setEditingItem(row);
    setFormData({ full_name: row.full_name, login: row.login, password: '' }); // Пароль не отдаем
    setIsModalOpen(true);
  };

  const handleSave = (e) => {
    e.preventDefault();
    if (editingItem) {
      setTeachers(prev => prev.map(t => t.id === editingItem.id ? { ...t, full_name: formData.full_name, login: formData.login } : t));
    } else {
      setTeachers(prev => [...prev, { ...formData, id: Date.now() }]); // В реале POST /teachers
    }
    setIsModalOpen(false);
  };

  const handleDelete = (id) => {
    if (window.confirm('Удалить преподавателя?')) {
      setTeachers(prev => prev.filter(t => t.id !== id));
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
          <button onClick={() => handleDelete(row.id)} className="text-red-600 hover:underline">Удал.</button>
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

      <DataTable data={teachers} columns={columns} emptyMessage="Нет преподавателей" />

      {/* Модалка создания/редактирования */}
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
                  <input required type="password" value={formData.password} onChange={e => setFormData({ ...formData, password: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm" />
                </div>
              )}
              <div className="pt-2 flex gap-3">
                <button type="button" onClick={() => setIsModalOpen(false)} className="flex-1 py-2 border rounded-lg hover:bg-gray-50">Отмена</button>
                <button type="submit" className="flex-1 py-2 bg-blue-700 text-white rounded-lg hover:bg-blue-800">Сохранить</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};