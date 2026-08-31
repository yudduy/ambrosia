import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CheckmarkFilled, Renew } from "@carbon/icons-react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { CoverageBanner } from "../components/CoverageBanner";
import { MetricCard } from "../components/MetricCard";

export function HomePage({ openAssistant }: { openAssistant: () => void }) {
  const query = useQuery({ queryKey: ["home"], queryFn: api.home });
  const reportsQuery = useQuery({ queryKey: ["reports"], queryFn: api.reports });
  if (query.isLoading) return <PageLoading label="Building your seven-day view" />;
  if (query.error || !query.data) return <PageError message={query.error?.message} retry={() => query.refetch()} />;
  const { data } = query;
  const syncStatus = String(data.sync.status ?? "not_started");
  return (
    <div className="page home-page">
      <section className="page-intro page-intro--home">
        <div>
          <p className="eyebrow">Seven days ending {formatDate(data.as_of)}</p>
          <h1>{data.sentence}</h1>
        </div>
        <button className="ask-primary" onClick={openAssistant}>
          <span>Ask about this week</span><ArrowRight size={20} />
        </button>
      </section>
      <CoverageBanner coverage={data.coverage} provenance={data.provenance} />
      <section className="section-block">
        <div className="section-heading">
          <div><p className="eyebrow">Your signals</p><h2>What moved, and what did not</h2></div>
          <p>Each comparison uses your preceding 28 covered days. No composite score.</p>
        </div>
        <div className="metric-grid">
          {data.metrics.map((metric) => <MetricCard key={metric.key} metric={metric} />)}
        </div>
      </section>
      <section className="home-bottom-grid">
        <article className="report-card">
          <div className="report-card__icon"><CheckmarkFilled size={20} /></div>
          <div>
            <p className="eyebrow">Deterministic weekly report</p>
            <h2>{data.report?.summary ?? "The first report is forming."}</h2>
            <p>Generated locally with {data.report?.method_version ?? "personal-baseline-v1"}. It does not call AI.</p>
            <details className="report-archive">
              <summary>Report archive · {reportsQuery.data?.reports.length ?? 0}</summary>
              <div>
                {(reportsQuery.data?.reports ?? []).slice(0, 4).map((report) => (
                  <p key={report.week_start}><strong>{formatDate(report.week_start)}</strong><span>{report.summary}</span></p>
                ))}
              </div>
            </details>
          </div>
          <span className="report-card__date">Week of {data.report ? formatDate(data.report.week_start) : "—"}</span>
        </article>
        <article className="sync-card">
          <div className="sync-card__top"><Renew size={20} /><span className={`status-dot status-dot--${syncStatus}`} /></div>
          <p className="eyebrow">Latest sync</p>
          <h2>{syncStatus.replace("_", " ")}</h2>
          <p>{syncStatus === "success" ? "Google Health is current." : syncStatus === "partial" ? "Some data types need attention." : data.coverage.covered_days > 0 ? "Historical data is loaded; live Google Health sync has not run yet." : "Import the existing export to begin."}</p>
        </article>
      </section>
      <nav className="domain-links" aria-label="Health areas">
        {[
          ["Fitness", "Movement, workouts, and weekly load", "/fitness"],
          ["Sleep", "Duration, timing, stages, and recovery", "/sleep"],
          ["Nutrition", "Confirmed meals, hydration, and weight", "/nutrition"],
        ].map(([label, description, path]) => (
          <Link to={path} key={path}><span><strong>{label}</strong><small>{description}</small></span><ArrowRight size={20} /></Link>
        ))}
      </nav>
    </div>
  );
}

export function PageLoading({ label }: { label: string }) {
  return <div className="page-state"><span className="loading-orbit" /><h1>{label}</h1><p>Reading local, normalized health data.</p></div>;
}

export function PageError({ message, retry }: { message?: string; retry: () => void }) {
  return <div className="page-state page-state--error"><h1>This view could not be built.</h1><p>{message ?? "The local API did not respond."}</p><button onClick={retry}>Try again</button></div>;
}

export function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).format(new Date(`${value}T12:00:00Z`));
}
