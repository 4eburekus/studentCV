import React, { useState } from 'react';
import { DataTable } from '../../components/ui/DataTable';

// Моки: список учителей (для выпадающего списка) и дисциплин
const mockTeachers = [
  { id: 1, full_name: 'Иванов Иван Иванович' },
  { id: 2, full_name: 'Петров Петр Петрович' }
];

const initialDisciplines = [
  { id: 1, name: 'Веб-разработка', teacher_id: 1, teacher_name: 'Иванов Иван Иванович' },
  { id: 2, name: 'Управление проектами', teacher_id: 2, teacher_name: 'Петров Петр Петрович' },
];

export const DisciplinesPage = () => {
  const [disciplines, setDisciplines] = useState(initialDisciplines);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  
  const [formData, setFormData] = useState({ name: '', teacher_id: mockTeachers[0].id });

  const openCreate = () => {
    setEditingItem(null);
    setFormData({ name: '', teacher_id: mockTeachers[0].id });
    setIsModalOpen(true);
  };

  const openEdit = (row) => {
    setEditingItem(row);
    setFormData({ name: row.name, teacher_id: row.teacher_id });
    setIsModalOpen(true);
  };

  const handleSave = (e) => {
    e.preventDefault();
    const selectedTeacher = mockTeachers.find(t => t.id === Number(formData.teacher_id));
    
    if (editingItem) {
      setDisciplines(prev => prev.map(d => d.id === editingItem.id ? { ...d, ...formData, teacher_id: Number(formData.teacher_id), teacher_name: selectedTeacher?.full_name } : d));
    } else {
      setDisciplines(prev => [...prev, { ...formData, id: Date.now(), teacher_id: Number(formData.teacher_id), teacher_name: selectedTeacher?.full_name }]);
    }
    setIsModalOpen(false);
  };

  const handleDelete = (id) => {
    if (window.confirm('Удалить дисциплину?')) setDisciplines(prev => prev.filter(d => d.id !== id));
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
        <button onClick={openCreate} className="bg-blue-700 hover:bg-blue-800 text-white px-4 py-2 rounded-lg text-sm font-medium">
          + Добавить дисциплину
        </button>
      </div>

      <DataTable data={disciplines} columns={columns} emptyMessage="Нет дисциплин" />

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
                  {mockTeachers.map(t => <option key={t.id} value={t.id}>{t.full_name}</option>)}
                </select>
              </div>
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