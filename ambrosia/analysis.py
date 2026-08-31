from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Literal

import numpy as np

from .config import Settings, settings
from .db import Database, json_value
from .models import (
    Comparison,
    Coverage,
    DailyReadiness,
    DomainResponse,
    HomeResponse,
    MetricSummary,
    Provenance,
    ReadinessComponent,
    ReadinessScore,
    RelationshipResult,
    SeriesPoint,
    SessionSummary,
    SessionsResponse,
    WeeklyReport,
    WeeklyReportsResponse,
)


METHOD_VERSION = "personal-baseline-v1"
READINESS_METHOD_VERSION = "personal-readiness-v1"
RangeName = Literal["7d", "28d", "90d"]


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    label: str
    data_type: str
    unit: str
    source_table: Literal["daily", "sample", "interval", "sleep", "exercise", "nutrition"]
    daily_aggregation: Literal["sum", "median", "count", "mean"]
    period_aggregation: Literal["sum", "median", "mean"] = "median"
    scale: float = 1.0


METRICS: dict[str, MetricDefinition] = {
    "steps": MetricDefinition("steps", "Steps", "steps", "steps/day", "interval", "sum", "mean"),
    "active_minutes": MetricDefinition(
        "active_minutes", "Active minutes", "active-minutes", "min/day", "interval", "sum", "mean"
    ),
    "zone_minutes": MetricDefinition(
        "zone_minutes", "Active Zone Minutes", "active-zone-minutes", "min/day", "interval", "sum", "mean"
    ),
    "distance": MetricDefinition(
        "distance", "Distance", "distance", "mi/day", "interval", "sum", "mean", 1 / 1_609_344
    ),
    "workouts": MetricDefinition(
        "workouts", "Workouts", "exercise", "sessions", "exercise", "count", "sum"
    ),
    "workout_duration": MetricDefinition(
        "workout_duration", "Workout duration", "exercise", "min/week", "exercise", "sum", "sum"
    ),
    "sleep_duration": MetricDefinition(
        "sleep_duration", "Sleep", "sleep", "hr/night", "sleep", "sum", "mean", 1 / 60
    ),
    "resting_hr": MetricDefinition(
        "resting_hr", "Resting heart rate", "daily-resting-heart-rate", "bpm", "daily", "median"
    ),
    "hrv": MetricDefinition(
        "hrv", "HRV", "daily-heart-rate-variability", "ms", "daily", "median"
    ),
    "spo2": MetricDefinition(
        "spo2", "SpO₂", "daily-oxygen-saturation", "%", "daily", "median"
    ),
    "respiratory_rate": MetricDefinition(
        "respiratory_rate", "Respiratory rate", "daily-respiratory-rate", "breaths/min", "daily", "median"
    ),
    "weight": MetricDefinition("weight", "Weight", "weight", "lb", "sample", "median", "median", 0.0022046226),
    "calories": MetricDefinition(
        "calories", "Calories", "nutrition", "kcal/day", "nutrition", "sum", "mean"
    ),
    "protein": MetricDefinition(
        "protein", "Protein", "nutrition", "g/day", "nutrition", "sum", "mean"
    ),
    "hydration": MetricDefinition(
        "hydration", "Hydration", "nutrition", "ml/day", "nutrition", "sum", "mean"
    ),
}

DOMAIN_KEYS = {
    "fitness": ("steps", "active_minutes", "zone_minutes", "workouts", "workout_duration", "distance"),
    "sleep": ("sleep_duration", "resting_hr", "hrv", "respiratory_rate", "spo2"),
    "nutrition": ("calories", "protein", "hydration", "weight"),
}


def _percentile(values: list[float], percentile: float) -> float | None:
    return float(np.percentile(values, percentile)) if values else None


def _period_value(values: list[float], aggregation: str) -> float | None:
    if not values:
        return None
    if aggregation == "sum":
        return float(sum(values))
    if aggregation == "mean":
        return float(sum(values) / len(values))
    return float(median(values))


def _percentile_rank(value: float, values: list[float]) -> float:
    lower = sum(item < value for item in values)
    equal = sum(item == value for item in values)
    return (lower + equal / 2) / len(values) * 100


