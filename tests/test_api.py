from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from ambrosia.api import create_app
from ambrosia.config import Settings


def test_typed_dashboard_and_compiled_frontend_are_served(tmp_path: Path):
    settings = Settings(
        home=tmp_path / "runtime",
        frontend_dist=Path(__file__).parents[1] / "web" / "dist",
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        home = client.get("/api/home").json()
        assert home["coverage"]["expected_days"] == 7
        assert home["provenance"]["method_version"] == "personal-baseline-v1"
        assert len(home["metrics"]) == 7
        assert client.get("/api/fitness?range=90d").json()["range"] == "90d"
        page = client.get("/")
        assert page.status_code == 200
        assert "Ambrosia" in page.text


def test_profile_requires_explicit_http_update(tmp_path: Path):
    settings = Settings(home=tmp_path / "runtime")
    with TestClient(create_app(settings)) as client:
        profile = client.get("/api/profile").json()
        profile["goal"] = "Improve sleep consistency"
        profile["dietary_preferences"] = ["high protein"]
        updated = client.put("/api/profile", json=profile)
        assert updated.status_code == 200
        assert client.get("/api/profile").json()["goal"] == "Improve sleep consistency"


def test_meal_upload_is_sanitized_before_ai(tmp_path: Path):
    settings = Settings(home=tmp_path / "runtime")
    image = io.BytesIO()
    Image.new("RGB", (400, 300), "orange").save(image, "JPEG")
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/nutrition/uploads",
            files={"photo": ("meal.jpg", image.getvalue(), "image/jpeg")},
            data={"note": "after training"},
        )
        assert response.status_code == 200
        draft = response.json()
        assert draft["status"] == "uploaded"
        sanitized = client.get(draft["thumbnail_url"])
        assert sanitized.status_code == 200
        assert sanitized.headers["content-type"] == "image/webp"
        assert client.delete(f"/api/nutrition/drafts/{draft['id']}").status_code == 204
        assert client.get(draft["thumbnail_url"]).status_code == 404


def test_sync_without_credentials_is_explainable(tmp_path: Path):
    settings = Settings(home=tmp_path / "runtime")
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/sync")
        assert response.status_code == 400
        assert "credentials" in response.json()["detail"].lower()


def test_mcp_facing_responses_do_not_expose_private_fields(tmp_path: Path):
    settings = Settings(home=tmp_path / "runtime")
    forbidden = ("access_token", "refresh_token", "google_user", "filesystem", "raw_samples")
    with TestClient(create_app(settings)) as client:
        payloads = [
            client.get("/api/home").text,
            client.get("/api/fitness?range=7d").text,
            client.get("/api/profile-and-quality").text,
            client.get("/api/relationships/sleep_hrv").text,
        ]
    lowered = "\n".join(payloads).lower()
    assert all(value not in lowered for value in forbidden)

