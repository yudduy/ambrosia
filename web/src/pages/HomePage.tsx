import { useEffect, useState, type CSSProperties } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Renew } from "@carbon/icons-react";
import { api } from "../lib/api";
import type { DailyInsight, DailyReadiness, MetricSummary, ReadinessComponent, ReadinessScore } from "../lib/types";

export function HomePage({ onAsk }: { onAsk: () => void }) {
  const queryClient = useQueryClient();
  const [selectedDate, setSelectedDate] = useState<string>();
  const [currentWeek, setCurrentWeek] = useState<DailyReadiness[]>();
  const [insights, setInsights] = useState<Record<string, DailyInsight>>({});
  const query = useQuery({
    queryKey: ["home", selectedDate ?? "today"],
    queryFn: () => api.home(selectedDate),
    refetchInterval: 5 * 60 * 1000,
  });
  const reportsQuery = useQuery({ queryKey: ["reports"], queryFn: api.reports });
  const sync = useMutation({
    mutationFn: api.sync,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["home"] });
    },
  });
  const insight = useMutation({
    mutationFn: api.homeInsight,
    onSuccess: (result) => setInsights((current) => ({ ...current, [result.as_of]: result })),
  });

  useEffect(() => {
    if (!selectedDate && query.data) setCurrentWeek(query.data.readiness_history);
  }, [query.data, selectedDate]);

  if (query.isLoading) return <PageLoading label="today" />;
  if (query.error || !query.data) return <PageError message={query.error?.message} retry={() => query.refetch()} />;
  const { data } = query;
  const isToday = data.as_of === localDate();
  const history = currentWeek ?? data.readiness_history;
  const syncConfigured = Boolean(data.sync.configured);

  function summarizeToday() {
    if (localStorage.getItem("ambrosia-ai-disclosure") !== "accepted") {
      onAsk();
      return;
    }
    insight.mutate(data.as_of);
  }

  return (
    <div className="page today-page">
      <header className="today-header">
        <div>
          <p>{formatLongDate(data.as_of)}</p>
          <h1>{isToday ? "Today" : formatWeekday(data.as_of)}</h1>
        </div>
        <div className="sync-control">
          <span>{syncText(data.sync)}</span>
          <button
            type="button"
            onClick={() => sync.mutate()}
            disabled={!syncConfigured || sync.isPending}
            aria-label={syncConfigured ? "Sync Google Health now" : "Google Health is not connected"}
          >
            <Renew size={16} className={sync.isPending ? "is-spinning" : ""} />
            {sync.isPending ? "Syncing" : "Sync now"}
          </button>
        </div>
      </header>

      <DateStrip history={history} selected={data.as_of} onSelect={setSelectedDate} />

      <DailyInsightLine
        value={insights[data.as_of]}
        pending={insight.isPending && insight.variables === data.as_of}
        error={insight.error}
        onSummarize={summarizeToday}
      />

      <ReadinessPanel readiness={data.readiness} />

      <MetricSection
        title={isToday ? "Today so far" : "That day"}
        metrics={data.today_metrics}
        partial={isToday}
      />
      <MetricSection title="Last night" metrics={data.overnight_metrics} />

      {sync.error && <p className="inline-error today-sync-error">{sync.error.message}</p>}

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

function DailyInsightLine({
  value, pending, error, onSummarize,
}: {
  value?: DailyInsight;
  pending: boolean;
  error: Error | null;
  onSummarize: () => void;
}) {
  if (value) {
    return <section className="daily-insight" aria-label="AI summary"><span>AI</span><p>{value.text}</p></section>;
  }
  return (
    <section className="daily-insight daily-insight--empty" aria-live="polite">
      <button type="button" onClick={onSummarize} disabled={pending}>{pending ? "Summarizing" : "Summarize with AI"}</button>
      {error && <span>{error.message}</span>}
    </section>
  );
}

function ReadinessPanel({ readiness }: { readiness: ReadinessScore }) {
  if (readiness.score === null) {
    return (
      <section className="readiness-panel readiness-panel--empty" aria-labelledby="readiness-title">
        <p>Readiness</p>
        <h2 id="readiness-title">{readiness.message}</h2>
      </section>
    );
  }
  return (
    <section className="readiness-panel" aria-labelledby="readiness-title">
      <ScoreRing score={readiness.score} label={readiness.label} />
      <div className="readiness-content">
        <div className="readiness-heading">
          <div><p>Readiness</p><h2 id="readiness-title">{capitalize(readiness.label)}</h2></div>
          <span>{readiness.baseline_days}/28 baseline days</span>
        </div>
        <div className="readiness-components">
          {readiness.components.map((component) => <ReadinessSignal key={component.key} component={component} />)}
        </div>
        <details className="score-method">
          <summary>How the score works</summary>
          <p>Sleep is 40%. HRV and resting heart rate are 30% each. Each is compared with your previous 28 valid days.</p>
        </details>
      </div>
    </section>
  );
}

function DateStrip({ history, selected, onSelect }: { history: DailyReadiness[]; selected: string; onSelect: (date: string) => void }) {
  return (
    <nav className="date-strip" aria-label="Daily readiness">
      {history.map((day) => (
        <button
          key={day.date}
          type="button"
          className={day.date === selected ? "active" : ""}
          aria-current={day.date === selected ? "date" : undefined}
          aria-label={`${formatLongDate(day.date)}${day.score === null ? ", no readiness score" : `, readiness ${day.score}`}`}
          onClick={() => onSelect(day.date)}
          style={{ "--day-score": day.score ?? 0 } as CSSProperties}
        >
          <span>{formatNarrowWeekday(day.date)}</span>
          <strong>{day.score ?? "-"}</strong>
          <small>{formatDay(day.date)}</small>
        </button>
      ))}
    </nav>
  );
}

function ScoreRing({ score, label }: { score: number | null; label: string }) {
  return (
    <div
      className={`score-ring ${score === null ? "score-ring--empty" : ""}`}
      style={{ "--readiness-score": score ?? 0 } as CSSProperties}
      role="img"
      aria-label={score === null ? "Readiness unavailable" : `Readiness ${score}, ${label}`}
    >
      <div><strong>{score ?? "-"}</strong><span>out of 100</span></div>
    </div>
  );
}

function ReadinessSignal({ component }: { component: ReadinessComponent }) {
  return (
    <article>
      <div><span>{component.label}</span><strong>{component.score}</strong></div>
      <p>{metricNumber(component.value, component.unit)} <small>{component.unit}</small></p>
      <small>Usual {metricNumber(component.baseline_median, component.unit)} {component.unit}</small>
    </article>
  );
}

function MetricSection({ title, metrics, partial = false }: { title: string; metrics: MetricSummary[]; partial?: boolean }) {
  return (
    <section className="daily-section">
      <h2>{title}</h2>
      <div className="daily-metrics">
        {metrics.map((metric) => (
          <article key={metric.key}>
            <span>{metricLabel(metric)}</span>
            <p>{metricNumber(metric.value, metric.unit)} <small>{displayUnit(metric.unit)}</small></p>
            <small>{metricContext(metric, partial)}</small>
          </article>
        ))}
      </div>
    </section>
  );
}

function metricLabel(metric: MetricSummary) {
  if (metric.key === "calories") return "Calories logged";
  return metric.label;
}

function metricContext(metric: MetricSummary, partial: boolean) {
  if (metric.value === null) return "No data";
  if (partial) return "So far";
  if (metric.comparison.baseline_median === null) return "No baseline";
  if (metric.comparison.direction !== "within") return metric.comparison.description;
  return `Usual ${metricNumber(metric.comparison.baseline_median, metric.unit)} ${displayUnit(metric.unit)}`;
}

function displayUnit(unit: string) {
  return unit.replace("/day", "").replace("/night", "").replace("/week", "");
}

function metricNumber(value: number | null, unit: string) {
  if (value === null) return "-";
  if (unit === "sessions" || Math.abs(value) >= 100) return Math.round(value).toLocaleString();
  return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function syncText(sync: Record<string, unknown>) {
  if (!sync.configured) return "Google Health not connected";
  const status = String(sync.status ?? "not_started");
  if (status === "not_started") return "Waiting for first sync";
  if (status === "failed") return "Last sync failed";
  const updated = relativeTime(sync.finished_at);
  if (status !== "partial") return updated;
  const failed = failedTypes(sync.details);
  return failed.length ? `${updated}. ${joinWords(failed)} not synced` : `${updated}. Some data missing`;
}

function failedTypes(value: unknown) {
  try {
    const details = typeof value === "string" ? JSON.parse(value) as { failed_types?: string[] } : value as { failed_types?: string[] };
    return (details?.failed_types ?? []).map((type) => ({
      "nutrition-log": "Food",
      "hydration-log": "Water",
    })[type] ?? type.replaceAll("-", " "));
  } catch {
    return [];
  }
}

function joinWords(values: string[]) {
  if (values.length < 2) return values[0] ?? "";
  return `${values.slice(0, -1).join(", ")} and ${values.at(-1)}`;
}

function relativeTime(value: unknown) {
  if (typeof value !== "string") return "Synced";
  const minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60_000));
  if (minutes < 1) return "Updated now";
  if (minutes < 60) return `Updated ${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `Updated ${hours} hr ago`;
  return `Updated ${Math.round(hours / 24)} days ago`;
}

function dateFrom(value: string) {
  return new Date(`${value}T12:00:00`);
}

function localDate() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatLongDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" }).format(dateFrom(value));
}

function formatWeekday(value: string) {
  return new Intl.DateTimeFormat(undefined, { weekday: "long" }).format(dateFrom(value));
}

function formatNarrowWeekday(value: string) {
  return new Intl.DateTimeFormat(undefined, { weekday: "narrow" }).format(dateFrom(value));
}

function formatDay(value: string) {
  return new Intl.DateTimeFormat(undefined, { day: "numeric" }).format(dateFrom(value));
}

function capitalize(value: string) {
  return `${value.charAt(0).toUpperCase()}${value.slice(1)}`;
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
