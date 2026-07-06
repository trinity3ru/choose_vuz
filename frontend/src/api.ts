// Клиент к backend. Все запросы идут на /api (в dev проксируется Vite на FastAPI).

import type { ApplicantsResponse, UniversityInfo } from "./types";

const BASE = "/api/v1/data";

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    let detail = `Ошибка ${response.status}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // тело не JSON — оставляем статусную строку
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function fetchUniversities(): Promise<UniversityInfo[]> {
  return getJson<UniversityInfo[]>(`${BASE}/universities`);
}

export function fetchApplicants(
  universityCode: string,
  majorCode: string,
): Promise<ApplicantsResponse> {
  const params = new URLSearchParams({
    university_code: universityCode,
    major_code: majorCode,
  });
  return getJson<ApplicantsResponse>(`${BASE}/applicants?${params.toString()}`);
}
