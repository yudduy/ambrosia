from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from ambrosia.analysis import HealthAnalysis, _spearman
from ambrosia.db import json_value
import numpy as np


def seed_days(database, end: date, count: int = 42):
    for offset in range(count):
        day = end - timedelta(days=count - offset - 1)
        for data_type, value, unit in (
            ("daily-resting-heart-rate", 62 - offset * 0.05, "bpm"),
            ("daily-heart-rate-variability", 45 + offset * 0.4, "ms"),
            ("daily-oxygen-saturation", 96 + (offset % 3) * 0.1, "%"),
        ):
            database.execute(
                "INSERT INTO daily_metrics VALUES (?, ?, ?, ?, ?, 'FITBIT:Charge 6', 1, ?)",
                [f"{data_type}-{day}", day, data_type, value, unit, json_value({"data_type": data_type})],
            )
        start = datetime(day.year, day.month, day.day, 16, tzinfo=UTC)
        database.execute(
            "INSERT INTO metric_intervals VALUES (?, ?, ?, 'steps', ?, 'count', 'FITBIT:Charge 6', ?)",
            [f"steps-{day}", start, start + timedelta(minutes=1), 7000 + offset * 100, json_value({"data_type": "steps"})],
        )
        database.execute(
            "INSERT INTO sleep_sessions VALUES (?, ?, ?, 450, 20, 240, 100, 90, 'FITBIT:Charge 6', '[]', ?)",
            [f"sleep-{day}", start - timedelta(hours=8), start, json_value({"data_type": "sleep"})],
        )


def test_home_uses_28_valid_day_baseline(database, app_settings):
    end = date(2026, 8, 29)
    seed_days(database, end)
    result = HealthAnalysis(database, app_settings).home(end)
    steps = next(metric for metric in result.metrics if metric.key == "steps")
    assert steps.comparison.baseline_days == 28
    assert steps.coverage.covered_days == 7
    assert result.provenance.date_start == date(2026, 8, 23)
    assert result.sentence
    assert result.readiness.score == 84
    assert result.readiness.label == "high"
    assert [component.key for component in result.readiness.components] == [
        "sleep_duration", "hrv", "resting_hr",
    ]
    assert len(result.readiness_history) == 7
    assert next(metric for metric in result.today_metrics if metric.key == "steps").value == 11100


def test_readiness_waits_for_all_three_personal_baselines(database, app_settings):
    end = date(2026, 8, 29)
    seed_days(database, end, 10)
    result = HealthAnalysis(database, app_settings).home(end)
    assert result.readiness.score is None
    assert result.readiness.label == "unavailable"
    assert result.readiness.baseline_days == 9
    assert result.readiness.message == "Building your baseline"


def test_readiness_waits_for_a_morning_sync(database, app_settings):
    end = date(2026, 8, 30)
    seed_days(database, end - timedelta(days=1))
    morning = datetime(2026, 8, 30, 9, tzinfo=app_settings.tz)

    result = HealthAnalysis(database, app_settings).home(end, now=morning)

    assert result.readiness.message == "Waiting for last night's sleep data."


def test_readiness_names_the_wearable_when_sleep_never_arrives(database, app_settings):
    end = date(2026, 8, 30)
    seed_days(database, end - timedelta(days=1))
    evening = datetime(2026, 8, 30, 20, tzinfo=app_settings.tz)

    result = HealthAnalysis(database, app_settings).home(end, now=evening)

    assert result.readiness.message == (
        "No sleep data came through last night. Wear your Charge 6 tonight."
    )


def test_baseline_withholds_conclusion_under_14_days(database, app_settings):
    end = date(2026, 8, 29)
    seed_days(database, end, 10)
    result = HealthAnalysis(database, app_settings)._metric_summary("steps", end, 7)
    assert result.comparison.direction == "unavailable"
    assert result.comparison.description == "3/14 days needed"


def test_weekly_workout_total_uses_weekly_scaled_daily_baseline(database, app_settings):
    end = date(2026, 8, 29)
    for offset in range(35):
        day = end - timedelta(days=34 - offset)
        start = datetime(day.year, day.month, day.day, 16, tzinfo=UTC)
        database.execute(
            """
            INSERT INTO exercise_sessions
              (id, start_at, end_at, exercise_type, display_name, duration_minutes, source, provenance)
            VALUES (?, ?, ?, 'run', 'Run', 30, 'FITBIT', ?)
            """,
            [f"exercise-{day}", start, start + timedelta(minutes=30), json_value({"data_type": "exercise"})],
        )
    result = HealthAnalysis(database, app_settings)._metric_summary("workouts", end, 7)
    assert result.value == 7
    assert result.comparison.baseline_median == 7
    assert result.comparison.direction == "within"


def test_spearman_handles_ties_and_monotonic_values():
    assert _spearman(np.array([1, 2, 3, 4]), np.array([2, 4, 6, 8])) == 1
    assert _spearman(np.array([1, 1, 2, 3]), np.array([4, 4, 2, 1])) < -0.99
