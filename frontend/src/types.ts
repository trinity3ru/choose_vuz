// Типы данных, приходящих с backend (эндпоинты /api/v1/data/*).

export interface MajorInfo {
  code: string;
  name: string;
}

export interface UniversityInfo {
  code: string;
  name: string;
  majors: MajorInfo[];
}

export interface Applicant {
  total_score: number | null;
  exam_score: number | null;
  priority: number | null;
  has_agreement: boolean;
  is_bvi: boolean;
}

export interface MajorStats {
  places: number | null;
  applications: number | null;
  agreements: number | null;
  list_formed_at: string | null;
}

export interface SnapshotInfo {
  id: string;
  created_at: string;
  status: string;
}

export interface ApplicantsResponse {
  snapshot: SnapshotInfo;
  major: MajorInfo;
  stats: MajorStats | null;
  applicants: Applicant[];
}
