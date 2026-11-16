// src/features/students/StudentCardPage.jsx (эскиз)
import { useParams } from 'react-router-dom';
import { StudentPhotos } from '../photos/StudentPhotos';

export const StudentCardPage = () => {
  const { studentId } = useParams();
  return (
    <div className="p-6 max-w-2xl mx-auto space-y-4">
      <h1 className="text-xl font-bold">Эталонные фото</h1>
      <StudentPhotos studentId={studentId} />
    </div>
  );
};