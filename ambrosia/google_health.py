from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse

import httpx
import orjson

from .config import Settings, settings
from .db import Database, json_value
from .importer import ExportImporter, sha256_file


API_ROOT = "https://health.googleapis.com/v4/users/me/dataTypes"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
SCOPES = (
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
    "https://www.googleapis.com/auth/googlehealth.ecg.readonly",
    "https://www.googleapis.com/auth/googlehealth.irn.readonly",
    "https://www.googleapis.com/auth/googlehealth.location.readonly",
    "https://www.googleapis.com/auth/googlehealth.nutrition.readonly",
)

DATA_TYPES: dict[str, str] = {
    "steps": "steps.interval.start_time",
    "distance": "distance.interval.start_time",
    "active-minutes": "active_minutes.interval.start_time",
    "active-zone-minutes": "active_zone_minutes.interval.start_time",
    "active-energy-burned": "active_energy_burned.interval.start_time",
    "sedentary-period": "sedentary_period.interval.start_time",
    "time-in-heart-rate-zone": "time_in_heart_rate_zone.interval.start_time",
    "exercise": "exercise.interval.start_time",
    "heart-rate": "heart_rate.sample_time.physical_time",
    "heart-rate-variability": "heart_rate_variability.sample_time.physical_time",
    "oxygen-saturation": "oxygen_saturation.sample_time.physical_time",
    "respiratory-rate-sleep-summary": "respiratory_rate_sleep_summary.sample_time.physical_time",
    "weight": "weight.sample_time.physical_time",
    "body-fat": "body_fat.sample_time.physical_time",
    "daily-resting-heart-rate": "daily_resting_heart_rate.date",
    "daily-heart-rate-variability": "daily_heart_rate_variability.date",
    "daily-heart-rate-zones": "daily_heart_rate_zones.date",
    "daily-oxygen-saturation": "daily_oxygen_saturation.date",
    "daily-respiratory-rate": "daily_respiratory_rate.date",
    "daily-sleep-temperature-derivations": "daily_sleep_temperature_derivations.date",
    "daily-vo2-max": "daily_vo2_max.date",
    "sleep": "sleep.interval.end_time",
    "nutrition-log": "nutrition_log.interval.end_time",
    "hydration-log": "hydration_log.interval.end_time",
}

LIST_TYPES = {"sleep", "exercise", "nutrition-log", "hydration-log"}


class GoogleHealthError(RuntimeError):
    pass


class GoogleConsentRevoked(GoogleHealthError):
    pass


def begin_authorization(credentials_path: Path) -> dict[str, str]:
    client = _oauth_client(credentials_path)
    redirect_uris = client.get("redirect_uris") or []
    if not redirect_uris:
        raise GoogleHealthError("Google credentials must contain at least one authorized redirect URI.")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = hashlib.sha256(verifier.encode()).digest()
    challenge_text = base64.urlsafe_b64encode(challenge).rstrip(b"=").decode()
    redirect_uri = str(redirect_uris[0])
    query = urlencode(
        {
            "client_id": client["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
            "code_challenge": challenge_text,
            "code_challenge_method": "S256",
        }
    )
    return {
        "url": f"{AUTH_URL}?{query}",
        "state": state,
        "verifier": verifier,
        "redirect_uri": redirect_uri,
    }


def complete_authorization(
    credentials_path: Path,
    token_path: Path,
    redirected_url: str,
    authorization: dict[str, str],
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    query = parse_qs(urlparse(redirected_url.strip()).query)
    if query.get("state", [None])[0] != authorization["state"]:
        raise GoogleHealthError("Google authorization state did not match; start again.")
    if error := query.get("error", [None])[0]:
        raise GoogleHealthError(f"Google authorization was not granted: {error}")
    code = query.get("code", [None])[0]
    if not code:
        raise GoogleHealthError("Paste the complete redirected URL containing the authorization code.")
    oauth_client = _oauth_client(credentials_path)
    response = (client or httpx.Client(timeout=60)).post(
        TOKEN_URL,
        data={
            "client_id": oauth_client["client_id"],
            "client_secret": oauth_client["client_secret"],
            "code": code,
            "code_verifier": authorization["verifier"],
            "grant_type": "authorization_code",
            "redirect_uri": authorization["redirect_uri"],
        },
    )
    if response.status_code >= 400:
        raise GoogleHealthError(f"Google token exchange failed with HTTP {response.status_code}.")
    token = response.json()
    granted = set(str(token.get("scope", "")).split())
    missing = sorted(set(SCOPES) - granted)
    if missing:
        raise GoogleHealthError("Google did not grant all required read-only scopes: " + ", ".join(missing))
    if not token.get("refresh_token"):
        raise GoogleHealthError("Google did not return offline refresh access; revoke the old grant and try again.")
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600))
    _private_json(token_path, token)
    return {"authorized": True, "scopes": sorted(granted), "token_path": str(token_path)}


