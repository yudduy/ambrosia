import type { MetricSummary } from "../lib/types";

function number(value: number | null, unit: string) {
  if (value === null) return "-";
  if (unit === "sessions" || Math.abs(value) >= 100) return Math.round(value).toLocaleString();
  return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function Sparkline({ metric }: { metric: MetricSummary }) {
  const values = metric.series.flatMap((point) => (point.value === null ? [] : [point.value]));
  if (values.length < 2) return <div className="sparkline sparkline--empty" aria-hidden="true" />;
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const span = maximum - minimum || 1;
  const path = metric.series
    .map((point, index) => {
      if (point.value === null) return null;
      const x = (index / Math.max(metric.series.length - 1, 1)) * 100;
      const y = 30 - ((point.value - minimum) / span) * 24;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .filter(Boolean)
    .join(" ");
  return (
    <svg className="sparkline" viewBox="0 0 100 34" preserveAspectRatio="none" aria-hidden="true">
      <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function MetricCard({ metric, compact = false }: { metric: MetricSummary; compact?: boolean }) {
  const showComparison = metric.value !== null && metric.comparison.description !== "Usual range";
  return (
    <article className={`metric-card ${compact ? "metric-card--compact" : ""}`}>
      <div className="metric-card__topline">
        <span>{metric.label}</span>
      </div>
      <div className="metric-card__value">
        {number(metric.value, metric.unit)} <small>{metric.unit}</small>
      </div>
      {!compact && <Sparkline metric={metric} />}
      {!compact && showComparison && <p className="metric-card__description">{metric.comparison.description}</p>}
    </article>
  );
}
