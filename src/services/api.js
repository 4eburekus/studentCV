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

// ---------- Lessons ----------
export const getLessons = ({ discipline_id, date, page = 1, limit = 50 } = {}) => {
  const p = new URLSearchParams();
  if (discipline_id) p.set('discipline_id', discipline_id);
  if (date) p.set('date', date); // YYYY-MM-DD
  p.set('page', page);
  p.set('limit', limit);
  return request(`/lessons?${p}`);
};

// ---------- Attendance ----------
export const postAttendanceEvent = (body) =>
  request('/attendance/events', { method: 'POST', body });
  // body: { lesson_id, student_id, captured_at (ISO с зоной), frame_object_key }
  // Ответ: { record, outcome, lesson_start, delay_minutes }
  // outcome: recorded | kept_earlier_entry | kept_manual_edit | ignored_after_lesson_end

export const getJournal = (lessonId) =>
  request(`/attendance/journal?lesson_id=${lessonId}`);

// ---------- Health ----------
export const getHealth = () => fetch('http://127.0.0.1:8000/healthz').then(r => r.json());