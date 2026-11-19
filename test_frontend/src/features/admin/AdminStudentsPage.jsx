import React, { useState } from 'react';
import { DataTable } from '../../components/ui/DataTable';

// Моки обновлены: добавлен массив photos для каждого студента
const initialStudents = [
  { 
    id: 1, full_name: 'Охламон Григорий Алексеевич', group_number: '23-ИСбо-04', is_active: true, 
    photos: [
      { id: 101, photo_url: 'biometrics/a1b2c3d4-e5f6.jpg', created_at: '2026-11-16T10:00:00Z' },
      { id: 102, photo_url: 'biometrics/b2c3d4e5-f6g7.jpg', created_at: '2026-11-16T10:05:00Z' },
      { id: 103, photo_url: 'biometrics/c3d4e5f6-g7h8.jpg', created_at: '2026-11-16T10:10:00Z' }
    ] 
  },
  { 
    id: 2, full_name: 'Великий Павел', group_number: '23-ИСбо-04', is_active: true, 
    photos: [
      { id: 201, photo_url: 'biometrics/d4e5f6g7-h8i9.jpg', created_at: '2026-11-16T11:00:00Z' }
    ] 
  },
];

export const AdminStudentsPage = () => {
  const [students, setStudents] = useState(initialStudents);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isPhotoModalOpen, setIsPhotoModalOpen] = useState(false);
  
  const [editingItem, setEditingItem] = useState(null);
  const [photoTarget, setPhotoTarget] = useState(null);
  
  const [formData, setFormData] = useState({ full_name: '', group_number: '', is_active: true });

  // ... (openCreate, openEdit, handleSave, handleDeactivate остаются без изменений) ...
  const openCreate = () => {
    setEditingItem(null);
    setFormData({ full_name: '', group_number: '', is_active: true });
    setIsModalOpen(true);
  };

  const openEdit = (row) => {
    setEditingItem(row);
    setFormData({ full_name: row.full_name, group_number: row.group_number, is_active: row.is_active });
    setIsModalOpen(true);
  };

  const handleSave = (e) => {
    e.preventDefault();
    if (editingItem) {
      setStudents(prev => prev.map(s => s.id === editingItem.id ? { ...s, ...formData } : s));
    } else {
      setStudents(prev => [...prev, { ...formData, id: Date.now(), photos: [] }]);
    }
    setIsModalOpen(false);
  };

  const handleDeactivate = (id) => {
    if (window.confirm('Деактивировать студента? (is_active = false)')) {
      setStudents(prev => prev.map(s => s.id === id ? { ...s, is_active: false } : s));
    }
  };

  // Заглушка загрузки фото
  const handlePhotoUpload = (e) => {
    e.preventDefault();
    if (photoTarget.photos.length >= 5) {
      alert('Максимум 5 фото!');
      return;
    }
    const newPhoto = {
      id: Date.now(),
      photo_url: `biometrics/${Math.random().toString(36).substring(7)}.jpg`,
      created_at: new Date().toISOString()
    };
    setStudents(prev => prev.map(s => s.id === photoTarget.id ? { ...s, photos: [...s.photos, newPhoto] } : s));
    setPhotoTarget(prev => ({ ...prev, photos: [...prev.photos, newPhoto] }));
    e.target.reset();
  };

  const handlePhotoDelete = (photoId) => {
    if (window.confirm('Удалить это фото?')) {
      setStudents(prev => prev.map(s => s.id === photoTarget.id ? { ...s, photos: s.photos.filter(p => p.id !== photoId) } : s));
      setPhotoTarget(prev => ({ ...prev, photos: prev.photos.filter(p => p.id !== photoId) }));
    }
  };

  const columns = [
    { key: 'id', label: 'ID' },
    { key: 'full_name', label: 'ФИО' },
    { key: 'group_number', label: 'Группа' },
    { 
      key: 'is_active', label: 'Статус',
      render: (is_active) => is_active 
        ? <span className="text-green-600 font-bold">Активен</span> 
        : <span className="text-red-500 font-bold">Деактивирован</span>
    },
    { 
      key: 'photos', label: 'Фото',
      render: (photos, row) => (
        <button onClick={() => { setPhotoTarget(row); setIsPhotoModalOpen(true); }} className="text-blue-600 hover:underline font-semibold">
          {photos.length} шт. (Смотреть)
        </button>
      )
    },
    {
      key: 'actions', label: 'Действия', sortable: false,
      render: (_, row) => (
        <div className="flex gap-3">
          <button onClick={() => openEdit(row)} className="text-blue-600 hover:underline">Ред.</button>
          {row.is_active && (
            <button onClick={() => handleDeactivate(row.id)} className="text-red-600 hover:underline">Деактив.</button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      {/* ... Заголовок и таблица без изменений ... */}
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-blue-900">Управление студентами</h1>
        <button onClick={openCreate} className="bg-blue-700 hover:bg-blue-800 text-white px-4 py-2 rounded-lg text-sm font-medium">
          + Добавить студента
        </button>
      </div>
      <DataTable data={students} columns={columns} emptyMessage="Нет студентов" />

      {/* Модалка редактирования (без изменений) */}
      {/* ... */}

      {/* ОБНОВЛЕННАЯ Модалка управления фото */}
      {isPhotoModalOpen && photoTarget && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl overflow-hidden">
            <div className="bg-blue-800 text-white px-6 py-4 flex justify-between items-center">
              <h2 className="font-bold">Фото студента: {photoTarget.full_name}</h2>
              <button onClick={() => setIsPhotoModalOpen(false)} className="text-blue-200 hover:text-white">✕</button>
            </div>
            
            <div className="p-6 space-y-6">
              {/* Блок предупреждения (статус ниже минимума) */}
              {photoTarget.photos.length < 3 && (
                <div className="bg-yellow-50 border border-yellow-200 text-yellow-800 p-3 rounded text-sm flex items-center gap-2">
                  <span className="text-lg">⚠️</span>
                  <span>Эталонов меньше минимума. Студент не будет распознаваться системой.</span>
                </div>
              )}

              {/* Сетка фотографий */}
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                {photoTarget.photos.length === 0 && (
                  <div className="col-span-full text-center text-gray-500 py-4">Нет загруженных фото</div>
                )}
                
                {photoTarget.photos.map((photo) => (
                  <div key={photo.id} className="border border-gray-200 rounded-lg overflow-hidden group relative">
                    {/* ЗАГЛУШКА вместо реальной картинки, т.к. photo_url - это ключ */}
                    <div className="bg-slate-100 aspect-square flex flex-col items-center justify-center text-gray-400 p-2 text-center">
                      <svg className="w-10 h-10 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>
                      <span className="text-xs font-mono break-all line-clamp-2" title={photo.photo_url}>
                        {photo.photo_url.split('/').pop()}
                      </span>
                    </div>
                    {/* Кнопка удаления поверх фото */}
                    <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                      <button onClick={() => handlePhotoDelete(photo.id)} className="bg-red-600 text-white px-3 py-1 rounded text-sm hover:bg-red-700">
                        Удалить
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              {/* Форма загрузки */}
              {photoTarget.photos.length < 5 && (
                <div className="border-t border-gray-100 pt-4">
                  <label className="block text-sm font-semibold text-gray-700 mb-2">Загрузить новое фото</label>
                  <input 
                    type="file" 
                    accept="image/jpeg, image/png" 
                    className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 cursor-pointer border border-gray-200 rounded-lg" 
                    onChange={handlePhotoUpload} 
                  />
                  <p className="text-xs text-gray-500 mt-2">Принимаются только JPEG и PNG, максимум 5 штук.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};