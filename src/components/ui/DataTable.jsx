// src/components/ui/DataTable.jsx
import React, { useState, useMemo } from 'react';

export const DataTable = ({ data, columns, emptyMessage = "Нет данных", loading = false }) => {
  const [sortConfig, setSortConfig] = useState({ key: null, direction: 'asc' });

  const sortedData = useMemo(() => {
    let sortableItems = [...data];
    if (sortConfig.key !== null) {
      sortableItems.sort((a, b) => {
        const valA = typeof a[sortConfig.key] === 'string' ? a[sortConfig.key].toLowerCase() : a[sortConfig.key];
        const valB = typeof b[sortConfig.key] === 'string' ? b[sortConfig.key].toLowerCase() : b[sortConfig.key];

        if (valA == null && valB == null) return 0;
        if (valA == null) return 1;   // пустые — в конец
        if (valB == null) return -1;

        if (valA < valB) return sortConfig.direction === 'asc' ? -1 : 1;
        if (valA > valB) return sortConfig.direction === 'asc' ? 1 : -1;
        return 0;
      });
    }
    return sortableItems;
  }, [data, sortConfig]);

  const requestSort = (key) => {
    let direction = 'asc';
    if (sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc';
    }
    setSortConfig({ key, direction });
  };

  return (
    <div className="w-full bg-white rounded-xl shadow-sm border border-blue-100 overflow-hidden">
      <div className="flex justify-between items-center p-4 border-b border-gray-100 bg-gray-50">
        <span className="text-sm text-gray-500 font-medium">
          {sortConfig.key ? 'Таблица отсортирована' : 'Исходный порядок'}
        </span>
        <button
          onClick={() => setSortConfig({ key: null, direction: 'asc' })}
          disabled={!sortConfig.key}
          className="text-sm text-blue-600 hover:text-blue-800 disabled:opacity-50 disabled:cursor-not-allowed font-semibold transition-colors"
        >
          Сбросить сортировку
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left text-gray-600">
          <thead className="text-xs text-white uppercase bg-blue-800">
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={`px-4 py-4 font-semibold whitespace-nowrap tracking-wider select-none ${col.sortable !== false ? 'cursor-pointer hover:bg-blue-700 transition-colors group' : ''}`}
                  onClick={() => col.sortable !== false && requestSort(col.key)}
                >
                  <div className="flex items-center gap-2">
                    {col.label}
                    {col.sortable !== false && (
                      <span className={`text-[10px] ${sortConfig.key === col.key ? 'opacity-100' : 'opacity-0 group-hover:opacity-50'}`}>
                        {sortConfig.key === col.key && sortConfig.direction === 'desc' ? '▼' : '▲'}
                      </span>
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            {loading ? (
              <tr>
                <td colSpan={columns.length} className="px-6 py-12 text-center text-gray-500">
                  Загрузка…
                </td>
              </tr>
            ) : sortedData.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-6 py-12 text-center text-gray-500">
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              sortedData.map((row, index) => (
                <tr
                  key={row.student_id ?? row.id}
                  className={`border-b border-blue-50 hover:bg-blue-50/50 transition-colors ${index % 2 === 0 ? 'bg-white' : 'bg-slate-50'}`}
                >
                  {columns.map((col) => (
                    <td
                      key={`${row.student_id ?? row.id}-${col.key}`}
                      className="px-4 py-3 whitespace-nowrap text-gray-700 font-medium"
                    >
                      {col.render ? col.render(row[col.key], row) : row[col.key]}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};