import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Domain, RangeName } from "../lib/types";
import { MetricCard } from "../components/MetricCard";
import { RangeSwitch } from "../components/RangeSwitch";
import { TrendChart } from "../components/TrendChart";
import { PageError, PageLoading } from "./HomePage";

export function DomainPage({ domain }: { domain: Exclude<Domain, "nutrition"> }) {
  const [range, setRange] = useState<RangeName>("28d");
  const [selected, setSelected] = useState(0);
  const query = useQuery({ queryKey: [domain, range], queryFn: () => api.domain(domain, range) });
  if (query.isLoading) return <PageLoading label={domain} />;
  if (query.error || !query.data) return <PageError message={query.error?.message} retry={() => query.refetch()} />;
  const { data } = query;
  const title = domain === "fitness" ? "Fitness" : "Sleep";
  const selectedMetric = data.metrics[selected] ?? data.metrics[0];
  const latestNight = domain === "sleep" ? data.details.selected_night as Record<string, unknown> | null : null;
  const timing = latestNight?.timing as Record<string, number | string> | undefined;
  const overnightHeartRate = (latestNight?.overnight_heart_rate as Array<{ value: number }> | undefined) ?? [];
  const sessions = domain === "fitness" ? (data.details.recent_sessions as Array<Record<string, unknown>> | undefined) ?? [] : [];
  return (
    <div className="page domain-page">
      <section className="page-intro">
        <div><h1>{title}</h1><p className="page-summary">{data.summary}</p></div>
        <RangeSwitch value={range} onChange={(next) => { setRange(next); setSelected(0); }} />
      </section>
      <section className="trend-section">
        <div className="trend-section__header">
          <h2>{selectedMetric?.label ?? title}</h2>
          <div className="metric-tabs" role="tablist" aria-label={`${domain} metric`}>
            {data.metrics.map((metric, index) => (
              <button key={metric.key} role="tab" aria-selected={selected === index} className={selected === index ? "active" : ""} onClick={() => setSelected(index)}>{metric.label}</button>
            ))}
          </div>
        </div>
        <TrendChart metric={selectedMetric} />
      </section>
      <section className="metric-grid metric-grid--domain">
        {data.metrics.map((metric) => <MetricCard key={metric.key} metric={metric} compact />)}
      </section>
      {domain === "sleep" && (
        <section className="detail-card">
          <div className="detail-card__heading"><h2>Last night</h2><strong>{latestNight ? `${((Number(latestNight.duration_minutes) || 0) / 60).toFixed(1)} hr` : "No data"}</strong></div>
          {latestNight ? (
            <div className="sleep-detail-content">
              <div className="stage-grid">
                {["awake_minutes", "light_minutes", "deep_minutes", "rem_minutes"].map((key) => (
                  <div key={key}><span>{key.replace("_minutes", "")}</span><strong>{Math.round(Number(latestNight[key]) || 0)} min</strong></div>
                ))}
              </div>
              <div className="sleep-context-grid">
                <div><span>Bedtime</span><strong>{timing ? new Date(String(timing.bedtime)).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "-"}</strong><small>{timing ? timingDifference(Number(timing.bedtime_difference_minutes)) : "No comparison"}</small></div>
                <div><span>Wake time</span><strong>{timing ? new Date(String(timing.wake_time)).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "-"}</strong><small>{timing ? timingDifference(Number(timing.wake_difference_minutes)) : "No comparison"}</small></div>
                <div><span>Heart rate</span><strong>{overnightHeartRate.length ? `${Math.round(Math.min(...overnightHeartRate.map((item) => item.value)))}-${Math.round(Math.max(...overnightHeartRate.map((item) => item.value)))} bpm` : "No data"}</strong></div>
              </div>
            </div>
          ) : <p>No sleep data for this period.</p>}
        </section>
      )}
      {domain === "fitness" && (
        <section className="detail-card sessions-card">
          <h2>Workouts</h2>
          <div className="session-list">
            {sessions.length ? sessions.slice(0, 6).map((session) => {
              const details = session.details as Record<string, unknown>;
              return <div key={String(session.id)}><span><strong>{String(session.title)}</strong><small>{new Date(String(session.start_at)).toLocaleDateString()}</small></span><span>{Math.round(Number(session.duration_minutes))} min{details.active_zone_minutes ? <small>{`${details.active_zone_minutes} zone min`}</small> : null}</span></div>;
            }) : <p>No workouts in this period.</p>}
          </div>
        </section>
      )}
    </div>
  );
}

function timingDifference(value: number) {
  if (!Number.isFinite(value) || value === 0) return "Usual time";
  return `${Math.abs(Math.round(value))} min ${value > 0 ? "later" : "earlier"} than usual`;
}
