// Главный экран: фильтры слева, гистограмма и вывод справа.

import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiUnavailableError, fetchUniversities } from "./api";
import { Filters } from "./components/Filters";
import { HistogramChart } from "./components/HistogramChart";
import { Summary } from "./components/Summary";
import { useApplicantData } from "./hooks/useApplicantData";
import { useParserHealth } from "./hooks/useParserHealth";
import type { ParserHealthUniversity, UniversityInfo } from "./types";
import type { AgreementFilter } from "./utils/analysis";
import {
  availablePriorities,
  averageScore,
  buildHistogram,
  countWithAgreement,
  cutoffScore,
  filterApplicants,
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

/** Текст свежести данных вуза: «обновлено N ч назад» / предупреждение. */
function freshnessLabel(health: ParserHealthUniversity): string {
  if (health.age_hours === null) return "Данные ещё не собирались";
  if (health.age_hours < 1) return "Обновлено меньше часа назад";
  const hours = Math.round(health.age_hours);
  return `Обновлено ${hours} ч назад`;
}

export default function App() {
  const [universities, setUniversities] = useState<UniversityInfo[]>([]);
  const [uniError, setUniError] = useState<string | null>(null);
  const [uniUnavailable, setUniUnavailable] = useState(false);
  const [uniLoading, setUniLoading] = useState(true);

  const [selectedUniversity, setSelectedUniversity] = useState<string | null>(
    null,
  );
  const [selectedMajor, setSelectedMajor] = useState<string | null>(null);
  const [selectedPriorities, setSelectedPriorities] = useState<Set<number>>(
    new Set(),
  );
  const [agreementFilter, setAgreementFilter] =
    useState<AgreementFilter>("all");
  const [userScore, setUserScore] = useState<number | null>(null);

  const health = useParserHealth();

  // Загрузка списка вузов (и повтор по кнопке «Повторить»).
  const loadUniversities = useCallback(() => {
    setUniLoading(true);
    setUniError(null);
    setUniUnavailable(false);
    fetchUniversities()
      .then((list) => {
        setUniversities(list);
        setUniLoading(false);
        if (list.length > 0) {
          setSelectedUniversity((prev) => prev ?? list[0].code);
          setSelectedMajor((prev) => prev ?? list[0].majors[0]?.code ?? null);
        }
      })
      .catch((err: Error) => {
        setUniError(err.message);
        setUniUnavailable(err instanceof ApiUnavailableError);
        setUniLoading(false);
      });
  }, []);

  useEffect(() => {
    loadUniversities();
  }, [loadUniversities]);

  function retryAll() {
    loadUniversities();
    health.reload();
  }

  const { data, loading, error, unavailable, retry } = useApplicantData(
    selectedUniversity,
    selectedMajor,
  );

  const selectedHealth = selectedUniversity
    ? health.byCode.get(selectedUniversity)
    : undefined;

  const applicants = data?.applicants ?? [];

  const priorities = useMemo(
    () => availablePriorities(applicants),
    [applicants],
  );

  const filtered = useMemo(
    () => filterApplicants(applicants, selectedPriorities, agreementFilter),
    [applicants, selectedPriorities, agreementFilter],
  );

  // Согласия считаем до фильтра по согласию, но с учётом приоритетов —
  // иначе в режиме «с согласием» подсказка всегда равнялась бы размеру списка.
  const agreementCount = useMemo(
    () => countWithAgreement(filterApplicants(applicants, selectedPriorities)),
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
    setAgreementFilter("all");
  }

  function handleMajorChange(code: string) {
    setSelectedMajor(code);
    setSelectedPriorities(new Set());
    setAgreementFilter("all");
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

  const agreementNote =
    agreementFilter === "with"
      ? "только с согласием"
      : agreementFilter === "without"
        ? "только без согласия"
        : "с согласием и без";

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header-inner">
          <div>
            <p className="eyebrow">Конкурсные списки · Бакалавриат 2026</p>
            <h1>Оценка шансов поступления</h1>
          </div>
          <div className="badges">
            {selectedHealth && (
              <div
                className={
                  selectedHealth.is_stale
                    ? "snapshot-badge badge-stale"
                    : "snapshot-badge badge-fresh"
                }
                title={
                  selectedHealth.is_stale
                    ? "Данные вуза давно не обновлялись — цифры могут отставать от сайта"
                    : "Данные вуза свежие"
                }
              >
                {selectedHealth.is_stale ? "⚠ " : ""}
                {freshnessLabel(selectedHealth)}
              </div>
            )}
            {data?.snapshot && (
              <div className="snapshot-badge" title="Последний успешный снимок">
                Данные на {formatSnapshotDate(data.snapshot.created_at)}
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="layout">
        {uniLoading ? (
          <div className="panel state-note">Загрузка списка направлений…</div>
        ) : uniUnavailable ? (
          <div className="panel state-note api-down">
            <h2>API временно недоступно</h2>
            <p>
              Не получилось связаться с сервером. Обычно это ненадолго —
              попробуйте ещё раз через минуту.
            </p>
            <button type="button" className="retry-btn" onClick={retryAll}>
              Повторить
            </button>
          </div>
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
              agreementFilter={agreementFilter}
              agreementCount={agreementCount}
              userScore={userScore}
              onUniversityChange={handleUniversityChange}
              onMajorChange={handleMajorChange}
              onTogglePriority={togglePriority}
              onResetPriorities={() => setSelectedPriorities(new Set())}
              onAgreementFilterChange={setAgreementFilter}
              onUserScoreChange={setUserScore}
            />

            <div className="content">
              {loading ? (
                <div className="panel state-note">Загрузка заявлений…</div>
              ) : unavailable ? (
                <div className="panel state-note api-down">
                  <h2>API временно недоступно</h2>
                  <p>Не удалось загрузить заявления. Попробуйте ещё раз.</p>
                  <button type="button" className="retry-btn" onClick={retry}>
                    Повторить
                  </button>
                </div>
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
                    agreementApplicants={agreementCount}
                    stats={data.stats}
                  />

                  <div className="panel">
                    <div className="panel-head">
                      <h2>{data.major.name}</h2>
                      <span className="panel-sub">
                        {data.major.code} · {filtered.length} заявлений ·{" "}
                        {priorityNote} · {agreementNote}
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

      <footer className="app-footer">
        Сервис работает в тестовом режиме. Для добавления новых ВУЗов или по
        другим вопросам напишите{" "}
        <a
          href="https://t.me/goldkuav"
          target="_blank"
          rel="noopener noreferrer"
        >
          @goldkuav
        </a>
      </footer>
    </div>
  );
}
