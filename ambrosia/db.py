from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from .config import Settings, settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_files (
    path VARCHAR PRIMARY KEY,
    data_type VARCHAR NOT NULL,
    sha256 VARCHAR NOT NULL,
    record_count UBIGINT NOT NULL,
    size_bytes UBIGINT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_runs (
    id UUID PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status VARCHAR NOT NULL,
    trigger VARCHAR NOT NULL,
    details JSON
);
CREATE TABLE IF NOT EXISTS sync_type_runs (
    run_id UUID NOT NULL,
    data_type VARCHAR NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status VARCHAR NOT NULL,
    records_seen UBIGINT DEFAULT 0,
    error VARCHAR,
    PRIMARY KEY (run_id, data_type)
);
CREATE TABLE IF NOT EXISTS watermarks (
    data_type VARCHAR PRIMARY KEY,
    watermark TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_metrics (
    record_id VARCHAR PRIMARY KEY,
    day DATE NOT NULL,
    data_type VARCHAR NOT NULL,
    value DOUBLE NOT NULL,
    unit VARCHAR,
    source VARCHAR,
    coverage DOUBLE DEFAULT 1,
    provenance JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS daily_metrics_lookup ON daily_metrics(data_type, day);
CREATE TABLE IF NOT EXISTS metric_samples (
    record_id VARCHAR PRIMARY KEY,
    measured_at TIMESTAMPTZ NOT NULL,
    data_type VARCHAR NOT NULL,
    value DOUBLE NOT NULL,
    unit VARCHAR,
    source VARCHAR,
    provenance JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS metric_samples_lookup ON metric_samples(data_type, measured_at);
CREATE TABLE IF NOT EXISTS metric_intervals (
    record_id VARCHAR PRIMARY KEY,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    data_type VARCHAR NOT NULL,
    value DOUBLE NOT NULL,
    unit VARCHAR,
    source VARCHAR,
    provenance JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS metric_intervals_lookup ON metric_intervals(data_type, start_at);
CREATE TABLE IF NOT EXISTS sleep_sessions (
    id VARCHAR PRIMARY KEY,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    duration_minutes DOUBLE NOT NULL,
    awake_minutes DOUBLE,
    light_minutes DOUBLE,
    deep_minutes DOUBLE,
    rem_minutes DOUBLE,
    source VARCHAR,
    stages JSON,
    provenance JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS sleep_sessions_time ON sleep_sessions(start_at);
CREATE TABLE IF NOT EXISTS exercise_sessions (
    id VARCHAR PRIMARY KEY,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    exercise_type VARCHAR NOT NULL,
    display_name VARCHAR NOT NULL,
    duration_minutes DOUBLE NOT NULL,
    calories_kcal DOUBLE,
    average_heart_rate DOUBLE,
    active_zone_minutes DOUBLE,
    zone_durations JSON,
    source VARCHAR,
    provenance JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS exercise_sessions_time ON exercise_sessions(start_at);
CREATE SEQUENCE IF NOT EXISTS nutrition_entry_id START 1;
CREATE TABLE IF NOT EXISTS nutrition_entries (
    id BIGINT PRIMARY KEY DEFAULT nextval('nutrition_entry_id'),
    record_id VARCHAR UNIQUE NOT NULL,
    eaten_at TIMESTAMPTZ NOT NULL,
    meal_type VARCHAR,
    description VARCHAR,
    calories_low DOUBLE,
    calories_high DOUBLE,
    protein_low DOUBLE,
    protein_high DOUBLE,
    carbs_low DOUBLE,
    carbs_high DOUBLE,
    fat_low DOUBLE,
    fat_high DOUBLE,
    sodium_low DOUBLE,
    sodium_high DOUBLE,
    water_ml DOUBLE,
    ingredients JSON,
    confidence DOUBLE,
    confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    thumbnail_path VARCHAR,
    source VARCHAR,
    provenance JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS nutrition_entries_time ON nutrition_entries(eaten_at);
CREATE TABLE IF NOT EXISTS nutrition_drafts (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    status VARCHAR NOT NULL,
    note VARCHAR,
    image_path VARCHAR NOT NULL,
    image_sha256 VARCHAR NOT NULL,
    analysis JSON,
    confirmed_entry_id BIGINT
);
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY,
    updated_at TIMESTAMPTZ NOT NULL,
    goal VARCHAR,
    time_horizon VARCHAR,
    training_frequency VARCHAR,
    dietary_preferences JSON,
    constraints JSON,
    timezone VARCHAR NOT NULL,
    distance_unit VARCHAR NOT NULL,
    weight_unit VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS weekly_reports (
    week_start DATE PRIMARY KEY,
    generated_at TIMESTAMPTZ NOT NULL,
    method_version VARCHAR NOT NULL,
    summary VARCHAR NOT NULL,
    payload JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS assistant_threads (
    id UUID PRIMARY KEY,
    provider VARCHAR NOT NULL,
    provider_thread_id VARCHAR,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    title VARCHAR,
    metadata JSON
);
CREATE TABLE IF NOT EXISTS assistant_messages (
    id UUID PRIMARY KEY,
    thread_id UUID NOT NULL,
    role VARCHAR NOT NULL,
    text VARCHAR NOT NULL,
    image_draft_id UUID,
    created_at TIMESTAMPTZ NOT NULL,
    provider_item_id VARCHAR,
    UNIQUE(thread_id, provider_item_id)
);
CREATE INDEX IF NOT EXISTS assistant_messages_thread_time
ON assistant_messages(thread_id, created_at);
"""


class Database:
    def __init__(self, app_settings: Settings = settings):
        self.settings = app_settings
        self.settings.ensure_directories()
        self._lock = threading.RLock()
        self._connection = duckdb.connect(str(self.settings.database_path))
        self._connection.execute("SET TimeZone='UTC'")
        # Leave headroom for Python, Arrow batches, and the web process on a small always-on Mac.
        self._connection.execute("SET memory_limit='700MiB'")
        temporary = str(self.settings.temp_dir).replace("'", "''")
        self._connection.execute(f"SET temp_directory='{temporary}'")
        self._connection.execute(SCHEMA)
        self._seed_profile()

    def _seed_profile(self) -> None:
        self._connection.execute(
            """
            INSERT INTO profile VALUES (1, ?, NULL, NULL, NULL, '[]', '[]', ?, 'miles', 'lb')
            ON CONFLICT DO NOTHING
            """,
            [datetime.now(UTC), self.settings.timezone],
        )

    @contextlib.contextmanager
    def transaction(self) -> Iterator[duckdb.DuckDBPyConnection]:
        with self._lock:
            self._connection.execute("BEGIN TRANSACTION")
            try:
                yield self._connection
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            else:
                self._connection.execute("COMMIT")

    def execute(self, query: str, parameters: list | tuple | None = None):
        with self._lock:
            return self._connection.execute(query, parameters or [])

    def rows(self, query: str, parameters: list | tuple | None = None) -> list[dict]:
        with self._lock:
            cursor = self._connection.execute(query, parameters or [])
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def row(self, query: str, parameters: list | tuple | None = None) -> dict | None:
        rows = self.rows(query, parameters)
        return rows[0] if rows else None

    def export_parquet(self) -> list[Path]:
        exported: list[Path] = []
        tables = (
            "daily_metrics",
            "metric_samples",
            "metric_intervals",
            "sleep_sessions",
            "exercise_sessions",
            "nutrition_entries",
            "weekly_reports",
        )
        with self._lock:
            for table in tables:
                target = self.settings.parquet_dir / f"{table}.parquet"
                escaped = str(target).replace("'", "''")
                self._connection.execute(
                    f"COPY (SELECT * FROM {table}) TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)"
                )
                exported.append(target)
        return exported

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def json_value(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)
