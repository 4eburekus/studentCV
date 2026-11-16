// src/features/attendance/mockData.js

// Статус ABSENT в данных НЕТ. Отсутствие = студента нет в журнале.
// Источник берём из is_manually_edited (поля source в API нет).

export const mockLessonsData = [
  {
    id: 1,
    lesson_date: '2026-11-16',      // дата ПАРЫ, не «сегодня»
    start_time: '08:30',
    end_time: '10:00',
    discipline: 'Управление проектами',
    group_number: '23-ИСбо-04',     // ВАЛИДНЫЙ формат: 2 цифры, 3–4 заглавных, 0–3 строчных, 2 цифры
    auditorium: 'А-301',
  },
  {
    id: 2,
    lesson_date: '2026-11-16',
    start_time: '10:15',
    end_time: '11:45',
    discipline: 'Веб-разработка',
    group_number: '23-ИСбо-04',
    auditorium: 'А-204',
  },
];

// Записи журнала (только те, кто пришёл / опоздал)
export const mockJournalRecords = [
  {
    id: 1,
    student_id: 1,
    full_name: 'Охламон Григорий Алексеевич',
    group_number: '23-ИСбо-04',
    captured_at: '2026-11-16T08:32:00+03:00', // timestamptz, с зоной
    status: 'LATE',
    delay_minutes: 2,
    is_manually_edited: false,
  },
  {
    id: 2,
    student_id: 2,
    full_name: 'Великий Павел',
    group_number: '23-ИСбо-04',
    captured_at: '2026-11-16T08:45:00+03:00',
    status: 'LATE',
    delay_minutes: 15,
    is_manually_edited: true,
  },
];

// Полный список группы — для вычисления «Отсутствовал»
export const mockGroupStudents = [
  { id: 1, full_name: 'Охламон Григорий Алексеевич', group_number: '23-ИСбо-04', is_active: true },
  { id: 2, full_name: 'Великий Павел', group_number: '23-ИСбо-04', is_active: true },
  { id: 3, full_name: 'Смирнов Даниил Дмитриевич', group_number: '23-ИСбо-04', is_active: true },
  { id: 4, full_name: 'Легендарный Никита', group_number: '23-ИСбо-04', is_active: true },
  { id: 5, full_name: 'Директоров Дмитрий', group_number: '23-ИСбо-04', is_active: true },
];