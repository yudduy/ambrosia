import { LineChart } from "@carbon/charts-react";
import { ChartTheme, ScaleTypes, type LineChartOptions } from "@carbon/charts";
import type { MetricSummary } from "../lib/types";

function escapeHtml(value: string) {
  return value.replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[character]!);
}

export function tooltipMarkup(metric: Pick<MetricSummary, "unit">, datum: { date?: unknown; value?: unknown }) {
  const date = datum.date instanceof Date ? datum.date : new Date(String(datum.date));
  const dateLabel = Number.isNaN(date.getTime())
    ? "Selected day"
    : date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  const value = Number(datum.value);
  const valueLabel = Number.isFinite(value)
    ? value.toLocaleString(undefined, { maximumFractionDigits: Math.abs(value) >= 100 ? 0 : 1 })
    : "-";
  return `<span class="ambrosia-chart-tooltip"><span>${escapeHtml(dateLabel)}</span><strong>${escapeHtml(valueLabel)} <small>${escapeHtml(metric.unit)}</small></strong></span>`;
}

export function TrendChart({ metric }: { metric: MetricSummary | undefined }) {
  if (!metric || metric.series.every((point) => point.value === null)) {
    return (
      <div className="chart-empty">
        <span className="chart-empty__line" />
        <p>No data for this period.</p>
      </div>
    );
  }
  const data = metric.series.flatMap((point) =>
    point.value === null
      ? []
      : [{ group: metric.label, date: new Date(`${point.date}T12:00:00`), value: point.value }],
  );
  const options: LineChartOptions = {
    theme: ChartTheme.G100,
    height: "300px",
    axes: {
      bottom: { mapsTo: "date", scaleType: ScaleTypes.TIME },
      left: { mapsTo: "value", scaleType: ScaleTypes.LINEAR, title: metric.unit },
    },
    curve: "curveMonotoneX" as const,
    points: { enabled: data.length <= 28 },
    legend: { enabled: false },
    toolbar: { enabled: false },
    grid: { x: { enabled: false }, y: { enabled: true } },
    color: { scale: { [metric.label]: "#30a46c" } },
    tooltip: {
      customHTML: (_tooltipData, _defaultHTML, datum) => tooltipMarkup(metric, datum),
    },
    accessibility: { svgAriaLabel: `${metric.label} trend over the selected period` },
  };
  return <LineChart data={data} options={options} />;
}
