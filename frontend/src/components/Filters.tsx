// Панель фильтров: вуз, направление, приоритеты, свой балл.

import type { UniversityInfo } from "../types";

interface Props {
  universities: UniversityInfo[];
  selectedUniversity: string | null;
  selectedMajor: string | null;
  availablePriorities: number[];
  selectedPriorities: Set<number>;
  userScore: number | null;
  onUniversityChange: (code: string) => void;
  onMajorChange: (code: string) => void;
  onTogglePriority: (priority: number) => void;
  onResetPriorities: () => void;
  onUserScoreChange: (score: number | null) => void;
}

export function Filters(props: Props) {
  const {
    universities,
    selectedUniversity,
    selectedMajor,
    availablePriorities,
    selectedPriorities,
    userScore,
    onUniversityChange,
    onMajorChange,
    onTogglePriority,
    onResetPriorities,
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
