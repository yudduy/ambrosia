from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from ambrosia.google_health import (
    SCOPES,
    GoogleHealthClient,
    GoogleHealthError,
    GoogleHealthSync,
    begin_authorization,
    complete_authorization,
)


def test_nutrition_scope_is_part_of_read_only_grant():
    assert "https://www.googleapis.com/auth/googlehealth.nutrition.readonly" in SCOPES
    assert all(scope.endswith("readonly") for scope in SCOPES)


def test_google_authorization_uses_pkce_and_persists_private_token(tmp_path: Path, monkeypatch):
    credentials = tmp_path / "credentials.json"
    token = tmp_path / "private" / "token.json"
    credentials.write_text(
        json.dumps(
            {
                "web": {
                    "client_id": "client-id",
                    "client_secret": "client-secret",
                    "redirect_uris": ["https://www.google.com"],
                }
            }
        )
    )
    authorization = begin_authorization(credentials)
    query = parse_qs(urlparse(authorization["url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert set(query["scope"][0].split()) == set(SCOPES)

    def handler(request: httpx.Request):
        assert request.url.path == "/token"
        assert b"code_verifier=" in request.content
        return httpx.Response(
            200,
            json={
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 3600,
                "scope": " ".join(SCOPES),
                "token_type": "Bearer",
            },
            request=request,
        )

    monkeypatch.setattr("ambrosia.google_health.TOKEN_URL", "https://oauth.example/token")
    result = complete_authorization(
        credentials,
        token,
        f"https://www.google.com/?code=approved&state={authorization['state']}",
        authorization,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert result["authorized"] is True
    assert json.loads(token.read_text())["refresh_token"] == "refresh"
    assert token.stat().st_mode & 0o777 == 0o600


def test_transient_failure_retries_and_respects_retry_after(monkeypatch, tmp_path: Path):
    attempts = 0

    def handler(request: httpx.Request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(200, json={"dataPoints": []}, request=request)

    client = GoogleHealthClient(
        tmp_path / "credentials.json",
        tmp_path / "token.json",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(client, "access_token", lambda force_refresh=False: "test-token")
    monkeypatch.setattr("ambrosia.google_health.time.sleep", lambda _: None)
    assert client.request("https://health.example/data", {}) == {"dataPoints": []}
    assert attempts == 2


def test_list_and_reconcile_modes_are_selected_by_type(tmp_path: Path):
    client = GoogleHealthClient(tmp_path / "credentials.json", tmp_path / "token.json")
    calls: list[tuple[str, dict]] = []

    def request(url: str, params: dict):
        calls.append((url, params.copy()))
        return {"dataPoints": []}

    client.request = request  # type: ignore[method-assign]
    start = datetime(2026, 8, 29, tzinfo=UTC)
    client.fetch("sleep", start)
    client.fetch("steps", start)
    client.fetch("nutrition-log", start)
    assert calls[0][0].endswith("/sleep/dataPoints")
    assert calls[1][0].endswith("/steps/dataPoints:reconcile")
    assert calls[2][0].endswith("/nutrition-log/dataPoints")


def test_partial_sync_advances_only_successful_watermark(monkeypatch, database, app_settings, tmp_path: Path):
    credentials = tmp_path / "credentials.json"
    token = tmp_path / "token.json"
    credentials.write_text("{}")
    token.write_text("{}")
    configured = app_settings.model_copy(update={"google_credentials": credentials, "google_token": token})

    class FakeClient:
        def __init__(self, *_):
            pass

        def fetch(self, data_type: str, start: datetime):
            if data_type == "sleep":
                raise GoogleHealthError("synthetic sleep failure")
            return [
                {
                    "dataSource": {"platform": "FITBIT"},
                    "steps": {
                        "interval": {
                            "startTime": "2026-08-30T12:00:00Z",
                            "endTime": "2026-08-30T12:01:00Z",
                        },
                        "count": "12",
                    },
                }
            ]

    monkeypatch.setattr("ambrosia.google_health.GoogleHealthClient", FakeClient)
    result = GoogleHealthSync(database, configured).run("test", ["steps", "sleep"])
    assert result["status"] == "partial"
    assert database.row("SELECT * FROM watermarks WHERE data_type='steps'")
    assert database.row("SELECT * FROM watermarks WHERE data_type='sleep'") is None
    assert database.row("SELECT count(*) AS count FROM metric_intervals WHERE data_type='steps'")["count"] == 1
    assert list(configured.raw_dir.rglob("steps.json.gz"))
