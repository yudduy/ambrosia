import { LineChart } from "@carbon/charts-react";
import { ChartTheme, ScaleTypes } from "@carbon/charts";
import type { MetricSummary } from "../lib/types";

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
  const options = {
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
    accessibility: { svgAriaLabel: `${metric.label} trend over the selected period` },
  };
  return <LineChart data={data} options={options} />;
}
