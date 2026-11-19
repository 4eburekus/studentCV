// src/services/api.js
const BASE_URL = 'http://127.0.0.1:8000/api/v1';

// TODO: заменить на реальный токен, когда появится вход (срез авторизации)
const getToken = () => localStorage.getItem('token') || 'dev';

export class ApiError extends Error {
  constructor(status, detail, raw) {
    super(typeof detail === 'string' ? detail : 'Ошибка API');
    this.status = status;
    this.detail = detail; // строка | объект | массив (422)
    this.raw = raw;
  }
}

async function request(path, { method = 'GET', body, isForm = false } = {}) {
  const headers = { Authorization: `Bearer ${getToken()}` };
  if (!isForm && body !== undefined) headers['Content-Type'] = 'application/json';

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: isForm ? body : body !== undefined ? JSON.stringify(body) : undefined,
  });

  // 204 и пустое тело
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;

  if (!res.ok) {
    // 401 — заглушка авторизации: обязаны обрабатывать с первого дня
    if (res.status === 401) {
      // TODO: редирект на /login, когда появится реальный вход
      console.warn('401 Unauthorized — нет заголовка Authorization');
    }
    throw new ApiError(res.status, data?.detail ?? data, data);
  }
  return data;
}

// ---------- Students ----------
export const getStudents = ({ group, q, is_active, page = 1, limit = 50 } = {}) => {
  const p = new URLSearchParams();
  if (group) p.set('group', group);          // точное совпадение
  if (q) p.set('q', q);                       // подстрока ФИО/группы
  if (is_active !== undefined) p.set('is_active', String(is_active)); // дефолт — только активные
  p.set('page', page);
  p.set('limit', limit);                      // 1..500
  return request(`/students?${p}`);
};

export const getStudent = (id) => request(`/students/${id}`);

export const createStudent = (body) =>
  request('/students', { method: 'POST', body }); // { full_name, group_number }

export const patchStudent = (id, body) =>
  request(`/students/${id}`, { method: 'PATCH', body });

// МЯГКОЕ удаление: is_active=false, журнал сохраняется
export const deactivateStudent = (id) =>
  request(`/students/${id}`, { method: 'DELETE' });

// ---------- Photos ----------
export const getPhotos = (studentId) => request(`/students/${studentId}/photos`);

export const uploadPhoto = (studentId, file) => {
  const fd = new FormData();
  fd.append('file', file); // поле обязательно называется file
  return request(`/students/${studentId}/photos`, { method: 'POST', body: fd, isForm: true });
  // 415 — не jpeg/png; 422 — >5 фото: detail = { photos_total, max_photos }
};

export const deletePhoto = (id) => request(`/photos/${id}`, { method: 'DELETE' });

// ---------- Photos: контент ----------
// <img src> здесь не годится: браузер не прикладывает заголовок Authorization
// к запросу картинки, а API закрыт зависимостью (заглушка входа). Поэтому
// байты тянем тем же клиентом и отдаём blob URL. Отзывать его должен тот, кто
// создал: см. releasePhotoUrl.
export const getPhotoBlob = async (photoId) => {
  const res = await fetch(`${BASE_URL}/photos/${photoId}/content`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try { detail = JSON.parse(text)?.detail ?? text; } catch { /* не JSON */ }
    throw new ApiError(res.status, detail, text);
  }
  return URL.createObjectURL(await res.blob());
};

export const releasePhotoUrl = (url) => { if (url) URL.revokeObjectURL(url); };

export const replacePhoto = (photoId, file) => {
  const fd = new FormData();
  fd.append('file', file);
  return request(`/photos/${photoId}/content`, { method: 'PUT', body: fd, isForm: true });
};

// ---------- Teachers ----------
export const getTeachers = ({ q, page = 1, limit = 50 } = {}) => {
  const p = new URLSearchParams();
  if (q) p.set('q', q);
  p.set('page', page);
  p.set('limit', limit);
  return request(`/teachers?${p}`);
};

export const getTeacher = (id) => request(`/teachers/${id}`);

export const createTeacher = (body) =>
  request('/teachers', { method: 'POST', body });
  // body: { full_name, login, password }  (password >= 8)
  // 409 — логин занят