def _coverage(covered: int, expected: int, label: str = "days") -> Coverage:
    ratio = covered / expected if expected else 0
    complete = covered == expected
    if complete:
        message = f"{covered}/{expected} {label}"
    elif covered == 0:
        message = "No data"
    else:
        message = f"{covered}/{expected} {label}"
    return Coverage(
        covered_days=covered,
        expected_days=expected,
        ratio=round(ratio, 3),
        complete=complete,
        message=message,
    )


class HealthAnalysis:
    def __init__(self, database: Database, app_settings: Settings = settings):
        self.db = database
        self.settings = app_settings

    def _daily_values(self, metric: MetricDefinition, start: date, end: date) -> dict[date, float]:
        tz = self.settings.timezone.replace("'", "''")
        if metric.source_table == "daily":
            rows = self.db.rows(
                """
                SELECT day, median(value) AS value FROM daily_metrics
                WHERE data_type = ? AND day BETWEEN ? AND ? GROUP BY day ORDER BY day
                """,
                [metric.data_type, start, end],
            )
        elif metric.source_table == "sample":
            rows = self.db.rows(
                f"""
                SELECT CAST(timezone('{tz}', measured_at) AS DATE) AS day, median(value) AS value
                FROM metric_samples WHERE data_type = ?
                  AND CAST(timezone('{tz}', measured_at) AS DATE) BETWEEN ? AND ?
                GROUP BY day ORDER BY day
                """,
                [metric.data_type, start, end],
            )
        elif metric.source_table == "interval":
            function = "sum" if metric.daily_aggregation == "sum" else "median"
            rows = self.db.rows(
                f"""
                SELECT CAST(timezone('{tz}', start_at) AS DATE) AS day, {function}(value) AS value
                FROM metric_intervals WHERE data_type = ?
                  AND CAST(timezone('{tz}', start_at) AS DATE) BETWEEN ? AND ?
                GROUP BY day ORDER BY day
                """,
                [metric.data_type, start, end],
            )
        elif metric.source_table == "sleep":
            rows = self.db.rows(
                f"""
                SELECT CAST(timezone('{tz}', end_at) AS DATE) AS day, sum(duration_minutes) AS value
                FROM sleep_sessions
                WHERE CAST(timezone('{tz}', end_at) AS DATE) BETWEEN ? AND ?
                GROUP BY day ORDER BY day
                """,
                [start, end],
            )
        elif metric.source_table == "exercise":
            expression = "count(*)" if metric.daily_aggregation == "count" else "sum(duration_minutes)"
            rows = self.db.rows(
                f"""
                SELECT CAST(timezone('{tz}', start_at) AS DATE) AS day, {expression} AS value
                FROM exercise_sessions
                WHERE CAST(timezone('{tz}', start_at) AS DATE) BETWEEN ? AND ?
                GROUP BY day ORDER BY day
                """,
                [start, end],
            )
        else:
            expression = {
                "calories": "sum((calories_low + calories_high) / 2)",
                "protein": "sum((protein_low + protein_high) / 2)",
                "hydration": "sum(water_ml)",
            }[metric.key]
            rows = self.db.rows(
                f"""
                SELECT CAST(timezone('{tz}', eaten_at) AS DATE) AS day, {expression} AS value
                FROM nutrition_entries WHERE confirmed
                  AND CAST(timezone('{tz}', eaten_at) AS DATE) BETWEEN ? AND ?
                GROUP BY day ORDER BY day
                """,
                [start, end],
            )
        return {row["day"]: float(row["value"]) * metric.scale for row in rows if row["value"] is not None}

    def _metric_summary(self, key: str, end: date, days: int) -> MetricSummary:
        definition = METRICS[key]
        recent_start = end - timedelta(days=days - 1)
        baseline_scan_start = recent_start - timedelta(days=180)
        all_values = self._daily_values(definition, baseline_scan_start, end)
        recent = {day: value for day, value in all_values.items() if recent_start <= day <= end}
        baseline_candidates = sorted(
            ((day, value) for day, value in all_values.items() if day < recent_start), reverse=True
        )[:28]
        baseline_values = [value for _, value in baseline_candidates]
        recent_values = list(recent.values())
        recent_value = _period_value(recent_values, definition.period_aggregation)
        if definition.period_aggregation == "sum":
            # Weekly totals need a weekly-sized reference, while coverage and baseline
            # eligibility remain based on the preceding 28 valid daily observations.
            comparison_values = [value * days for value in baseline_values]
        else:
            comparison_values = baseline_values
        baseline_median = float(median(comparison_values)) if len(baseline_values) >= 14 else None
        baseline_p10 = _percentile(comparison_values, 10) if len(baseline_values) >= 14 else None
        baseline_p90 = _percentile(comparison_values, 90) if len(baseline_values) >= 14 else None
        difference = recent_value - baseline_median if recent_value is not None and baseline_median is not None else None
        difference_percent = (
            difference / baseline_median * 100 if difference is not None and baseline_median not in (None, 0) else None
        )
        if recent_value is None:
            direction = "unavailable"
            description = "No data"
        elif baseline_median is None:
            direction = "unavailable"
            description = f"{len(baseline_values)}/14 days needed"
        elif baseline_p10 is not None and recent_value < baseline_p10:
            direction = "below"
            description = self._difference_text(definition, recent_value, baseline_median, "below")
        elif baseline_p90 is not None and recent_value > baseline_p90:
            direction = "above"
            description = self._difference_text(definition, recent_value, baseline_median, "above")
        else:
            direction = "within"
            description = "Usual range"
        series = [
            SeriesPoint(date=recent_start + timedelta(days=index), value=recent.get(recent_start + timedelta(days=index)), covered=(recent_start + timedelta(days=index)) in recent)
            for index in range(days)
        ]
        return MetricSummary(
            key=key,
            label=definition.label,
            value=round(recent_value, 2) if recent_value is not None else None,
            unit=definition.unit,
            comparison=Comparison(
                recent_value=recent_value,
                baseline_median=baseline_median,
                baseline_p10=baseline_p10,
                baseline_p90=baseline_p90,
                difference=difference,
                difference_percent=difference_percent,
                baseline_days=len(baseline_values),
                direction=direction,
                description=description,
            ),
            series=series,
            coverage=_coverage(len(recent), days),
        )

    @staticmethod
    def _difference_text(metric: MetricDefinition, value: float, baseline: float, direction: str) -> str:
        delta = abs(value - baseline)
        change = "more" if direction == "above" else "less"
        if metric.key == "workouts":
            return f"{delta:.1f} workouts {change} than usual"
        if metric.unit.startswith("hr"):
            return f"{delta:.1f} hr {change} than usual"
        return f"{delta:.1f} {metric.unit.split('/')[0]} {change} than usual"

    def home(self, as_of: date | None = None, now: datetime | None = None) -> HomeResponse:
        current_time = now.astimezone(self.settings.tz) if now else datetime.now(self.settings.tz)
        end = as_of or current_time.date()
        keys = ("steps", "sleep_duration", "calories", "weight", "resting_hr", "hrv", "spo2")
        metrics = [self._metric_summary(key, end, 7) for key in keys]
        today_metrics = [
            self._metric_summary(key, end, 1)
            for key in ("steps", "active_minutes", "zone_minutes", "workouts", "calories", "hydration")
        ]
        overnight_metrics = [
            self._metric_summary(key, end, 1)
            for key in ("sleep_duration", "resting_hr", "hrv", "spo2", "respiratory_rate")
        ]
        readiness = self._readiness(end)
        sentence = self._sentence(metrics)
        covered_days = len({point.date for metric in metrics for point in metric.series if point.covered})
        start = end - timedelta(days=6)
        report = self._weekly_report(end, sentence, metrics)
        sources = self._sources()
        sync = dict(self.db.row(
            "SELECT started_at, finished_at, status, trigger, details FROM sync_runs ORDER BY started_at DESC LIMIT 1"
        ) or {"status": "not_started"})
        sync["configured"] = bool(self.settings.google_credentials and self.settings.google_token)
        readiness = self._readiness_status(readiness, end, current_time, sync, sources)
        return HomeResponse(
            generated_at=datetime.now(UTC),
            as_of=end,
            sentence=sentence,
            metrics=metrics,
            coverage=_coverage(min(covered_days, 7), 7),
            provenance=Provenance(
                sources=sources, date_start=start, date_end=end, method_version=METHOD_VERSION
            ),
            report=report,
            sync=sync,
            readiness=readiness,
            readiness_history=[
                DailyReadiness(date=day, score=result.score, label=result.label)
                for day in (end - timedelta(days=offset) for offset in range(6, -1, -1))
                for result in [self._readiness(day)]
            ],
            today_metrics=today_metrics,
            overnight_metrics=overnight_metrics,
        )

    @staticmethod
    def _readiness_status(
        readiness: ReadinessScore,
        day: date,
        now: datetime,
        sync: dict,
        sources: list[str],
    ) -> ReadinessScore:
        if readiness.score is not None:
            return readiness
        if readiness.baseline_days < 14:
            return readiness.model_copy(update={"message": "Building your baseline"})

        missing = {"sleep_duration", "hrv", "resting_hr"} - {
            component.key for component in readiness.components
        }
        sleep_missing = "sleep_duration" in missing
        if day < now.date():
            message = "No sleep data for that night." if sleep_missing else "Some recovery data is missing for that night."
        elif day > now.date():
            message = "No data for this date yet."
        elif sync.get("status") == "running" or now.hour < 12:
            message = "Waiting for last night's sleep data." if sleep_missing else "Waiting for last night's recovery data."
        else:
            device = HealthAnalysis._wearable_name(sources)
            missing_text = "No sleep data came through last night." if sleep_missing else "Some recovery data is missing."
            message = f"{missing_text} Wear your {device} tonight."
        return readiness.model_copy(update={"message": message})

    @staticmethod
    def _wearable_name(sources: list[str]) -> str:
        for source in sources:
            if source.upper().startswith("FITBIT:") and source.partition(":")[2].strip():
                return source.partition(":")[2].strip()
        if any(source.upper().startswith("FITBIT") for source in sources):
            return "Fitbit"
        return "tracker"

    def _readiness(self, day: date) -> ReadinessScore:
        specifications = (
            ("sleep_duration", 0.4, False),
            ("hrv", 0.3, False),
            ("resting_hr", 0.3, True),
        )
        components: list[ReadinessComponent] = []
        baseline_counts: list[int] = []
        missing_signals: list[str] = []
        needs_history = False
        weighted_score = 0.0
        for key, weight, lower_is_better in specifications:
            definition = METRICS[key]
            values = self._daily_values(definition, day - timedelta(days=180), day)
            current = values.get(day)
            baseline = [
                value for _, value in sorted(
                    ((candidate_day, value) for candidate_day, value in values.items() if candidate_day < day),
                    reverse=True,
                )[:28]
            ]
            baseline_counts.append(len(baseline))
            if current is None:
                missing_signals.append({
                    "sleep_duration": "sleep", "hrv": "HRV", "resting_hr": "resting heart rate",
                }[key])
                continue
            if len(baseline) < 14:
                needs_history = True
                continue
            rank = _percentile_rank(current, baseline)
            favorable_rank = 100 - rank if lower_is_better else rank
            component_score = round(20 + favorable_rank * 0.8)
            weighted_score += component_score * weight
            components.append(
                ReadinessComponent(
                    key=key,
                    label=definition.label,
                    value=round(current, 2),
                    unit=definition.unit.split("/")[0],
                    score=component_score,
                    baseline_median=round(float(median(baseline)), 2),
                    baseline_days=len(baseline),
                )
            )
        baseline_days = min(baseline_counts, default=0)
        if len(components) != len(specifications):
            if needs_history:
                message = f"{max(0, 14 - baseline_days)} more baseline days needed"
            else:
                missing = ", ".join(missing_signals[:-1])
                if len(missing_signals) > 1:
                    missing = f"{missing} and {missing_signals[-1]}"
                else:
                    missing = missing_signals[0] if missing_signals else "Overnight data"
                message = f"Waiting for {missing}"
            return ReadinessScore(
                score=None,
                label="unavailable",
                message=message,
                components=components,
                baseline_days=baseline_days,
                method_version=READINESS_METHOD_VERSION,
            )
        score = round(weighted_score)
        label = "low" if score < 30 else "moderate" if score < 65 else "high"
        return ReadinessScore(
            score=score,
            label=label,
            message=f"{label.capitalize()} readiness",
            components=components,
            baseline_days=baseline_days,
            method_version=READINESS_METHOD_VERSION,
        )

    def _sentence(self, metrics: list[MetricSummary]) -> str:
        available = [metric for metric in metrics if metric.comparison.direction != "unavailable"]
        if not available:
            return "More data is needed before comparisons appear."
        notable = [metric for metric in available if metric.comparison.direction in ("above", "below")]
        if not notable:
            return "Similar to your last four weeks."
        fragments = [
            f"{metric.label} was {'higher' if metric.comparison.direction == 'above' else 'lower'} than usual."
            for metric in notable[:2]
        ]
        return " ".join(fragments)

    def domain(self, domain: Literal["fitness", "sleep", "nutrition"], range_name: RangeName) -> DomainResponse:
        days = {"7d": 7, "28d": 28, "90d": 90}[range_name]
        end = datetime.now(self.settings.tz).date()
        metrics = [self._metric_summary(key, end, days) for key in DOMAIN_KEYS[domain]]
        covered = len({point.date for metric in metrics for point in metric.series if point.covered})
        summary = self._domain_sentence(domain, metrics)
        details: dict = {}
        if domain == "sleep":
            details["selected_night"] = self._latest_sleep()
        elif domain == "fitness":
            details["recent_sessions"] = [item.model_dump(mode="json") for item in self.sessions("exercise", 8).sessions]
        elif domain == "nutrition":
            details["confirmed_meals"] = self.db.row(
                "SELECT count(*) AS count FROM nutrition_entries WHERE confirmed"
            )["count"]
        return DomainResponse(
            generated_at=datetime.now(UTC),
            domain=domain,
            range=range_name,
            summary=summary,
            metrics=metrics,
            coverage=_coverage(min(covered, days), days),
            provenance=Provenance(
                sources=self._sources(), date_start=end - timedelta(days=days - 1), date_end=end,
                method_version=METHOD_VERSION,
            ),
            details=details,
        )

    @staticmethod
    def _domain_sentence(domain: str, metrics: list[MetricSummary]) -> str:
        available = [metric for metric in metrics if metric.value is not None]
        if not available:
            return f"No {domain} data for this period."
        notable = next(
            (metric for metric in available if metric.comparison.direction in ("above", "below")), None
        )
        if notable:
            change = "higher" if notable.comparison.direction == "above" else "lower"
            return f"{notable.label} was {change} than usual."
        return "Similar to your last four weeks."

    def _latest_sleep(self) -> dict | None:
        rows = self.db.rows(
            """
            SELECT start_at, end_at, duration_minutes, awake_minutes, light_minutes, deep_minutes, rem_minutes
            FROM sleep_sessions ORDER BY end_at DESC LIMIT 28
            """
        )
        if not rows:
            return None
        latest = dict(rows[0])
        bedtimes: list[float] = []
        wake_times: list[float] = []
        for row in rows:
            bedtime = row["start_at"].astimezone(self.settings.tz)
            wake = row["end_at"].astimezone(self.settings.tz)
            bedtimes.append(float((bedtime.hour * 60 + bedtime.minute - 720) % 1440))
            wake_times.append(float(wake.hour * 60 + wake.minute))
        bedtime_median = median(bedtimes)
        wake_median = median(wake_times)
        latest_bedtime = bedtimes[0]
        latest_wake = wake_times[0]
        latest["timing"] = {
            "bedtime": rows[0]["start_at"].astimezone(self.settings.tz).isoformat(),
            "wake_time": rows[0]["end_at"].astimezone(self.settings.tz).isoformat(),
            "bedtime_difference_minutes": round(
                min(abs(latest_bedtime - bedtime_median), 1440 - abs(latest_bedtime - bedtime_median))
            ),
            "wake_difference_minutes": round(
                min(abs(latest_wake - wake_median), 1440 - abs(latest_wake - wake_median))
            ),
            "baseline_nights": len(rows),
        }
        heart_rate = self.db.rows(
            """
            SELECT time_bucket(INTERVAL '5 minutes', measured_at) AS measured_at,
                   median(value) AS value
            FROM metric_samples
            WHERE data_type='heart-rate' AND measured_at BETWEEN ? AND ?
            GROUP BY 1 ORDER BY 1
            """,
            [rows[0]["start_at"], rows[0]["end_at"]],
        )
        latest["overnight_heart_rate"] = [
            {"measured_at": item["measured_at"].isoformat(), "value": round(float(item["value"]), 1)}
            for item in heart_rate
        ]
        return latest

    def sessions(self, kind: Literal["sleep", "exercise"] | None = None, limit: int = 50) -> SessionsResponse:
        result: list[SessionSummary] = []
        if kind in (None, "sleep"):
            for row in self.db.rows(
                "SELECT * FROM sleep_sessions ORDER BY start_at DESC LIMIT ?", [limit]
            ):
                result.append(
                    SessionSummary(
                        id=row["id"], kind="sleep", start_at=row["start_at"], end_at=row["end_at"],
                        title="Sleep", duration_minutes=row["duration_minutes"],
                        details={
                            "awake_minutes": row["awake_minutes"], "light_minutes": row["light_minutes"],
                            "deep_minutes": row["deep_minutes"], "rem_minutes": row["rem_minutes"],
                        },
                        provenance=Provenance(
                            sources=[row["source"]], date_start=row["start_at"].date(),
                            date_end=row["end_at"].date(), method_version="normalized-record-v1",
                        ),
                    )
                )
        if kind in (None, "exercise"):
            for row in self.db.rows(
                "SELECT * FROM exercise_sessions ORDER BY start_at DESC LIMIT ?", [limit]
            ):
                result.append(
                    SessionSummary(
                        id=row["id"], kind="exercise", start_at=row["start_at"], end_at=row["end_at"],
                        title=row["display_name"], duration_minutes=row["duration_minutes"],
                        details={
                            "exercise_type": row["exercise_type"], "calories_kcal": row["calories_kcal"],
                            "average_heart_rate": row["average_heart_rate"],
                            "active_zone_minutes": row["active_zone_minutes"],
                            "zone_durations": (
                                json.loads(row["zone_durations"] or "{}")
                                if isinstance(row["zone_durations"], str)
                                else row["zone_durations"] or {}
                            ),
                        },
                        provenance=Provenance(
                            sources=[row["source"]], date_start=row["start_at"].date(),
                            date_end=row["end_at"].date(), method_version="normalized-record-v1",
                        ),
                    )
                )
        result.sort(key=lambda item: item.start_at, reverse=True)
        result = result[:limit]
        end = result[0].start_at.date() if result else None
        start = result[-1].start_at.date() if result else None
        return SessionsResponse(
            generated_at=datetime.now(UTC), sessions=result,
            coverage=_coverage(len(result), limit, "requested sessions"),
            provenance=Provenance(sources=self._sources(), date_start=start, date_end=end, method_version="normalized-record-v1"),
        )

    def session(self, session_id: str) -> SessionSummary | None:
        sessions = self.sessions(None, 500).sessions
        return next((item for item in sessions if item.id == session_id), None)

    def _weekly_report(self, end: date, sentence: str, metrics: list[MetricSummary]) -> WeeklyReport:
        week_start = end - timedelta(days=end.weekday())
        payload = {metric.key: metric.model_dump(mode="json") for metric in metrics}
        generated = datetime.now(UTC)
        self.db.execute(
            """
            INSERT INTO weekly_reports VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (week_start) DO UPDATE SET generated_at=excluded.generated_at,
              method_version=excluded.method_version, summary=excluded.summary, payload=excluded.payload
            """,
            [week_start, generated, METHOD_VERSION, sentence, json_value(payload)],
        )
        return WeeklyReport(
            week_start=week_start, generated_at=generated, method_version=METHOD_VERSION,
            summary=sentence, payload=payload,
        )

    def weekly_reports(self, limit: int = 52) -> WeeklyReportsResponse:
        reports = [
            WeeklyReport(
                week_start=row["week_start"], generated_at=row["generated_at"],
                method_version=row["method_version"], summary=row["summary"],
                payload=json.loads(row["payload"]),
            )
            for row in self.db.rows(
                "SELECT * FROM weekly_reports ORDER BY week_start DESC LIMIT ?", [limit]
            )
        ]
        return WeeklyReportsResponse(generated_at=datetime.now(UTC), reports=reports)

    def _sources(self) -> list[str]:
        rows = self.db.rows(
            """
            SELECT DISTINCT source FROM (
              SELECT source FROM daily_metrics UNION ALL SELECT source FROM metric_samples
              UNION ALL SELECT source FROM metric_intervals UNION ALL SELECT source FROM sleep_sessions
              UNION ALL SELECT source FROM exercise_sessions
            ) WHERE source IS NOT NULL ORDER BY source
            """
        )
        return [row["source"] for row in rows]

    def relationships(self) -> list[RelationshipResult]:
        definitions: tuple[tuple[str, str, str, str, int], ...] = (
            ("sleep_hrv", "Sleep duration vs next-day HRV", "sleep_duration", "hrv", 1),
            ("sleep_rhr", "Sleep duration vs resting heart rate", "sleep_duration", "resting_hr", 0),
            ("load_hrv", "Activity load vs next-day HRV", "zone_minutes", "hrv", 1),
            ("nutrition_weight", "Confirmed nutrition vs weight trend", "calories", "weight", 0),
        )
        end = datetime.now(self.settings.tz).date()
        start = end - timedelta(days=365)
        output: list[RelationshipResult] = []
        for key, label, left_key, right_key, lag in definitions:
            left = self._daily_values(METRICS[left_key], start, end)
            right = self._daily_values(METRICS[right_key], start, end)
            pairs = [
                (value, right[day + timedelta(days=lag)])
                for day, value in left.items() if day + timedelta(days=lag) in right
            ]
            output.append(self._relationship(key, label, pairs, (end - start).days + 1))
        return output

    @staticmethod
    def _relationship(key: str, label: str, pairs: list[tuple[float, float]], possible_days: int) -> RelationshipResult:
        count = len(pairs)
        coverage = count / possible_days if possible_days else 0
        if count < 30:
            return RelationshipResult(
                key=key, label=label, coefficient=None, confidence_low=None, confidence_high=None,
                paired_days=count, coverage=round(coverage, 3), available=False,
                message=f"Needs 30 paired days; {count} are available. Association is not causation.",
            )
        values = np.asarray(pairs, dtype=float)
        coefficient = _spearman(values[:, 0], values[:, 1])
        rng = np.random.default_rng(20260830)
        bootstrapped = []
        for _ in range(1_000):
            indexes = rng.integers(0, count, count)
            candidate = _spearman(values[indexes, 0], values[indexes, 1])
            if not math.isnan(candidate):
                bootstrapped.append(candidate)
        low, high = np.percentile(bootstrapped, [2.5, 97.5]) if bootstrapped else (math.nan, math.nan)
        return RelationshipResult(
            key=key, label=label, coefficient=round(coefficient, 3),
            confidence_low=round(float(low), 3), confidence_high=round(float(high), 3),
            paired_days=count, coverage=round(coverage, 3), available=True,
            message="Spearman correlation with a 95% bootstrap interval. Association is not causation.",
        )


def _rank(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    index = 0
    while index < len(values):
        end = index + 1
        while end < len(values) and values[order[end]] == values[order[index]]:
            end += 1
        ranks[order[index:end]] = (index + end - 1) / 2 + 1
        index = end
    return ranks


def _spearman(left: np.ndarray, right: np.ndarray) -> float:
    left_rank = _rank(left)
    right_rank = _rank(right)
    if np.std(left_rank) == 0 or np.std(right_rank) == 0:
        return math.nan
    return float(np.corrcoef(left_rank, right_rank)[0, 1])
