// src/App.jsx
import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, Link } from 'react-router-dom';

// Ваши старые страницы
import { SchedulePage } from './features/schedule/SchedulePage';
import { LessonJournalPage } from './features/attendance/LessonJournalPage';
import { StudentsPage } from './features/students/StudentsPage';

// Новые страницы админки
import { AdminLayout } from './features/admin/AdminLayout';
import { TeachersPage } from './features/admin/TeachersPage';
import { LessonsPage } from './features/admin/LessonsPage';
import { DisciplinesPage } from './features/admin/DisciplinesPage';
import { AdminStudentsPage } from './features/admin/AdminStudentsPage';
import { AdminSchedulePage } from './features/admin/AdminSchedulePage';

import './App.css';

const Nav = () => (
  <nav className="bg-blue-900 text-white px-6 py-3 flex gap-6">
    <Link to="/schedule" className="hover:underline">Расписание</Link>
    <Link to="/students" className="hover:underline">Студенты</Link>
    <Link to="/admin/teachers" className="hover:underline">Админка</Link>
  </nav>
);

export default function App() {
  return (
    <BrowserRouter>
      <Nav />
      <Routes>
        {/* Корневой путь ведет на расписание */}
        <Route path="/" element={<Navigate to="/schedule" replace />} />
        
        {/* Ваши обычные страницы */}
        <Route path="/schedule" element={<SchedulePage />} />
        <Route path="/lessons/:lessonId" element={<LessonJournalPage />} />
        <Route path="/students" element={<StudentsPage />} />

        {/* Админ-панель с общим Layout (Sidebar) */}
        <Route path="/admin" element={<AdminLayout />}>
          {/* Если зайти просто на /admin, перекинет на /admin/schedule */}
          <Route index element={<Navigate to="schedule" replace />} />
          
          {/* Админские страницы */}
          <Route path="teachers" element={<TeachersPage />} />
          <Route path="lessons" element={<LessonsPage />} />
          
          {/* Сюда позже добавим остальные (disciplines, students, schedule) */}
          <Route path="schedule" element={<AdminSchedulePage />} />
          <Route path="disciplines" element={<DisciplinesPage />} />
          <Route path="students" element={<AdminStudentsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}