export const patchTeacher = (id, body) =>
  request(`/teachers/${id}`, { method: 'PATCH', body });
  // body: { full_name?, login? } — пароля здесь НЕТ намеренно

export const setTeacherPassword = (id, password) =>
  request(`/teachers/${id}/password`, { method: 'PUT', body: { password } });

// 409 — за преподавателем числятся дисциплины
export const deleteTeacher = (id) => request(`/teachers/${id}`, { method: 'DELETE' });

// ---------- Disciplines ----------
export const getDisciplines = ({ teacher_id, q, page = 1, limit = 50 } = {}) => {
  const p = new URLSearchParams();
  if (teacher_id) p.set('teacher_id', teacher_id);
  if (q) p.set('q', q);
  p.set('page', page);
  p.set('limit', limit);
  return request(`/disciplines?${p}`);
};

export const createDiscipline = (body) =>
  request('/disciplines', { method: 'POST', body }); // { name, teacher_id }

export const patchDiscipline = (id, body) =>
  request(`/disciplines/${id}`, { method: 'PATCH', body });

// 409 — у дисциплины есть пары с записями журнала
export const deleteDiscipline = (id) => request(`/disciplines/${id}`, { method: 'DELETE' });

// ---------- Lessons ----------
export const getLessons = ({ discipline_id, date, group_number, page = 1, limit = 50 } = {}) => {
  const p = new URLSearchParams();
  if (discipline_id) p.set('discipline_id', discipline_id);
  if (date) p.set('date', date); // YYYY-MM-DD
  if (group_number) p.set('group_number', group_number);
  p.set('page', page);
  p.set('limit', limit);
  return request(`/lessons?${p}`);
};

export const getLesson = (id) => request(`/lessons/${id}`);

export const createLesson = (body) =>
  request('/lessons', { method: 'POST', body });
  // body: { discipline_id, group_number, lesson_date, start_time, end_time, room_number? }
  // 409 — слот занят (дисциплина+группа+дата+начало); 422 — формат группы или окно

export const patchLesson = (id, body) =>
  request(`/lessons/${id}`, { method: 'PATCH', body });
  // у ЗАКРЫТОЙ пары нельзя менять группу/дату/время (409), аудиторию — можно

// 409 — у пары есть записи журнала
export const deleteLesson = (id) => request(`/lessons/${id}`, { method: 'DELETE' });

// ---------- Attendance: закрытие пары ----------
export const closeLesson = (lessonId) =>
  request(`/attendance/lessons/${lessonId}/close`, { method: 'POST' });
  // { absent_created, already_recorded, closed_at, was_already_closed }

// ---------- Attendance ----------
export const postAttendanceEvent = (body) =>
  request('/attendance/events', { method: 'POST', body });
  // body: { lesson_id, student_id, captured_at (ISO с зоной), frame_object_key }
  // Ответ: { record, outcome, lesson_start, delay_minutes }
  // outcome: recorded | kept_earlier_entry | kept_manual_edit | ignored_after_lesson_end

export const getJournal = (lessonId) =>
  request(`/attendance/journal?lesson_id=${lessonId}`);

// ---------- Attendance: ручная правка (задача 3.3.1) ----------
// body: { status, entry_time? }. Поля delay_minutes здесь НЕТ намеренно:
// сервер считает опоздание сам из времени, иначе журнал мог бы показать
// «пришёл в 9:15» и «опоздал на 5 минут» одновременно.
// entry_time обязателен для PRESENT/LATE и игнорируется для ABSENT.
// Время ПОСЛЕ конца пары разрешено (для того правка и нужна), время в другой
// день - 422. Ответ: { record, delay_minutes, edited_at }.
export const patchAttendanceRecord = (recordId, body) =>
  request(`/attendance/records/${recordId}`, { method: 'PATCH', body });

// Ручная отметка по паре и студенту: создаёт запись, если её нет.
// Нужен именно этот вход, а не только PATCH: пока пара не закрыта, у
// студента без отметки нет строки, а значит нет и record_id.
// body: { lesson_id, student_id, status, entry_time? }
export const setAttendanceRecord = (body) =>
  request('/attendance/records', { method: 'POST', body });

// ---------- Health ----------
export const getHealth = () => fetch('http://127.0.0.1:8000/healthz').then(r => r.json());