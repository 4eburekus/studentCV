import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { DataTable } from '../../components/ui/DataTable';

const mockLessons = [
  { id: 1, discipline_name: 'Веб-разработка', group_number: '23-ИСбо-04', start_time: '08:30', end_time: '10:00', room_number: 'А-301', is_stopped: false },
  { id: 2, discipline_name: 'Управление проектами', group_number: '23-ИСбо-04', start_time: '10:15', end_time: '11:45', room_number: 'А-204', is_stopped: true },
];

export const AdminSchedulePage = () => {
  const navigate = useNavigate();
  const [lessons, setLessons] = useState(mockLessons);

  const handleStop = (id) => {
    if (window.confirm('Досрочно завершить автоотметки? Всем студентам без статуса будет поставлен "Отсутствовал".')) {
      setLessons(prev => prev.map(l => l.id === id ? { ...l, is_stopped: true } : l));
      alert('Отметки завершены (имитация запроса к бэкенду)');
    }
  };

  const columns = [
    { key: 'discipline_name', label: 'Дисциплина' },
    { key: 'group_number', label: 'Группа' },
    { key: 'start_time', label: 'Время', render: (v, row) => `${v} - ${row.end_time}` },
    { key: 'room_number', label: 'Аудитория' },
    {
      key: 'actions', label: 'Действия', sortable: false,
      render: (_, row) => (
        <div className="flex gap-2">
          <button onClick={() => navigate(`/lessons/${row.id}`)} className="px-3 py-1 bg-blue-100 text-blue-700 rounded text-xs font-bold hover:bg-blue-200">
            Журнал
          </button>
          <button 
            onClick={() => handleStop(row.id)} 
            disabled={row.is_stopped}
            className={`px-3 py-1 rounded text-xs font-bold ${row.is_stopped ? 'bg-gray-100 text-gray-400' : 'bg-red-100 text-red-700 hover:bg-red-200'}`}
          >
            {row.is_stopped ? 'Завершено' : 'Стоп'}
          </button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-blue-900">Расписание и управление</h1>
      </div>
      <DataTable data={lessons} columns={columns} emptyMessage="Нет занятий на сегодня" />
    </div>
  );
};