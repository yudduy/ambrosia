from __future__ import annotations

import hashlib
import gzip
import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import orjson
import pyarrow as pa

from .config import Settings, settings
from .db import Database, json_value


DAILY_TYPES: dict[str, tuple[str, str, str]] = {
    "daily-resting-heart-rate": ("dailyRestingHeartRate", "beatsPerMinute", "bpm"),
    "daily-heart-rate-variability": (
        "dailyHeartRateVariability",
        "averageHeartRateVariabilityMilliseconds",
        "ms",
    ),
    "daily-oxygen-saturation": ("dailyOxygenSaturation", "averagePercentage", "%"),
    "daily-respiratory-rate": ("dailyRespiratoryRate", "breathsPerMinute", "breaths/min"),
    "daily-vo2-max": ("dailyVo2Max", "vo2MillilitersPerMinutePerKilogram", "ml/kg/min"),
}

SAMPLE_TYPES: dict[str, tuple[str, tuple[str, ...], str]] = {
    "heart-rate": ("heartRate", ("beatsPerMinute",), "bpm"),
    "heart-rate-variability": (
        "heartRateVariability",
        ("rootMeanSquareOfSuccessiveDifferencesMilliseconds",),
        "ms",
    ),
    "oxygen-saturation": ("oxygenSaturation", ("percentage",), "%"),
    "weight": ("weight", ("weightGrams",), "g"),
    "body-fat": ("bodyFat", ("percentage",), "%"),
    "altitude": ("altitude", ("meters", "altitudeMeters"), "m"),
}

