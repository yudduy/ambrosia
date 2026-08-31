import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { RangeName } from "../lib/types";
import { MetricCard } from "../components/MetricCard";
import { RangeSwitch } from "../components/RangeSwitch";
import { TrendChart } from "../components/TrendChart";
import { PageError, PageLoading } from "./HomePage";

export function NutritionPage() {
  const [range, setRange] = useState<RangeName>("28d");
  const query = useQuery({
    queryKey: ["nutrition", range],
    queryFn: () => api.domain("nutrition", range),
  });

  if (query.isLoading) return <PageLoading label="nutrition" />;
  if (query.error || !query.data) {
    return <PageError message={query.error?.message} retry={() => query.refetch()} />;
  }

  const { data } = query;
  return (
    <div className="page nutrition-page">
      <section className="page-intro">
        <div>
          <h1>Nutrition</h1>
          {data.coverage.covered_days > 0 && <p className="page-summary">{data.summary}</p>}
        </div>
        <RangeSwitch value={range} onChange={setRange} />
      </section>
      <section className="nutrition-data-grid">
        <div className="trend-section">
          <div className="trend-section__header"><h2>{data.metrics[0]?.label ?? "Calories"}</h2></div>
          <TrendChart metric={data.metrics[0]} />
        </div>
        <div className="metric-grid metric-grid--nutrition">
          {data.metrics.map((metric) => <MetricCard key={metric.key} metric={metric} compact />)}
        </div>
      </section>
    </div>
  );
}
