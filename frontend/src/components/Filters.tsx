// Панель фильтров: вуз, направление, приоритеты, согласие, свой балл.

import type { UniversityInfo } from "../types";
import type { AgreementFilter } from "../utils/analysis";

interface Props {
  universities: UniversityInfo[];
  selectedUniversity: string | null;
  selectedMajor: string | null;
  availablePriorities: number[];
  selectedPriorities: Set<number>;
  agreementFilter: AgreementFilter;
  // Сколько заявлений с согласием есть в направлении (0 = вуз их не публикует
  // или их пока никто не подал — тогда предупреждаем, что фильтр всё скроет).
  agreementCount: number;
  userScore: number | null;
  onUniversityChange: (code: string) => void;
  onMajorChange: (code: string) => void;
  onTogglePriority: (priority: number) => void;
  onResetPriorities: () => void;
  onAgreementFilterChange: (value: AgreementFilter) => void;
  onUserScoreChange: (score: number | null) => void;
}

// Подписи переключателя согласия.
const AGREEMENT_OPTIONS: { value: AgreementFilter; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "with", label: "С согласием" },
  { value: "without", label: "Без согласия" },
];

export function Filters(props: Props) {
  const {
    universities,
    selectedUniversity,
    selectedMajor,
    availablePriorities,
    selectedPriorities,
    agreementFilter,
    agreementCount,
    userScore,
    onUniversityChange,
    onMajorChange,
    onTogglePriority,
    onResetPriorities,
    onAgreementFilterChange,
    onUserScoreChange,
  } = props;

  const currentUniversity = universities.find(
    (u) => u.code === selectedUniversity,
  );
  const majors = currentUniversity?.majors ?? [];

  return (
    <aside className="filters" aria-label="Фильтры">
      <div className="field">
        <label className="field-label" htmlFor="university-select">
          Вуз
        </label>
        <select
          id="university-select"
          className="control"
          value={selectedUniversity ?? ""}
          onChange={(e) => onUniversityChange(e.target.value)}
        >
          {universities.map((u) => (
            <option key={u.code} value={u.code}>
              {u.name}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label className="field-label" htmlFor="major-select">
          Направление
        </label>
        <select
          id="major-select"
          className="control"
          value={selectedMajor ?? ""}
          onChange={(e) => onMajorChange(e.target.value)}
          disabled={majors.length === 0}
        >
          {majors.map((m) => (
            <option key={m.code} value={m.code}>
              {m.code} · {m.name}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <div className="field-label-row">
          <span className="field-label">Приоритеты</span>
          {selectedPriorities.size > 0 && (
            <button
              type="button"
              className="link-button"
              onClick={onResetPriorities}
            >
              Сбросить
            </button>
          )}
        </div>
        <p className="field-hint">
          Не выбрано — учитываются все приоритеты. Выберите 1, чтобы смотреть
          только основной. Заявления без баллов (нет ЕГЭ) не учитываются.
        </p>
        <div className="priority-list">
          {availablePriorities.map((p) => {
            const checked = selectedPriorities.has(p);
            return (
              <label
                key={p}
                className={`priority-chip${checked ? " priority-chip--on" : ""}`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onTogglePriority(p)}
                />
                Приоритет {p}
              </label>
            );
          })}
        </div>
      </div>

      <div className="field">
        <span className="field-label">Согласие на зачисление</span>
        <p className="field-hint">
          {agreementCount > 0
            ? `В выборке с согласием — ${agreementCount} заявл. Это те, кто реально претендует на место.`
            : "По этому направлению согласий пока нет — фильтр оставит список пустым."}
        </p>
        <div
          className="priority-list"
          role="radiogroup"
          aria-label="Согласие на зачисление"
        >
          {AGREEMENT_OPTIONS.map((option) => {
            const checked = agreementFilter === option.value;
            return (
              <label
                key={option.value}
                className={`priority-chip${checked ? " priority-chip--on" : ""}`}
              >
                <input
                  type="radio"
                  name="agreement-filter"
                  checked={checked}
                  onChange={() => onAgreementFilterChange(option.value)}
                />
                {option.label}
              </label>
            );
          })}
        </div>
      </div>

      <div className="field">
        <label className="field-label" htmlFor="user-score">
          Твои баллы
        </label>
        <input
          id="user-score"
          className="control"
          type="number"
          min={0}
          max={400}
          inputMode="numeric"
          placeholder="напр. 250"
          value={userScore ?? ""}
          onChange={(e) => {
            const value = e.target.value.trim();
            onUserScoreChange(value === "" ? null : Number(value));
          }}
        />
        <p className="field-hint">
          Показывается зелёной линией на гистограмме и в выводе о шансах.
        </p>
      </div>
    </aside>
  );
}
