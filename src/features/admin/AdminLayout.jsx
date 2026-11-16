import React from 'react';
import { NavLink, Outlet } from 'react-router-dom';

const menuItems = [
  { path: '/admin/schedule', label: 'Расписание (Журнал)' },
  { path: '/admin/teachers', label: 'Преподаватели' },
  { path: '/admin/disciplines', label: 'Дисциплины' },
  { path: '/admin/lessons', label: 'Занятия' },
  { path: '/admin/students', label: 'Студенты' },
];

export const AdminLayout = () => {
  return (
    <div className="flex min-h-screen bg-slate-100 font-sans">
      {/* Sidebar */}
      <aside className="w-64 bg-blue-900 text-white flex flex-col shadow-lg z-10">
        <div className="p-6 text-xl font-bold border-b border-blue-800">
          Админ-панель
        </div>
        <nav className="flex-1 py-4">
          <ul className="space-y-1">
            {menuItems.map((item) => (
              <li key={item.path}>
                <NavLink
                  to={item.path}
                  className={({ isActive }) =>
                    `block px-6 py-3 text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-blue-800 border-l-4 border-white'
                        : 'hover:bg-blue-800/50 border-l-4 border-transparent'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="p-4 border-t border-blue-800 text-xs text-blue-300">
          StudentCV Admin v1.0
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 p-8 overflow-y-auto h-screen">
        <Outlet /> {/* Сюда будут рендериться страницы админки */}
      </main>
    </div>
  );
};