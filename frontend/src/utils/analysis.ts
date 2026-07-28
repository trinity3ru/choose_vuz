// Расчёты для анализа: фильтрация, средний балл, проходной балл, гистограмма.

import type { Applicant } from "../types";

export const BIN_SIZE = 10;

export interface HistogramBin {
  // Левая граница интервала (напр. 180 → интервал 180–189).
  start: number;
  // Подпись интервала для оси X.
  label: string;
  count: number;
}

// Фильтр по согласию на зачисление:
// all — все заявления, with — только с согласием, without — только без него.
export type AgreementFilter = "all" | "with" | "without";

// Оставить заявления с указанными приоритетами и нужным статусом согласия.
// Пустой набор приоритетов = показать все приоритеты.
// Заявления с нулевым баллом (нет результатов ЕГЭ) исключаются всегда,
// иначе они искажают средний и проходной балл.
export function filterApplicants(
  applicants: Applicant[],
  priorities: Set<number>,
  agreement: AgreementFilter = "all",
): Applicant[] {
  let rows = applicants.filter(
    (a) => a.total_score !== null && a.total_score > 0,
  );
  if (priorities.size > 0) {
    rows = rows.filter((a) => a.priority !== null && priorities.has(a.priority));
  }
  if (agreement === "with") rows = rows.filter((a) => a.has_agreement);
  if (agreement === "without") rows = rows.filter((a) => !a.has_agreement);
  return rows;
}

// Сколько заявлений с поданным согласием на зачисление.
export function countWithAgreement(applicants: Applicant[]): number {
  return applicants.filter((a) => a.has_agreement).length;
}

// Все приоритеты, встречающиеся в данных (для чекбоксов), по возрастанию.
export function availablePriorities(applicants: Applicant[]): number[] {
  const set = new Set<number>();
  for (const a of applicants) {
    if (a.priority !== null) set.add(a.priority);
  }
  return [...set].sort((x, y) => x - y);
}

// Средний балл по отфильтрованным заявлениям (null, если пусто).
export function averageScore(applicants: Applicant[]): number | null {
  const scores = applicants
    .map((a) => a.total_score)
    .filter((s): s is number => s !== null);
  if (scores.length === 0) return null;
  const sum = scores.reduce((acc, s) => acc + s, 0);
  return Math.round(sum / scores.length);
}

// Проходной балл по числу мест: ранжируем по баллу убыв., берём балл
// абитуриента на последнем бюджетном месте. Это оценочная «отсечка» —
// без учёта межнаправленческого перераспределения по приоритетам.
export function cutoffScore(
  applicants: Applicant[],
  places: number | null,
): number | null {
  if (!places || places <= 0) return null;
  const scores = applicants
    .map((a) => a.total_score)
    .filter((s): s is number => s !== null)
    .sort((x, y) => y - x);
  if (scores.length === 0) return null;
  // Если заявлений меньше, чем мест, проходной = минимальный балл в списке.
  const index = Math.min(places, scores.length) - 1;
  return scores[index];
}

// Построить бины гистограммы фиксированного размера BIN_SIZE.
export function buildHistogram(applicants: Applicant[]): HistogramBin[] {
  const scores = applicants
    .map((a) => a.total_score)
    .filter((s): s is number => s !== null);
  if (scores.length === 0) return [];

  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const firstStart = Math.floor(min / BIN_SIZE) * BIN_SIZE;
  const lastStart = Math.floor(max / BIN_SIZE) * BIN_SIZE;

  const bins: HistogramBin[] = [];
  for (let start = firstStart; start <= lastStart; start += BIN_SIZE) {
    bins.push({
      start,
      label: `${start}–${start + BIN_SIZE - 1}`,
      count: 0,
    });
  }
  for (const score of scores) {
    const idx = Math.floor((score - firstStart) / BIN_SIZE);
    bins[idx].count += 1;
  }
  return bins;
}

// Ранг балла в отсортированном по убыванию списке (1 = самый высокий).
// Возвращает позицию, на которую встал бы данный балл среди заявлений.
export function rankOfScore(
  applicants: Applicant[],
  score: number,
): number {
  const scores = applicants
    .map((a) => a.total_score)
    .filter((s): s is number => s !== null);
  // Сколько заявлений строго выше нашего балла, +1 — наша позиция.
  const above = scores.filter((s) => s > score).length;
  return above + 1;
}