INTERVAL_TYPES: dict[str, tuple[str, tuple[str, ...], str]] = {
    "steps": ("steps", ("count",), "count"),
    "distance": ("distance", ("millimeters",), "mm"),
    "active-zone-minutes": ("activeZoneMinutes", ("activeZoneMinutes",), "min"),
    "active-energy-burned": ("activeEnergyBurned", ("calories", "kilocalories"), "kcal"),
}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(data_type: str, point: dict[str, Any]) -> str:
    named = point.get("name")
    if named:
        material = f"{data_type}\0{named}".encode()
    else:
        material = data_type.encode() + b"\0" + orjson.dumps(point, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(material).hexdigest()


def iter_export_points(path: Path) -> Iterator[dict[str, Any]]:
    """Stream the collector's line-oriented JSON object without loading the array."""
    opener = gzip.open if path.suffix == ".gz" else Path.open
    with opener(path, "rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            stripped = raw.strip()
            if not stripped or line_number == 1:
                continue
            if stripped in (b"]}", b"]"):
                break
            if stripped.endswith(b","):
                stripped = stripped[:-1]
            if not stripped:
                continue
            value = orjson.loads(stripped)
            if not isinstance(value, dict):
                raise ValueError(f"Expected an object at {path.name}:{line_number}")
            yield value


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.removesuffix("s")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _first_float(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _float(payload.get(key))
        if value is not None:
            return value
    return None


def _source(point: dict[str, Any]) -> str:
    source = point.get("dataSource") or {}
    platform = source.get("platform", "UNKNOWN")
    device = (source.get("device") or {}).get("displayName")
    return f"{platform}:{device}" if device else str(platform)


def _date(payload: dict[str, Any]) -> date | None:
    parts = payload.get("date")
    if not parts:
        return None
    try:
        return date(int(parts["year"]), int(parts["month"]), int(parts["day"]))
    except (KeyError, TypeError, ValueError):
        return None


def _time(container: dict[str, Any], key: str = "sampleTime") -> datetime | None:
    value = (container.get(key) or {}).get("physicalTime")
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _interval(container: dict[str, Any]) -> tuple[datetime, datetime] | None:
    value = container.get("interval") or {}
    start = value.get("startTime")
    end = value.get("endTime")
    if not start or not end:
        return None
    return (
        datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(UTC),
        datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(UTC),
    )


def _provenance(data_type: str, file_hash: str, point: dict[str, Any]) -> str:
    source = point.get("dataSource") or {}
    return json_value(
        {
            "data_type": data_type,
            "raw_sha256": file_hash,
            "platform": source.get("platform"),
            "recording_method": source.get("recordingMethod"),
        }
    )


def map_daily(
    data_type: str, point: dict[str, Any], file_hash: str
) -> tuple[str, date, str, float, str, str, float, str] | None:
    if data_type not in DAILY_TYPES:
        return None
    payload_key, value_key, unit = DAILY_TYPES[data_type]
    payload = point.get(payload_key) or {}
    day = _date(payload)
    value = _float(payload.get(value_key))
    if day is None or value is None:
        return None
    return (
        canonical_hash(data_type, point),
        day,
        data_type,
        value,
        unit,
        _source(point),
        1.0,
        _provenance(data_type, file_hash, point),
    )


def map_sample(
    data_type: str, point: dict[str, Any], file_hash: str
) -> tuple[str, datetime, str, float, str, str, str] | None:
    if data_type not in SAMPLE_TYPES:
        return None
    payload_key, value_keys, unit = SAMPLE_TYPES[data_type]
    payload = point.get(payload_key) or {}
    measured_at = _time(payload)
    value = _first_float(payload, value_keys)
    if measured_at is None or value is None:
        return None
    return (
        canonical_hash(data_type, point),
        measured_at,
        data_type,
        value,
        unit,
        _source(point),
        _provenance(data_type, file_hash, point),
    )


def map_interval(
    data_type: str, point: dict[str, Any], file_hash: str
) -> tuple[str, datetime, datetime, str, float, str, str, str] | None:
    if data_type == "active-minutes":
        payload = point.get("activeMinutes") or {}
        value = sum(
            _float(item.get("activeMinutes")) or 0
            for item in payload.get("activeMinutesByActivityLevel", [])
        )
        unit = "min"
    elif data_type in INTERVAL_TYPES:
        payload_key, value_keys, unit = INTERVAL_TYPES[data_type]
        payload = point.get(payload_key) or {}
        value = _first_float(payload, value_keys)
    else:
        return None
    interval = _interval(payload)
    if interval is None or value is None:
        return None
    return (
        canonical_hash(data_type, point),
        interval[0],
        interval[1],
        data_type,
        float(value),
        unit,
        _source(point),
        _provenance(data_type, file_hash, point),
    )


def map_sleep(data_type: str, point: dict[str, Any], file_hash: str) -> tuple | None:
    if data_type != "sleep":
        return None
    payload = point.get("sleep") or {}
    interval = _interval(payload)
    if interval is None:
        return None
    totals: defaultdict[str, float] = defaultdict(float)
    for stage in payload.get("stages", []):
        start = stage.get("startTime")
        end = stage.get("endTime")
        if not start or not end:
            continue
        start_at = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_at = datetime.fromisoformat(end.replace("Z", "+00:00"))
        totals[str(stage.get("type", "UNKNOWN"))] += (end_at - start_at).total_seconds() / 60
    duration = (interval[1] - interval[0]).total_seconds() / 60
    return (
        canonical_hash(data_type, point),
        interval[0],
        interval[1],
        duration,
        totals.get("AWAKE"),
        totals.get("LIGHT"),
        totals.get("DEEP"),
        totals.get("REM"),
        _source(point),
        json_value(payload.get("stages", [])),
        _provenance(data_type, file_hash, point),
    )


def map_exercise(data_type: str, point: dict[str, Any], file_hash: str) -> tuple | None:
    if data_type != "exercise":
        return None
    payload = point.get("exercise") or {}
    interval = _interval(payload)
    if interval is None:
        return None
    metrics = payload.get("metricsSummary") or {}
    duration = _float(payload.get("activeDuration"))
    if duration is None:
        duration = (interval[1] - interval[0]).total_seconds()
    return (
        canonical_hash(data_type, point),
        interval[0],
        interval[1],
        str(payload.get("exerciseType", "UNKNOWN")),
        str(payload.get("displayName") or payload.get("exerciseType") or "Workout"),
        duration / 60,
        _float(metrics.get("caloriesKcal")),
        _float(metrics.get("averageHeartRateBeatsPerMinute")),
        _float(metrics.get("activeZoneMinutes")),
        json_value(metrics.get("heartRateZoneDurations") or {}),
        _source(point),
        _provenance(data_type, file_hash, point),
    )


def _quantity(payload: dict[str, Any] | None, *keys: str) -> float | None:
    payload = payload or {}
    return _first_float(payload, tuple(keys))


def map_nutrition(data_type: str, point: dict[str, Any], file_hash: str) -> tuple | None:
    if data_type == "nutrition-log":
        payload = point.get("nutritionLog") or {}
        interval = _interval(payload)
        if interval is None:
            return None
        nutrients = {
            str(item.get("nutrient")): _quantity(item.get("quantity"), "grams")
            for item in payload.get("nutrients", [])
        }
        protein = nutrients.get("PROTEIN")
        sodium_g = nutrients.get("SODIUM")
        calories = _quantity(payload.get("energy"), "kilocalories", "kcalories", "calories")
        carbs = _quantity(payload.get("totalCarbohydrate"), "grams")
        fat = _quantity(payload.get("totalFat"), "grams")
        description = payload.get("foodDisplayName") or "Imported meal"
        meal_type = payload.get("mealType")
        water_ml = None
        ingredients = [description]
    elif data_type == "hydration-log":
        payload = point.get("hydrationLog") or {}
        interval = _interval(payload)
        if interval is None:
            return None
        amount = payload.get("amountConsumed") or {}
        water_ml = _quantity(amount, "milliliters")
        if water_ml is None:
            liters = _quantity(amount, "liters")
            water_ml = liters * 1000 if liters is not None else None
        calories = protein = carbs = fat = sodium_g = None
        description = "Imported hydration"
        meal_type = "HYDRATION"
        ingredients = []
    else:
        return None
    return (
        canonical_hash(data_type, point), interval[0], meal_type, description,
        calories, calories, protein, protein, carbs, carbs, fat, fat,
        sodium_g * 1000 if sodium_g is not None else None,
        sodium_g * 1000 if sodium_g is not None else None,
        water_ml, json_value(ingredients), 1.0, True, None, _source(point),
        _provenance(data_type, file_hash, point),
    )


def _insert_batch(connection, table: str, columns: tuple[str, ...], rows: list[tuple]) -> None:
    if not rows:
        return
    arrays = {name: [row[index] for row in rows] for index, name in enumerate(columns)}
    arrow_table = pa.table(arrays)
    connection.register("ambrosia_import_batch", arrow_table)
    names = ", ".join(columns)
    connection.execute(
        f"INSERT OR IGNORE INTO {table} ({names}) SELECT {names} FROM ambrosia_import_batch"
    )
    connection.unregister("ambrosia_import_batch")


TABLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "daily": (
        "daily_metrics",
        ("record_id", "day", "data_type", "value", "unit", "source", "coverage", "provenance"),
    ),
    "sample": (
        "metric_samples",
        ("record_id", "measured_at", "data_type", "value", "unit", "source", "provenance"),
    ),
    "interval": (
        "metric_intervals",
        ("record_id", "start_at", "end_at", "data_type", "value", "unit", "source", "provenance"),
    ),
    "sleep": (
        "sleep_sessions",
        (
            "id", "start_at", "end_at", "duration_minutes", "awake_minutes", "light_minutes",
            "deep_minutes", "rem_minutes", "source", "stages", "provenance",
        ),
    ),
    "exercise": (
        "exercise_sessions",
        (
            "id", "start_at", "end_at", "exercise_type", "display_name", "duration_minutes",
            "calories_kcal", "average_heart_rate", "active_zone_minutes", "zone_durations",
            "source", "provenance",
        ),
    ),
    "nutrition": (
        "nutrition_entries",
        (
            "record_id", "eaten_at", "meal_type", "description", "calories_low", "calories_high",
            "protein_low", "protein_high", "carbs_low", "carbs_high", "fat_low", "fat_high",
            "sodium_low", "sodium_high", "water_ml", "ingredients", "confidence", "confirmed",
            "thumbnail_path", "source", "provenance",
        ),
    ),
}


class ExportImporter:
    def __init__(self, database: Database, app_settings: Settings = settings, batch_size: int = 20_000):
        self.database = database
        self.settings = app_settings
        self.batch_size = batch_size

    def import_directory(self, export_dir: Path) -> dict[str, Any]:
        export_dir = export_dir.expanduser().resolve()
        if not export_dir.is_dir():
            raise FileNotFoundError(export_dir)
        files = sorted(path for path in export_dir.glob("*.json") if path.name != "manifest.json")
        results = [self.import_file(path) for path in files]
        manifest = self._manifest(export_dir / "manifest.json")
        total_seen = sum(item["record_count"] for item in results)
        if manifest and manifest["record_count"] != total_seen:
            raise ValueError(
                f"Manifest reports {manifest['record_count']:,} records but import saw {total_seen:,}"
            )
        self.database.execute("CHECKPOINT")
        self.database.export_parquet()
        return {
            "files": len(results),
            "record_count": total_seen,
            "manifest_record_count": manifest["record_count"] if manifest else None,
            "types": results,
        }

    def _manifest(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        if "record_count" in data:
            return {"record_count": int(data["record_count"])}
        counts = data.get("counts") or data.get("dataTypes") or {}
        if isinstance(counts, dict):
            total = 0
            for value in counts.values():
                total += int(value.get("count", 0) if isinstance(value, dict) else value)
            return {"record_count": total}
        return None

    def import_file(self, path: Path) -> dict[str, Any]:
        data_type = path.name.removesuffix(".json.gz").removesuffix(".json")
        known = self.database.row("SELECT * FROM raw_files WHERE path = ?", [str(path)])
        file_hash = sha256_file(path)
        if known and known["sha256"] == file_hash:
            return {"data_type": data_type, "record_count": int(known["record_count"]), "cached": True}

        batches: dict[str, list[tuple]] = defaultdict(list)
        count = 0
        with self.database.transaction() as connection:
            for point in iter_export_points(path):
                count += 1
                mapped = (
                    ("daily", map_daily(data_type, point, file_hash)),
                    ("sample", map_sample(data_type, point, file_hash)),
                    ("interval", map_interval(data_type, point, file_hash)),
                    ("sleep", map_sleep(data_type, point, file_hash)),
                    ("exercise", map_exercise(data_type, point, file_hash)),
                    ("nutrition", map_nutrition(data_type, point, file_hash)),
                )
                for kind, row in mapped:
                    if row is None:
                        continue
                    batches[kind].append(row)
                    if len(batches[kind]) >= self.batch_size:
                        table, columns = TABLES[kind]
                        _insert_batch(connection, table, columns, batches[kind])
                        batches[kind].clear()
            for kind, rows in batches.items():
                table, columns = TABLES[kind]
                _insert_batch(connection, table, columns, rows)
            connection.execute(
                """
                INSERT INTO raw_files VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (path) DO UPDATE SET
                    data_type = excluded.data_type,
                    sha256 = excluded.sha256,
                    record_count = excluded.record_count,
                    size_bytes = excluded.size_bytes,
                    imported_at = excluded.imported_at
                """,
                [str(path), data_type, file_hash, count, path.stat().st_size, datetime.now(UTC)],
            )
        return {"data_type": data_type, "record_count": count, "cached": False}


def validate_manifest(export_dir: Path) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for path in sorted(export_dir.glob("*.json")):
        if path.name == "manifest.json":
            continue
        counts[path.stem] = sum(1 for _ in iter_export_points(path))
    return {"record_count": sum(counts.values()), "types": counts}
