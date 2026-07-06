// Гистограмма распределения баллов с вертикальными маркерами:
// средний балл (amber), проходной по местам (red), твой балл (green).
// Ось X числовая — маркеры ставятся на точное значение балла.

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { BIN_SIZE, type HistogramBin } from "../utils/analysis";

interface Props {
  bins: HistogramBin[];
  averageScore: number | null;
  cutoffScore: number | null;
  userScore: number | null;
}

const COLORS = {
  bar: "#94a3b8",
  barUser: "#10b981",
  average: "#f59e0b",
  cutoff: "#ef4444",
  user: "#10b981",
};

interface ChartPoint {
  center: number;
  start: number;
  label: string;
  count: number;
}

// Recharts распознаёт опорные линии по типу дочернего элемента, поэтому
// ReferenceLine нельзя оборачивать в свой компонент — строим их фабрикой.
// dy разносит подписи по высоте, чтобы они не наезжали друг на друга,
// когда маркеры стоят близко.
function markerLine(
  key: string,
  score: number | null,
  color: string,
  caption: string,
  dy: number,
) {
  if (score === null) return null;
  return (
    <ReferenceLine
      key={key}
      x={score}
      stroke={color}
      strokeWidth={2}
      strokeDasharray="5 4"
      label={{
        value: `${caption}: ${score}`,
        position: "top",
        fill: color,
        fontSize: 11,
        fontWeight: 600,
        dy,
      }}
    />
  );
}

export function HistogramChart({
  bins,
  averageScore,
  cutoffScore,
  userScore,
}: Props) {
  if (bins.length === 0) {
    return <p className="empty-note">Нет данных для построения гистограммы.</p>;
  }

  const data: ChartPoint[] = bins.map((b) => ({
    center: b.start + BIN_SIZE / 2,
    start: b.start,
    label: b.label,
    count: b.count,
  }));

  const domainMin = bins[0].start;
  const domainMax = bins[bins.length - 1].start + BIN_SIZE;
  // Метки оси — по левым границам интервалов, но не гуще, чем каждые 20 баллов.
  const tickStep = bins.length > 16 ? BIN_SIZE * 2 : BIN_SIZE;
  const ticks: number[] = [];
  for (let s = domainMin; s <= domainMax; s += tickStep) ticks.push(s);

  // Ширина столбца в пикселях: подстраиваем под число интервалов.
  const barSize = Math.max(6, Math.floor(560 / bins.length));

  const userStart =
    userScore !== null
      ? Math.floor(userScore / BIN_SIZE) * BIN_SIZE
      : null;

  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height={380}>
        <BarChart data={data} margin={{ top: 44, right: 20, left: 0, bottom: 8 }}>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="var(--grid)"
            vertical={false}
          />
          <XAxis
            dataKey="center"
            type="number"
            domain={[domainMin, domainMax]}
            ticks={ticks}
            tick={{ fontSize: 11, fill: "var(--text-muted)" }}
            tickFormatter={(v) => String(v)}
            height={28}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fontSize: 11, fill: "var(--text-muted)" }}
            width={40}
            label={{
              value: "Человек",
              angle: -90,
              position: "insideLeft",
              fontSize: 11,
              fill: "var(--text-muted)",
            }}
          />
          <Tooltip
            cursor={{ fill: "var(--bar-hover)" }}
            contentStyle={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              fontSize: 12,
            }}
            labelFormatter={(v) => {
              const point = data.find((d) => d.center === v);
              return `Баллы ${point ? point.label : v}`;
            }}
            formatter={(value) => [`${value}`, "Абитуриентов"]}
          />
          <Bar dataKey="count" radius={[3, 3, 0, 0]} barSize={barSize}>
            {data.map((d) => (
              <Cell
                key={d.start}
                fill={d.start === userStart ? COLORS.barUser : COLORS.bar}
              />
            ))}
          </Bar>

          {markerLine("avg", averageScore, COLORS.average, "Средний", -16)}
          {markerLine("cut", cutoffScore, COLORS.cutoff, "Проходной", 0)}
          {markerLine("user", userScore, COLORS.user, "Ты", 0)}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
