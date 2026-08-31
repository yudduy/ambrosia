import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Domain, RangeName } from "../lib/types";
import { CoverageBanner } from "../components/CoverageBanner";
import { MetricCard } from "../components/MetricCard";
import { RangeSwitch } from "../components/RangeSwitch";
import { TrendChart } from "../components/TrendChart";
import { PageError, PageLoading } from "./HomePage";

const copy = {
  fitness: { eyebrow: "Training and movement", title: "Fitness", description: "Movement and sessions, described against your own recent pattern." },
  sleep: { eyebrow: "Nights and recovery", title: "Sleep", description: "Coverage comes first. Conclusions stay personal, without population ranges." },
};

export function DomainPage({ domain }: { domain: Exclude<Domain, "nutrition"> }) {
  const [range, setRange] = useState<RangeName>("28d");
  const [selected, setSelected] = useState(0);
  const query = useQuery({ queryKey: [domain, range], queryFn: () => api.domain(domain, range) });
  if (query.isLoading) return <PageLoading label={`Building your ${domain} view`} />;
  if (query.error || !query.data) return <PageError message={query.error?.message} retry={() => query.refetch()} />;
  const { data } = query;
  const content = copy[domain];
  const selectedMetric = data.metrics[selected] ?? data.metrics[0];
  const latestNight = domain === "sleep" ? data.details.selected_night as Record<string, unknown> | null : null;
  const timing = latestNight?.timing as Record<string, number | string> | undefined;
  const overnightHeartRate = (latestNight?.overnight_heart_rate as Array<{ value: number }> | undefined) ?? [];
  const sessions = domain === "fitness" ? (data.details.recent_sessions as Array<Record<string, unknown>> | undefined) ?? [] : [];
  return (
    <div className="page domain-page">
      <section className="page-intro">
        <div><p className="eyebrow">{content.eyebrow}</p><h1>{content.title}</h1><p>{content.description}</p></div>
        <RangeSwitch value={range} onChange={(next) => { setRange(next); setSelected(0); }} />
      </section>
      <CoverageBanner coverage={data.coverage} provenance={data.provenance} />
      <section className="insight-band"><span>Current read</span><h2>{data.summary}</h2></section>
      <section className="trend-section">
        <div className="trend-section__header">
          <div><p className="eyebrow">Daily view</p><h2>{selectedMetric?.label ?? content.title}</h2></div>
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
          <div><p className="eyebrow">Most recent covered night</p><h2>{latestNight ? `${((Number(latestNight.duration_minutes) || 0) / 60).toFixed(1)} hours` : "No covered night"}</h2></div>
          {latestNight ? (
            <div className="sleep-detail-content">
              <div className="stage-grid">
                {["awake_minutes", "light_minutes", "deep_minutes", "rem_minutes"].map((key) => (
                  <div key={key}><span>{key.replace("_minutes", "")}</span><strong>{Math.round(Number(latestNight[key]) || 0)} min</strong></div>
                ))}
              </div>
              <div className="sleep-context-grid">
                <div><span>Bedtime</span><strong>{timing ? new Date(String(timing.bedtime)).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "—"}</strong><small>{timing ? `${timing.bedtime_difference_minutes} min from 28-night median` : "No timing baseline"}</small></div>
                <div><span>Wake time</span><strong>{timing ? new Date(String(timing.wake_time)).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "—"}</strong><small>{timing ? `${timing.wake_difference_minutes} min from 28-night median` : "No timing baseline"}</small></div>
                <div><span>Overnight heart rate</span><strong>{overnightHeartRate.length ? `${Math.round(Math.min(...overnightHeartRate.map((item) => item.value)))}–${Math.round(Math.max(...overnightHeartRate.map((item) => item.value)))} bpm` : "No coverage"}</strong><small>{overnightHeartRate.length ? `${overnightHeartRate.length} five-minute medians` : "Raw samples stay local"}</small></div>
              </div>
            </div>
          ) : <p>Sleep stages appear only when the wearable supplies a complete session.</p>}
        </section>
      )}
      {domain === "fitness" && (
        <section className="detail-card sessions-card">
          <div><p className="eyebrow">Workout history</p><h2>Recent sessions</h2></div>
          <div className="session-list">
            {sessions.length ? sessions.slice(0, 6).map((session) => {
              const details = session.details as Record<string, unknown>;
              return <div key={String(session.id)}><span><strong>{String(session.title)}</strong><small>{new Date(String(session.start_at)).toLocaleDateString()}</small></span><span>{Math.round(Number(session.duration_minutes))} min<small>{details.active_zone_minutes ? `${details.active_zone_minutes} zone min` : "covered session"}</small></span></div>;
            }) : <p>No workout sessions are available in this period.</p>}
          </div>
        </section>
      )}
    </div>
  );
}
