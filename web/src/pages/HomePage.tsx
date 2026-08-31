import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { CoverageBanner } from "../components/CoverageBanner";
import { MetricCard } from "../components/MetricCard";

export function HomePage() {
  const query = useQuery({ queryKey: ["home"], queryFn: api.home });
  const reportsQuery = useQuery({ queryKey: ["reports"], queryFn: api.reports });
  if (query.isLoading) return <PageLoading label="home" />;
  if (query.error || !query.data) return <PageError message={query.error?.message} retry={() => query.refetch()} />;
  const { data } = query;
  const syncStatus = String(data.sync.status ?? "not_started");
  const syncLabel = syncStatus === "success" ? "Up to date" : syncStatus === "partial" ? "Some data missing" : "Not synced";
  return (
    <div className="page home-page">
      <section className="page-intro page-intro--home">
        <div>
          <div className="page-meta"><span>{formatDate(data.as_of)}</span><span>Sync: {syncLabel}</span></div>
          <h1>This week</h1>
          <p className="page-summary">{data.sentence}</p>
        </div>
      </section>
      <CoverageBanner coverage={data.coverage} />
      <section className="section-block">
        <div className="metric-grid">
          {data.metrics.map((metric) => <MetricCard key={metric.key} metric={metric} />)}
        </div>
      </section>
      <details className="weekly-history">
        <summary>Past weeks ({reportsQuery.data?.reports.length ?? 0})</summary>
        <div>
          {(reportsQuery.data?.reports ?? []).slice(0, 6).map((report) => (
            <p key={report.week_start}><strong>{formatDate(report.week_start)}</strong><span>{report.summary}</span></p>
          ))}
        </div>
      </details>
    </div>
  );
}

export function PageLoading({ label }: { label: string }) {
  return <div className="page-state"><span className="loading-orbit" /><p>Loading {label}...</p></div>;
}

export function PageError({ message, retry }: { message?: string; retry: () => void }) {
  return <div className="page-state page-state--error"><h1>Could not load this page</h1><p>{message ?? "Try again."}</p><button onClick={retry}>Try again</button></div>;
}

export function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).format(new Date(`${value}T12:00:00Z`));
}
