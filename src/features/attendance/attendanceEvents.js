// src/features/attendance/attendanceEvents.js
import { postAttendanceEvent } from '../../services/api';

// Возвращает { record, outcome, lesson_start, delay_minutes }
// outcome читать ВСЕГДА — код ответа (200/201) говорит лишь «изменили/не изменили»
export async function sendAttendanceEvent(payload) {
  const res = await postAttendanceEvent(payload);
  return res;
}

// Человекочитаемая подпись исхода — для тостов/баннеров
export const OUTCOME_TEXT = {
  recorded:                'Отметка создана/обновлена',
  kept_earlier_entry:      'Сохранён более ранний вход',
  kept_manual_edit:        'Журнал правил преподаватель — событие отброшено',
  ignored_after_lesson_end:'Пара закончилась — запись не создана',
};

export function outcomeMessage(res) {
  if (!res) return 'Пустой ответ';
  if (res.outcome === 'ignored_after_lesson_end') {
    return OUTCOME_TEXT.ignored_after_lesson_end; // record: null
  }
  return OUTCOME_TEXT[res.outcome] ?? `Неизвестный исход: ${res.outcome}`;
}