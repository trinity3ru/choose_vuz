// Сводка: числовые плитки + текстовый вывод о реалистичности поступления.

import type { MajorStats } from "../types";

interface Props {
  averageScore: number | null;
  cutoffScore: number | null;
  userScore: number | null;
  userRank: number | null;
  totalApplicants: number;
  // Сколько заявлений с согласием на зачисление (без учёта фильтра согласия).
  agreementApplicants: number;
  stats: MajorStats | null;
}

type Verdict = "good" | "borderline" | "risky" | "none";

function buildVerdict(
  userScore: number | null,
  averageScore: number | null,
  cutoffScore: number | null,
): { level: Verdict; text: string } {
  if (userScore === null || averageScore === null) {
    return {
      level: "none",
      text: "Введите свои баллы, чтобы оценить позицию относительно среднего балла — «середины», по которой оцениваем гарантированный проход.",
    };
  }

  const vsAvg = userScore - averageScore;

  // Оценка строится от среднего балла: средняя позиция = точка, по которой
  // гарантированно проходишь. Проходной по местам показываем как факт справкой.
  const cutoffNote =
    cutoffScore !== null
      ? ` Оценочный проходной по числу мест — ${cutoffScore} б.`
      : "";

  let level: Verdict;
  let main: string;

  if (vsAvg > 0) {
    level = "good";
    main = `Твой балл на ${vsAvg} б. выше средней позиции — по этой выборке проходишь уверенно.`;
  } else if (vsAvg === 0) {
    level = "good";
    main = `Твой балл ровно на средней позиции — по этой выборке проходишь.`;
  } else if (vsAvg >= -10) {
    level = "borderline";
    main = `Твой балл на ${Math.abs(vsAvg)} б. ниже средней позиции — пограничная зона, шанс есть.`;
  } else {
    level = "risky";
    main = `Твой балл на ${Math.abs(vsAvg)} б. ниже средней позиции — до «середины» не дотягиваешь, поступление по этой выборке маловероятно.`;
  }

  return { level, text: main + cutoffNote };
}

function Tile({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: string;
}) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value" style={accent ? { color: accent } : undefined}>
        {value}
      </div>
    </div>
  );
}

export function Summary({
  averageScore,
  cutoffScore,
  userScore,
  userRank,
  totalApplicants,
  agreementApplicants,
  stats,
}: Props) {
  const verdict = buildVerdict(userScore, averageScore, cutoffScore);

  const competition =
    stats?.places && stats.places > 0 && stats.applications
      ? (stats.applications / stats.places).toFixed(1)
      : null;

  return (
    <section className="summary">
      <div className="tiles">
        <Tile
          label="Средний балл"
          value={averageScore !== null ? String(averageScore) : "—"}
          accent="#f59e0b"
        />
        <Tile
          label="Проходной (оценка)"
          value={cutoffScore !== null ? String(cutoffScore) : "—"}
          accent="#ef4444"
        />
        <Tile
          label="Твой балл"
          value={userScore !== null ? String(userScore) : "—"}
          accent="#10b981"
        />
        <Tile
          label="Твоя позиция"
          value={
            userRank !== null ? `${userRank} из ${totalApplicants}` : "—"
          }
        />
        <Tile
          label="Бюджетных мест"
          value={stats?.places != null ? String(stats.places) : "—"}
        />
        <Tile
          label="Конкурс"
          value={competition !== null ? `${competition} чел/место` : "—"}
        />
        <Tile
          label="С согласием"
          value={String(agreementApplicants)}
          accent="#3b82f6"
        />
      </div>

      <div className={`verdict verdict--${verdict.level}`} role="status">
        {verdict.text}
      </div>
    </section>
  );
}
