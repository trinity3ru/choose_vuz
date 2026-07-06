// Главный экран: фильтры слева, гистограмма и вывод справа.

import { useEffect, useMemo, useState } from "react";

import { fetchUniversities } from "./api";
import { Filters } from "./components/Filters";
import { HistogramChart } from "./components/HistogramChart";
import { Summary } from "./components/Summary";
import { useApplicantData } from "./hooks/useApplicantData";
import type { UniversityInfo } from "./types";
import {
  availablePriorities,
  averageScore,
  buildHistogram,
  cutoffScore,
  filterByPriorities,
  rankOfScore,
} from "./utils/analysis";

function formatSnapshotDate(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function App() {
  const [universities, setUniversities] = useState<UniversityInfo[]>([]);
  const [uniError, setUniError] = useState<string | null>(null);
  const [uniLoading, setUniLoading] = useState(true);

  const [selectedUniversity, setSelectedUniversity] = useState<string | null>(
    null,
  );
  const [selectedMajor, setSelectedMajor] = useState<string | null>(null);
  const [selectedPriorities, setSelectedPriorities] = useState<Set<number>>(
    new Set(),
  );
  const [userScore, setUserScore] = useState<number | null>(null);

  // Загрузка списка вузов при старте.
  useEffect(() => {
    fetchUniversities()
      .then((list) => {
        setUniversities(list);
        setUniLoading(false);
        if (list.length > 0) {
          setSelectedUniversity(list[0].code);
          if (list[0].majors.length > 0) {
            setSelectedMajor(list[0].majors[0].code);
          }
        }
      })
      .catch((err: Error) => {
        setUniError(err.message);
        setUniLoading(false);
      });
  }, []);

  const { data, loading, error } = useApplicantData(
    selectedUniversity,
    selectedMajor,
  );

  const applicants = data?.applicants ?? [];

  const priorities = useMemo(
    () => availablePriorities(applicants),
    [applicants],
  );

  const filtered = useMemo(
    () => filterByPriorities(applicants, selectedPriorities),
    [applicants, selectedPriorities],
  );

  const bins = useMemo(() => buildHistogram(filtered), [filtered]);
  const avg = useMemo(() => averageScore(filtered), [filtered]);
  const cutoff = useMemo(
    () => cutoffScore(filtered, data?.stats?.places ?? null),
    [filtered, data],
  );
  const userRank = useMemo(
    () => (userScore !== null ? rankOfScore(filtered, userScore) : null),
    [filtered, userScore],
  );

  function handleUniversityChange(code: string) {
    setSelectedUniversity(code);
    const uni = universities.find((u) => u.code === code);
    setSelectedMajor(uni?.majors[0]?.code ?? null);
    setSelectedPriorities(new Set());
  }

  function handleMajorChange(code: string) {
    setSelectedMajor(code);
    setSelectedPriorities(new Set());
  }

  function togglePriority(priority: number) {
    setSelectedPriorities((prev) => {
      const next = new Set(prev);
      if (next.has(priority)) next.delete(priority);
      else next.add(priority);
      return next;
    });
  }

  const priorityNote =
    selectedPriorities.size === 0
      ? "все приоритеты"
      : `приоритеты ${[...selectedPriorities].sort((a, b) => a - b).join(", ")}`;

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header-inner">
          <div>
            <p className="eyebrow">СПбПУ · Бакалавриат 2026</p>
            <h1>Оценка шансов поступления</h1>
          </div>
          {data?.snapshot && (
            <div className="snapshot-badge" title="Последний успешный снимок">
              Данные на {formatSnapshotDate(data.snapshot.created_at)}
            </div>
          )}
        </div>
      </header>

      <main className="layout">
        {uniLoading ? (
          <div className="panel state-note">Загрузка списка направлений…</div>
        ) : uniError ? (
          <div className="panel state-note state-error">
            Не удалось загрузить данные: {uniError}
          </div>
        ) : universities.length === 0 ? (
          <div className="panel state-note">
            Пока нет спарсенных данных. Запустите парсер и обновите страницу.
          </div>
        ) : (
          <>
            <Filters
              universities={universities}
              selectedUniversity={selectedUniversity}
              selectedMajor={selectedMajor}
              availablePriorities={priorities}
              selectedPriorities={selectedPriorities}
              userScore={userScore}
              onUniversityChange={handleUniversityChange}
              onMajorChange={handleMajorChange}
              onTogglePriority={togglePriority}
              onResetPriorities={() => setSelectedPriorities(new Set())}
              onUserScoreChange={setUserScore}
            />

            <div className="content">
              {loading ? (
                <div className="panel state-note">Загрузка заявлений…</div>
              ) : error ? (
                <div className="panel state-note state-error">{error}</div>
              ) : data ? (
                <>
                  <Summary
                    averageScore={avg}
                    cutoffScore={cutoff}
                    userScore={userScore}
                    userRank={userRank}
                    totalApplicants={filtered.length}
                    stats={data.stats}
                  />

                  <div className="panel">
                    <div className="panel-head">
                      <h2>{data.major.name}</h2>
                      <span className="panel-sub">
                        {data.major.code} · {filtered.length} заявлений ·{" "}
                        {priorityNote}
                      </span>
                    </div>
                    <HistogramChart
                      bins={bins}
                      averageScore={avg}
                      cutoffScore={cutoff}
                      userScore={userScore}
                    />
                  </div>
                </>
              ) : null}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