def _private_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as error:
        raise GoogleHealthError(f"Required Google credential file is missing: {path}") from error
    except json.JSONDecodeError as error:
        raise GoogleHealthError(f"Invalid JSON in {path}: {error}") from error


def _oauth_client(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    client = payload.get("web") or payload.get("installed") or {}
    if not client.get("client_id") or not client.get("client_secret"):
        raise GoogleHealthError("Google credentials must contain a client_id and client_secret.")
    return client


def _retry_seconds(response: httpx.Response, attempt: int) -> float:
    value = response.headers.get("Retry-After")
    if value:
        try:
            return max(0, float(value))
        except ValueError:
            try:
                return max(0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError):
                pass
    return float(2**attempt)


class GoogleHealthClient:
    def __init__(self, credentials_path: Path, token_path: Path, client: httpx.Client | None = None):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.client = client or httpx.Client(timeout=60)

    def access_token(self, force_refresh: bool = False) -> str:
        token = _load_json(self.token_path)
        expires_at = int(token.get("expires_at", 0))
        if not force_refresh and token.get("access_token") and expires_at > time.time() + 60:
            return str(token["access_token"])
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise GoogleConsentRevoked("Google authorization must be renewed.")
        client = _oauth_client(self.credentials_path)
        response = self.client.post(
            TOKEN_URL,
            data={
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if response.status_code in (400, 401):
            raise GoogleConsentRevoked("Google authorization was revoked or expired.")
        response.raise_for_status()
        token.update(response.json())
        token["refresh_token"] = refresh_token
        token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600))
        _private_json(self.token_path, token)
        return str(token["access_token"])

    def request(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        refreshed = False
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                token = self.access_token(force_refresh=refreshed)
                response = self.client.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
                if response.status_code == 401 and not refreshed:
                    refreshed = True
                    continue
                if response.status_code == 403:
                    raise GoogleConsentRevoked("Google Health consent is missing or revoked.")
                if response.status_code == 429 or response.status_code >= 500:
                    time.sleep(_retry_seconds(response, attempt))
                    last_error = GoogleHealthError(f"Google Health returned HTTP {response.status_code}")
                    continue
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                last_error = error
                time.sleep(float(2**attempt))
        raise GoogleHealthError(f"Google Health request failed after three attempts: {last_error}")

    def fetch(self, data_type: str, start: datetime) -> list[dict[str, Any]]:
        endpoint = "dataPoints" if data_type in LIST_TYPES else "dataPoints:reconcile"
        url = f"{API_ROOT}/{quote(data_type)}/{endpoint}"
        field = DATA_TYPES[data_type]
        if field.endswith(".date"):
            filter_value = f'{field} >= "{start.date().isoformat()}"'
        else:
            filter_value = f'{field} >= "{start.isoformat().replace("+00:00", "Z")}"'
        params: dict[str, Any] = {
            "pageSize": 25 if data_type in {"sleep", "exercise"} else 10_000,
            "filter": filter_value,
        }
        points: list[dict[str, Any]] = []
        while True:
            page = self.request(url, params)
            for point in page.get("dataPoints", []):
                if "dataPointName" in point and "name" not in point:
                    point["name"] = point.pop("dataPointName")
                points.append(point)
            page_token = page.get("nextPageToken")
            if not page_token:
                return points
            params["pageToken"] = page_token


def write_compressed_points(path: Path, points: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".part")
    with gzip.open(temporary, "wb", compresslevel=6) as handle:
        handle.write(b'{"dataPoints":[\n')
        for index, point in enumerate(points):
            handle.write(orjson.dumps(point, option=orjson.OPT_SORT_KEYS))
            handle.write(b",\n" if index < len(points) - 1 else b"\n")
        handle.write(b"]}\n")
    temporary.replace(path)


class GoogleHealthSync:
    def __init__(self, database: Database, app_settings: Settings = settings):
        self.db = database
        self.settings = app_settings

    def run(self, trigger: str = "hourly", selected_types: list[str] | None = None) -> dict[str, Any]:
        if not self.settings.google_credentials or not self.settings.google_token:
            raise GoogleHealthError("Google credentials and token paths are not configured.")
        run_id = uuid.uuid4()
        started = datetime.now(UTC)
        types = selected_types or list(DATA_TYPES)
        self.db.execute(
            "INSERT INTO sync_runs VALUES (?, ?, NULL, 'running', ?, '{}')",
            [run_id, started, trigger],
        )
        client = GoogleHealthClient(self.settings.google_credentials, self.settings.google_token)
        run_dir = self.settings.raw_dir / started.strftime("%Y/%m/%d/%Y%m%dT%H%M%SZ")
        results: dict[str, Any] = {}
        for data_type in types:
            type_started = datetime.now(UTC)
            self.db.execute(
                "INSERT INTO sync_type_runs VALUES (?, ?, ?, NULL, 'running', 0, NULL)",
                [run_id, data_type, type_started],
            )
            try:
                watermark = self.db.row("SELECT watermark FROM watermarks WHERE data_type = ?", [data_type])
                start = (watermark["watermark"] if watermark else started) - timedelta(hours=48)
                points = client.fetch(data_type, start)
                raw_path = run_dir / f"{data_type}.json.gz"
                write_compressed_points(raw_path, points)
                imported = ExportImporter(self.db, self.settings).import_file(raw_path)
                completed = datetime.now(UTC)
                with self.db.transaction() as connection:
                    connection.execute(
                        """
                        INSERT INTO watermarks VALUES (?, ?, ?)
                        ON CONFLICT (data_type) DO UPDATE SET watermark=excluded.watermark, updated_at=excluded.updated_at
                        """,
                        [data_type, started, completed],
                    )
                    connection.execute(
                        """
                        UPDATE sync_type_runs SET finished_at=?, status='success', records_seen=?
                        WHERE run_id=? AND data_type=?
                        """,
                        [completed, len(points), run_id, data_type],
                    )
                results[data_type] = {"status": "success", "records": len(points), "imported": imported}
            except Exception as error:
                completed = datetime.now(UTC)
                self.db.execute(
                    """
                    UPDATE sync_type_runs SET finished_at=?, status='failed', error=?
                    WHERE run_id=? AND data_type=?
                    """,
                    [completed, str(error), run_id, data_type],
                )
                results[data_type] = {"status": "failed", "error": str(error)}
        failed = [key for key, value in results.items() if value["status"] == "failed"]
        status = "partial" if failed and len(failed) < len(results) else "failed" if failed else "success"
        finished = datetime.now(UTC)
        manifest = {
            "run_id": str(run_id), "started_at": started.isoformat(), "finished_at": finished.isoformat(),
            "status": status, "types": results,
        }
        run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n")
        manifest_path.chmod(0o600)
        self.db.execute(
            "UPDATE sync_runs SET finished_at=?, status=?, details=? WHERE id=?",
            [finished, status, json_value({"failed_types": failed}), run_id],
        )
        if status != "failed":
            self.db.export_parquet()
        return manifest
