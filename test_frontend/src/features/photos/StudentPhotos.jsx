// src/features/photos/StudentPhotos.jsx
//
// Галерея эталонных фото студента. Раньше в этом файле лежал эскиз
// StudentCardPage, который импортировал сам себя (import { StudentPhotos }
// from '../photos/StudentPhotos') и рендерил себя же - то есть компонентом это
// не являлось. Теперь это настоящая галерея: загрузка, просмотр, замена,
// удаление и статус «ниже минимума».
//
// Почему картинки грузятся через fetch, а не через <img src>: браузер не
// прикладывает заголовок Authorization к запросу изображения, а все маршруты
// /api/v1 закрыты зависимостью (заглушка входа). Поэтому байты тянет клиент,
// а в <img> попадает blob URL, который освобождается при размонтировании.

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  deletePhoto,
  getPhotoBlob,
  getPhotos,
  releasePhotoUrl,
  replacePhoto,
  uploadPhoto,
} from '../../services/api';

const PhotoTile = ({ photo, onDelete, onReplace, onOpen }) => {
  const [url, setUrl] = useState(null);
  const [state, setState] = useState('loading'); // loading | ok | missing
  const fileRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = null;

    getPhotoBlob(photo.id)
      .then((u) => {
        if (cancelled) { releasePhotoUrl(u); return; }
        objectUrl = u;
        setUrl(u);
        setState('ok');
      })
      .catch((err) => {
        if (cancelled) return;
        // 410 — строка в БД есть, объекта в бакете нет: это поломка
        // хранилища, а не «фото отсутствует». Показываем различимо.
        setState(err?.status === 410 ? 'missing' : 'broken');
      });

    return () => {
      cancelled = true;
      // blob URL иначе живёт до перезагрузки страницы, удерживая память
      releasePhotoUrl(objectUrl);
    };
  }, [photo.id, photo.content_hash]);

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden group relative">
      {state === 'ok' && (
        <img
          src={url}
          alt="Эталон"
          onClick={() => onOpen?.(url)}
          className="w-full aspect-square object-cover cursor-zoom-in"
        />
      )}
      {state === 'loading' && (
        <div className="w-full aspect-square bg-slate-100 animate-pulse" />
      )}
      {state === 'missing' && (
        <div className="w-full aspect-square bg-amber-50 flex items-center justify-center p-2 text-center text-xs text-amber-800">
          Объект отсутствует в хранилище
        </div>
      )}
      {(state === 'broken') && (
        <div className="w-full aspect-square bg-red-50 flex items-center justify-center p-2 text-center text-xs text-red-700">
          Не удалось загрузить
        </div>
      )}

      <div className="absolute inset-0 bg-black/55 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col items-center justify-center gap-2">
        <button
          onClick={() => fileRef.current?.click()}
          className="bg-white text-gray-800 px-3 py-1 rounded text-xs font-semibold hover:bg-gray-100"
        >
          Заменить
        </button>
        <button
          onClick={() => onDelete(photo.id)}
          className="bg-red-600 text-white px-3 py-1 rounded text-xs font-semibold hover:bg-red-700"
        >
          Удалить
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/jpeg,image/png"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onReplace(photo.id, file);
            e.target.value = '';
          }}
        />
      </div>

      <div className="px-2 py-1 text-[10px] font-mono text-gray-400 truncate" title={photo.photo_url}>
        {photo.photo_url.split('/').pop()}
      </div>
    </div>
  );
};

export const StudentPhotos = ({ studentId, onChanged, compact = false }) => {
  const [photos, setPhotos] = useState([]);
  const [status, setStatus] = useState(null); // { min_photos, max_photos, status }
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(null);

  const load = useCallback(async () => {
    if (!studentId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getPhotos(studentId);
      setPhotos(data.items ?? []);
      setStatus({
        status: data.status,
        min_photos: data.min_photos,
        max_photos: data.max_photos,
      });
    } catch (e) {
      setError(e.detail || e.message || 'Не удалось загрузить фото');
    } finally {
      setLoading(false);
    }
  }, [studentId]);

  useEffect(() => { load(); }, [load]);

  const notifyChanged = () => { onChanged?.(); };

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await uploadPhoto(studentId, file);
      await load();
      notifyChanged();
    } catch (err) {
      // 422 приходит объектом { photos_total, max_photos } - читаемое
      // сообщение важнее кода: админ должен понять, что упёрся в лимит.
      const detail = err.detail;
      setError(
        typeof detail === 'string'
          ? detail
          : detail?.max_photos
            ? `Достигнут лимит: ${detail.photos_total} из ${detail.max_photos} фото`
            : 'Не удалось загрузить фото',
      );
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (photoId) => {
    if (!window.confirm('Удалить это эталонное фото?')) return;
    setBusy(true);
    try {
      await deletePhoto(photoId);
      await load();
      notifyChanged();
    } catch (err) {
      setError(err.detail || 'Не удалось удалить фото');
    } finally {
      setBusy(false);
    }
  };

  const handleReplace = async (photoId, file) => {
    setBusy(true);
    try {
      await replacePhoto(photoId, file);
      await load();
      notifyChanged();
    } catch (err) {
      setError(err.detail || 'Не удалось заменить фото');
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <div className="text-sm text-gray-500 py-3">Загрузка фото…</div>;

  const min = status?.min_photos ?? 1;
  const max = status?.max_photos ?? 5;
  const belowMinimum = photos.length < min;

  return (
    <div className="space-y-4">
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2 rounded">
          {error}
        </div>
      )}

      {belowMinimum && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 text-sm px-3 py-2 rounded flex items-center gap-2">
          <span>⚠</span>
          <span>
            Эталонов меньше минимума ({photos.length} из {min}) — студент не будет
            распознаваться системой.
          </span>
        </div>
      )}

      {photos.length === 0 ? (
        <div className="text-sm text-gray-500 py-3">Нет загруженных эталонов</div>
      ) : (
        <div className={compact ? 'grid grid-cols-3 gap-2' : 'grid grid-cols-2 md:grid-cols-3 gap-4'}>
          {photos.map((photo) => (
            <PhotoTile
              key={photo.id}
              photo={photo}
              onDelete={handleDelete}
              onReplace={handleReplace}
              onOpen={setPreview}
            />
          ))}
        </div>
      )}

      {photos.length < max && (
        <div className="border-t border-gray-100 pt-3">
          <label className="block text-sm font-semibold text-gray-700 mb-2">
            Добавить эталон ({photos.length} из {max})
          </label>
          <input
            type="file"
            accept="image/jpeg,image/png"
            disabled={busy}
            onChange={handleUpload}
            className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 cursor-pointer border border-gray-200 rounded-lg disabled:opacity-50"
          />
          <p className="text-xs text-gray-500 mt-2">Только JPEG и PNG, до {max} штук.</p>
        </div>
      )}

      {preview && (
        <div
          className="fixed inset-0 bg-black/80 flex items-center justify-center z-[60] p-6 cursor-zoom-out"
          onClick={() => setPreview(null)}
        >
          <img src={preview} alt="Эталон" className="max-h-full max-w-full rounded-lg" />
        </div>
      )}
    </div>
  );
};
