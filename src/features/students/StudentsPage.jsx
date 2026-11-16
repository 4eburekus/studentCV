// src/features/students/StudentsPage.jsx
import React, { useEffect, useState, useCallback } from 'react';
import { DataTable } from '../../components/ui/DataTable';
import { getStudents, deactivateStudent } from '../../services/api';

export const StudentsPage = () => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getStudents({ is_active: true, limit: 500 }) // дефолт — только активные
      .then((res) => setRows(res?.items ?? res ?? []))
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const onDeactivate = async (row) => {
    if (!window.confirm('Деактивировать студента? Он останется в базе (is_active=false) и скроется из списка. Журнал сохранится.')) return;
    try {
      await deactivateStudent(row.id); // DELETE /students/{id} — МЯГКОЕ удаление
      load();
    } catch (ex) {
      if (ex.status === 409) setError('Конфликт состояния (409)');
      else if (ex.status === 404) setError('Студент не найден (404)');
      else setError(`Ошибка ${ex.status}`);
    }
  };

  const columns = [
    { key: 'full_name', label: 'ФИО', render: (v) => <span className="font-semibold text-blue-900">{v}</span> },
    { key: 'group_number', label: 'Группа' },
    {
      key: 'actions', label: 'Действие', sortable: false,
      render: (_, row) => (
        <button
          onClick={() => onDeactivate(row)}
          className="text-xs font-semibold text-red-600 hover:text-red-800 hover:underline"
        >
          Деактивировать
        </button>
      ),
    },
  ];

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      <h1 className="text-2xl font-bold text-blue-900">Студенты</h1>
      {error && <div className="text-red-600 text-sm">{error}</div>}
      <DataTable data={rows} columns={columns} loading={loading} emptyMessage="Нет активных студентов" />
    </div>
  );
};