from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from ambrosia.importer import (
    canonical_hash,
    iter_export_points,
    map_daily,
    map_exercise,
    map_interval,
    map_sample,
    map_sleep,
)


def point_source() -> dict:
    return {"dataSource": {"platform": "FITBIT", "device": {"displayName": "Charge 6"}}}


def test_streams_line_oriented_export(tmp_path: Path):
    path = tmp_path / "steps.json"
    path.write_text('{"dataPoints":[\n{"steps":{"count":"1"}},\n{"steps":{"count":"2"}}\n]}\n')
    assert [item["steps"]["count"] for item in iter_export_points(path)] == ["1", "2"]


def test_named_and_unnamed_hashes_are_stable():
    named = {"name": "users/private/dataTypes/sleep/dataPoints/abc", "sleep": {}}
    assert canonical_hash("sleep", named) == canonical_hash("sleep", named)
    assert "private" not in canonical_hash("sleep", named)
    assert canonical_hash("steps", {"steps": {"count": "1"}}) != canonical_hash(
        "steps", {"steps": {"count": "2"}}
    )


def test_maps_daily_sample_and_interval():
    daily = point_source() | {
        "dailyRestingHeartRate": {"date": {"year": 2026, "month": 8, "day": 29}, "beatsPerMinute": "55"}
    }
    sample = point_source() | {
        "heartRate": {"sampleTime": {"physicalTime": "2026-08-29T20:26:49Z"}, "beatsPerMinute": "64"}
    }
    interval = point_source() | {
        "steps": {
            "interval": {"startTime": "2026-08-29T20:26:00Z", "endTime": "2026-08-29T20:27:00Z"},
            "count": "8",
        }
    }
    assert map_daily("daily-resting-heart-rate", daily, "hash")[1:5] == (
        date(2026, 8, 29), "daily-resting-heart-rate", 55.0, "bpm"
    )
    assert map_sample("heart-rate", sample, "hash")[1:5] == (
        datetime(2026, 8, 29, 20, 26, 49, tzinfo=UTC), "heart-rate", 64.0, "bpm"
    )
    assert map_interval("steps", interval, "hash")[3:6] == ("steps", 8.0, "count")


def test_maps_sleep_stages_and_exercise():
    sleep = point_source() | {
        "name": "sleep-1",
        "sleep": {
            "interval": {"startTime": "2026-08-29T08:00:00Z", "endTime": "2026-08-29T16:00:00Z"},
            "stages": [
                {"startTime": "2026-08-29T08:00:00Z", "endTime": "2026-08-29T10:00:00Z", "type": "DEEP"},
                {"startTime": "2026-08-29T10:00:00Z", "endTime": "2026-08-29T16:00:00Z", "type": "LIGHT"},
            ],
        },
    }
    exercise = point_source() | {
        "name": "exercise-1",
        "exercise": {
            "interval": {"startTime": "2026-08-29T18:00:00Z", "endTime": "2026-08-29T19:00:00Z"},
            "exerciseType": "STRENGTH_TRAINING",
            "displayName": "Strength training",
            "activeDuration": "3600s",
            "metricsSummary": {"caloriesKcal": 300, "activeZoneMinutes": "20"},
        },
    }
    sleep_row = map_sleep("sleep", sleep, "hash")
    exercise_row = map_exercise("exercise", exercise, "hash")
    assert sleep_row[3] == 480
    assert sleep_row[6] == 120
    assert exercise_row[4:9] == ("Strength training", 60.0, 300.0, None, 20.0)

