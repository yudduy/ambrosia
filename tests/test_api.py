from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from ambrosia.api import create_app
from ambrosia.config import Settings
from ambrosia.models import AssistantStatus


class FakeInsightProvider:
    def __init__(self):
        self.calls = 0

    async def status(self):
        return AssistantStatus(
            provider="codex-app-server",
            running=True,
            authenticated=True,
            image_capable_model=True,
            model="test-model",
            reason=None,
        )

    async def run_structured(self, prompt, schema, image_path=None):
        self.calls += 1
        assert "get_health_overview" in prompt
        assert schema["additionalProperties"] is False
        assert image_path is None
        return {"text": "Activity is available; recovery data has not arrived yet."}

    async def close(self):
        return None


class FakeChatProvider:
    def __init__(self):
        self.image_path = None

    async def status(self):
        return AssistantStatus(
            provider="codex-app-server", running=True, authenticated=True,
            image_capable_model=True, model="test-model", reason=None,
        )

    async def create_thread(self):
        return "provider-thread-1"

    async def resume_thread(self, provider_thread_id):
        assert provider_thread_id == "provider-thread-1"

    async def start_turn(self, provider_thread_id, text, image_path=None):
        assert provider_thread_id == "provider-thread-1"
        assert text == "How does this meal fit my training?"
        self.image_path = image_path
        return "turn-1"

    async def events(self, provider_thread_id, after_sequence=0):
        assert provider_thread_id == "provider-thread-1"
        yield {
            "method": "item/completed", "_ambrosia_sequence": 1,
            "params": {
                "threadId": provider_thread_id, "turnId": "turn-1",
                "item": {
                    "id": "assistant-message-1", "type": "agentMessage",
                    "text": "It looks protein-forward; portion size is uncertain.",
                },
            },
        }
        yield {
            "method": "turn/completed", "_ambrosia_sequence": 2,
            "params": {"turn": {"id": "turn-1", "status": "completed"}},
        }

    async def close(self):
        return None


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
        assert len(home["today_metrics"]) == 6
        assert len(home["overnight_metrics"]) == 5
        assert len(home["readiness_history"]) == 7
        assert home["readiness"]["method_version"] == "personal-readiness-v1"
        assert home["sync"]["configured"] is False
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


def test_daily_insight_requires_disclosure_and_is_cached(tmp_path: Path):
    settings = Settings(home=tmp_path / "runtime")
    with TestClient(create_app(settings)) as client:
        provider = FakeInsightProvider()
        client.app.state.assistant = provider
        denied = client.post(
            "/api/home/insight?date=2026-08-30", json={"disclosure_accepted": False}
        )
        assert denied.status_code == 400
        response = client.post(
            "/api/home/insight?date=2026-08-30", json={"disclosure_accepted": True}
        )
        assert response.status_code == 200
        assert response.json()["text"] == "Activity is available; recovery data has not arrived yet."
        assert response.json()["model"] == "test-model"
        assert client.post(
            "/api/home/insight?date=2026-08-30", json={"disclosure_accepted": True}
        ).status_code == 200
        assert provider.calls == 1


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


def test_health_chat_persists_messages_and_photo_across_reload(tmp_path: Path):
    settings = Settings(home=tmp_path / "runtime")
    image = io.BytesIO()
    Image.new("RGB", (400, 300), "orange").save(image, "JPEG")
    with TestClient(create_app(settings)) as client:
        provider = FakeChatProvider()
        client.app.state.assistant = provider
        assert client.get("/api/assistant/conversation").json() == {
            "thread": None, "messages": [],
        }
        thread = client.post(
            "/api/assistant/threads",
            json={"title": "My health chat", "disclosure_accepted": True},
        ).json()
        draft = client.post(
            "/api/nutrition/uploads",
            files={"photo": ("meal.jpg", image.getvalue(), "image/jpeg")},
        ).json()
        started = client.post(
            f"/api/assistant/threads/{thread['id']}/turns",
            json={
                "text": "How does this meal fit my training?",
                "image_draft_id": draft["id"],
            },
        )
        assert started.status_code == 200
        assert provider.image_path.is_file()
        with client.stream("GET", f"/api/assistant/threads/{thread['id']}/events") as response:
            assert response.status_code == 200
            assert any("turn_completed" in line for line in response.iter_lines())
        conversation = client.get("/api/assistant/conversation").json()
        assert conversation["thread"]["id"] == thread["id"]
        assert [message["role"] for message in conversation["messages"]] == ["user", "assistant"]
        assert conversation["messages"][0]["image_url"] == draft["thumbnail_url"]
        assert conversation["messages"][1]["text"].startswith("It looks protein-forward")
        with client.stream("GET", f"/api/assistant/threads/{thread['id']}/events") as response:
            list(response.iter_lines())
        assert len(client.get("/api/assistant/conversation").json()["messages"]) == 2


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
