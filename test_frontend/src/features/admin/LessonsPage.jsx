import React, { useState } from 'react';
import { DataTable } from '../../components/ui/DataTable';

// Моки по ERD
const initialLessons = [
  { id: 1, discipline_id: 1, discipline_name: 'Веб-разработка', lesson_date: '2026-11-16', start_time: '08:30', end_time: '10:00', room_number: 'А-301' },
];
const mockDisciplines = [{ id: 1, name: 'Веб-разработка' }, { id: 2, name: 'Управление проектами' }];

export const LessonsPage = () => {
  const [lessons, setLessons] = useState(initialLessons);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  
  const [formData, setFormData] = useState({ discipline_id: '', lesson_date: '', start_time: '', end_time: '', room_number: '' });

  const openCreate = () => {
    setEditingItem(null);
    setFormData({ discipline_id: mockDisciplines[0].id, lesson_date: new Date().toISOString().split('T')[0], start_time: '08:30', end_time: '10:00', room_number: '' });
    setIsModalOpen(true);
  };

  const openEdit = (row) => {
    setEditingItem(row);
    setFormData({ discipline_id: row.discipline_id, lesson_date: row.lesson_date, start_time: row.start_time, end_time: row.end_time, room_number: row.room_number });
    setIsModalOpen(true);
  };

  const handleSave = (e) => {
    e.preventDefault();
    const selectedDiscipline = mockDisciplines.find(d => d.id === Number(formData.discipline_id));
    
    if (editingItem) {
      setLessons(prev => prev.map(l => l.id === editingItem.id ? { ...l, ...formData, discipline_id: Number(formData.discipline_id), discipline_name: selectedDiscipline?.name } : l));
    } else {
      setLessons(prev => [...prev, { ...formData, id: Date.now(), discipline_id: Number(formData.discipline_id), discipline_name: selectedDiscipline?.name }]);
    }
    setIsModalOpen(false);
  };

  const handleDelete = (id) => {
    if (window.confirm('Удалить занятие?')) setLessons(prev => prev.filter(l => l.id !== id));
  };

  const columns = [
    { key: 'id', label: 'ID' },
    { key: 'discipline_name', label: 'Дисциплина' },
    { key: 'lesson_date', label: 'Дата' },
    { key: 'start_time', label: 'Начало' },
    { key: 'end_time', label: 'Конец' },
    { key: 'room_number', label: 'Аудитория' },
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
        <h1 className="text-2xl font-bold text-blue-900">Управление занятиями</h1>
        <button onClick={openCreate} className="bg-blue-700 hover:bg-blue-800 text-white px-4 py-2 rounded-lg text-sm font-medium">
          + Добавить занятие
        </button>
      </div>

      <DataTable data={lessons} columns={columns} emptyMessage="Нет занятий" />

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
                <select value={formData.discipline_id} onChange={e => setFormData({ ...formData, discipline_id: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm" required>
                  {mockDisciplines.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-semibold mb-1">Дата</label>
                <input required type="date" value={formData.lesson_date} onChange={e => setFormData({ ...formData, lesson_date: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm" />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold mb-1">Начало</label>
                  <input required type="time" value={formData.start_time} onChange={e => setFormData({ ...formData, start_time: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm" />
                </div>
                <div>
                  <label className="block text-sm font-semibold mb-1">Конец</label>
                  <input required type="time" value={formData.end_time} onChange={e => setFormData({ ...formData, end_time: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm" />
                </div>
              </div>
              <div>
                <label className="block text-sm font-semibold mb-1">Аудитория</label>
                <input required type="text" value={formData.room_number} onChange={e => setFormData({ ...formData, room_number: e.target.value })} className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="А-301" />
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