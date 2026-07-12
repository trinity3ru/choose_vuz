// Клиент к backend.
//
// База URL берётся из VITE_API_URL (задаётся при сборке):
// - dev: переменная пуста -> запросы идут на тот же origin, Vite проксирует
//   /api на FastAPI (см. vite.config.ts);
// - prod: VITE_API_URL=https://api.vuzfinder.ru (см. корневой .env.example).

import type {
  ApplicantsResponse,
  ParserHealthResponse,
  UniversityInfo,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");

const DATA_BASE = `${API_BASE}/api/v1/data`;
const PARSER_BASE = `${API_BASE}/api/v1/parser`;

/**
 * API временно недоступно: сеть не отвечает или сервер отдаёт 5xx.
 * UI показывает для этого случая отдельный экран с кнопкой «Повторить».
 */
export class ApiUnavailableError extends Error {
  constructor(message = "API временно недоступно") {
    super(message);
    this.name = "ApiUnavailableError";
  }
}

async function getJson<T>(url: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url);
  } catch {
    // fetch кидает TypeError при сетевой ошибке (нет соединения, DNS, CORS).
    throw new ApiUnavailableError();
  }

  if (response.status >= 500) {
    throw new ApiUnavailableError(`Сервер недоступен (${response.status})`);
  }

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
  return getJson<UniversityInfo[]>(`${DATA_BASE}/universities`);
}

export function fetchApplicants(
  universityCode: string,
  majorCode: string,
): Promise<ApplicantsResponse> {
  const params = new URLSearchParams({
    university_code: universityCode,
    major_code: majorCode,
  });
  return getJson<ApplicantsResponse>(`${DATA_BASE}/applicants?${params.toString()}`);
}

export function fetchParserHealth(): Promise<ParserHealthResponse> {
  return getJson<ParserHealthResponse>(`${PARSER_BASE}/health`);
}
