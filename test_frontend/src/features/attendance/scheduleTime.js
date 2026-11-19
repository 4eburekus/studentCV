// src/features/attendance/scheduleTime.js
//
// Единый способ показывать и собирать «время расписания».
//
// Почему это отдельный модуль, а не toLocaleTimeString на месте.
// Backend трактует приходящее naive-время как UTC (см. _as_aware в
// app/services/attendance.py) и строит границы пары из naive Date/Time
// расписания. То есть «08:30 - начало пары» и «08:37 - вход» живут в одной
// условной зоне, и зона эта - UTC.
//
// Обычный new Date(iso).toLocaleTimeString('ru-RU') переводит момент в зону
// браузера. На машине с +03:00 вход 08:37 показывается как 11:37, а опоздание
// остаётся 7 минут: журнал начинает противоречить сам себе. Хуже того, форма
// правки, отправившая «11:37» обратно, сдвинула бы отметку на три часа - то
// есть каждое сохранение портило бы данные.
//
// Поэтому здесь всё читается и собирается ЧЕРЕЗ UTC-геттеры, без перевода в
// локальную зону.

/** HH:MM из ISO-строки, без перевода в локальную зону. */
export const scheduleHM = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return pad2(d.getUTCHours()) + ':' + pad2(d.getUTCMinutes());
};

/** HH:MM:SS - полная точность. Нужна для value у <input type="time" step="1">:
 * усечение до минут при открытии формы тихо сдвигало бы опоздание на минуту
 * при каждом сохранении. */
export const scheduleHMS = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return scheduleHM(iso) + ':' + pad2(d.getUTCSeconds());
};

/** Момент «дата + HH:MM(:SS) расписания» как ISO в UTC - то, что ждёт API. */
export const parseScheduleTime = (dateStr, timeStr) => {
  if (!dateStr || !timeStr) return null;
  const parts = timeStr.split(':');
  if (parts.length < 2) return null;
  const [h, m, s = '00'] = parts;
  // Секунды обязательны: без них часть клиентов отдаёт "08:37", и время
  // становится неотличимым от "08:37:00" только по длине строки.
  return `${dateStr}T${pad2(h)}:${pad2(m)}:${pad2(s)}+00:00`;
};

/**
 * Минуты опоздания от начала пары - ровно как считает сервер:
 * ceil от секунд/60, не меньше нуля (см. delay_minutes_from).
 *
 * Дублировать формулу на фронте приходится, чтобы показать преподавателю
 * результат ДО сохранения: сервер пересчитывает задержку сам и принимает
 * только время, поэтому «предпросмотр» обязан совпадать с тем, что ляжет в
 * журнал. Расхождение здесь - самый заметный баг этого экрана.
 */
export const previewDelayMinutes = (dateStr, startHM, entryIso) => {
  if (!entryIso) return null;
  const start = new Date(`${dateStr}T${pad2(startHM.split(':')[0])}:${pad2(startHM.split(':')[1])}:00+00:00`);
  const entry = new Date(entryIso);
  if (Number.isNaN(start.getTime()) || Number.isNaN(entry.getTime())) return null;
  return Math.max(0, Math.ceil((entry - start) / 60000));
};

/** Человекочитаемая дата+время того же момента, без перевода зоны. */
export const formatScheduleMoment = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const day = pad2(d.getUTCDate());
  const month = pad2(d.getUTCMonth() + 1);
  return `${day}.${month}.${d.getUTCFullYear()} ${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}`;
};

function pad2(v) {
  return String(v).padStart(2, '0');
}
