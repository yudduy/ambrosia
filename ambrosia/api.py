from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .analysis import METRICS, HealthAnalysis
from .assistant import AssistantError, assistant_provider, generate_daily_insight
from .config import Settings, settings
from .db import Database, json_value
from .google_health import GoogleHealthError, GoogleHealthSync
from .models import (
    AssistantStatus,
    AssistantConversation,
    AssistantMessage,
    AssistantThread,
    AssistantThreadCreate,
    AssistantTurn,
    ConfirmMealRequest,
    DailyInsight,
    DailyInsightRequest,
    DomainResponse,
    HomeResponse,
    NutritionDraft,
    Profile,
    RelationshipResult,
    SessionSummary,
    SessionsResponse,
    WeeklyReportsResponse,
)
from .nutrition import NutritionError, NutritionService


def _json_field(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _raise_bad_request(error: Exception) -> None:
    raise HTTPException(status_code=400, detail=str(error)) from error


async def _sync_loop(app: FastAPI) -> None:
    app_settings: Settings = app.state.settings
    while True:
        try:
            await asyncio.to_thread(app.state.sync.run, "hourly")
            app.state.nutrition.cleanup_expired()
        except Exception:
            pass
        await asyncio.sleep(app_settings.sync_interval_seconds)


async def _store_assistant_reply(
    app: FastAPI, thread_id: str, provider_thread_id: str, turn_id: str,
) -> None:
    async for event in app.state.assistant.events(provider_thread_id):
        params = event.get("params") or {}
        event_turn_id = params.get("turnId") or (params.get("turn") or {}).get("id")
        if event_turn_id != turn_id:
            continue
        if event.get("method") == "item/completed":
            item = params.get("item") or {}
            text = str(item.get("text") or "").strip()
            if item.get("type") == "agentMessage" and text:
                provider_item_id = str(item.get("id") or turn_id)
                app.state.db.execute(
                    """
                    INSERT INTO assistant_messages VALUES (?, ?, 'assistant', ?, NULL, ?, ?)
                    ON CONFLICT (thread_id, provider_item_id) DO NOTHING
                    """,
                    [uuid.uuid4(), thread_id, text, datetime.now(UTC), provider_item_id],
                )
        if event.get("method") == "turn/completed":
            app.state.db.execute(
                "UPDATE assistant_threads SET updated_at=? WHERE id=?",
                [datetime.now(UTC), thread_id],
            )
            return


def create_app(app_settings: Settings = settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app_settings.ensure_directories()
        database = Database(app_settings)
        app.state.settings = app_settings
        app.state.db = database
        app.state.analysis = HealthAnalysis(database, app_settings)
        app.state.nutrition = NutritionService(database, app_settings)
        app.state.assistant = assistant_provider(app_settings)
        app.state.assistant_tasks = set()
        app.state.daily_insights = {}
        app.state.sync = GoogleHealthSync(database, app_settings)
        app.state.nutrition.cleanup_expired()
        task = None
        if app_settings.google_credentials and app_settings.google_token:
            task = asyncio.create_task(_sync_loop(app))
        yield
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        for assistant_task in list(app.state.assistant_tasks):
            assistant_task.cancel()
        if app.state.assistant_tasks:
            await asyncio.gather(*app.state.assistant_tasks, return_exceptions=True)
        await app.state.assistant.close()
        database.close()

    app = FastAPI(title="Ambrosia", version="0.1.0", lifespan=lifespan)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "generated_at": datetime.now(UTC)}

    @app.get("/api/home", response_model=HomeResponse)
    def home(request: Request, as_of: date | None = Query(None, alias="date")):
        return request.app.state.analysis.home(as_of)

    @app.post("/api/home/insight", response_model=DailyInsight)
    async def home_insight(
        request: Request,
        body: DailyInsightRequest,
        as_of: date | None = Query(None, alias="date"),
    ):
        if not body.disclosure_accepted:
            raise HTTPException(status_code=400, detail="Accept the AI data disclosure before continuing.")
        day = as_of or datetime.now(app_settings.tz).date()
        overview = request.app.state.analysis.home(day)
        displayed_values = tuple(
            (metric.key, metric.value) for metric in overview.today_metrics + overview.overnight_metrics
        )
        cache_key = (
            day.isoformat(), str(overview.sync.get("finished_at") or "no-sync"),
            overview.readiness.score, displayed_values,
        )
        if cached := request.app.state.daily_insights.get(cache_key):
            return cached
        status = await request.app.state.assistant.status()
        if not status.authenticated:
            raise HTTPException(status_code=401, detail=status.reason or "ChatGPT sign-in is required.")
        if not status.model:
            raise HTTPException(status_code=400, detail="No compatible model is available.")
        try:
            draft = await generate_daily_insight(request.app.state.assistant, day)
        except AssistantError as error:
            _raise_bad_request(error)
        result = DailyInsight(
            as_of=day,
            text=draft.text,
            generated_at=datetime.now(UTC),
            provider=status.provider,
            model=status.model,
        )
        request.app.state.daily_insights[cache_key] = result
        return result

    @app.get("/api/reports", response_model=WeeklyReportsResponse)
    def reports(request: Request, limit: int = Query(52, ge=1, le=260)):
        return request.app.state.analysis.weekly_reports(limit)

    @app.get("/api/fitness", response_model=DomainResponse)
    def fitness(request: Request, range_name: Literal["7d", "28d", "90d"] = Query("28d", alias="range")):
        return request.app.state.analysis.domain("fitness", range_name)

    @app.get("/api/sleep", response_model=DomainResponse)
    def sleep(request: Request, range_name: Literal["7d", "28d", "90d"] = Query("28d", alias="range")):
        return request.app.state.analysis.domain("sleep", range_name)

    @app.get("/api/nutrition", response_model=DomainResponse)
    def nutrition(request: Request, range_name: Literal["7d", "28d", "90d"] = Query("28d", alias="range")):
        return request.app.state.analysis.domain("nutrition", range_name)

    @app.get("/api/sessions", response_model=SessionsResponse)
    def sessions(
        request: Request, kind: Literal["sleep", "exercise"] | None = None,
        limit: int = Query(50, ge=1, le=200),
    ):
        return request.app.state.analysis.sessions(kind, limit)

    @app.get("/api/sessions/{session_id}", response_model=SessionSummary)
    def session(request: Request, session_id: str):
        result = request.app.state.analysis.session(session_id)
        if not result:
            raise HTTPException(status_code=404, detail="Session not found.")
        return result

    @app.get("/api/compare/{metric}")
    def compare(request: Request, metric: str, as_of: date | None = Query(None, alias="date")):
        if metric not in METRICS:
            raise HTTPException(status_code=404, detail="Metric not found.")
        end = as_of or datetime.now(app_settings.tz).date()
        summary = request.app.state.analysis._metric_summary(metric, end, 7)
        return {
            "metric": summary, "date_start": end - timedelta(days=6), "date_end": end,
            "generated_at": datetime.now(UTC), "method_version": "personal-baseline-v1",
        }

    @app.get("/api/relationships", response_model=list[RelationshipResult])
    def relationships(request: Request):
        return request.app.state.analysis.relationships()

    @app.get("/api/relationships/{relationship}", response_model=RelationshipResult)
    def relationship(request: Request, relationship: str):
        result = next(
            (item for item in request.app.state.analysis.relationships() if item.key == relationship), None
        )
        if not result:
            raise HTTPException(status_code=404, detail="Relationship not found.")
        return result

    @app.get("/api/profile", response_model=Profile)
    def get_profile(request: Request):
        row = request.app.state.db.row("SELECT * FROM profile WHERE id=1")
        return Profile(
            goal=row["goal"], time_horizon=row["time_horizon"],
            training_frequency=row["training_frequency"],
            dietary_preferences=_json_field(row["dietary_preferences"]) or [],
            constraints=_json_field(row["constraints"]) or [], timezone=row["timezone"],
            distance_unit=row["distance_unit"], weight_unit=row["weight_unit"],
            updated_at=row["updated_at"],
        )

    @app.put("/api/profile", response_model=Profile)
    def put_profile(request: Request, profile: Profile):
        updated = datetime.now(UTC)
        request.app.state.db.execute(
            """
            UPDATE profile SET updated_at=?, goal=?, time_horizon=?, training_frequency=?,
              dietary_preferences=?, constraints=?, timezone=?, distance_unit=?, weight_unit=? WHERE id=1
            """,
            [
                updated, profile.goal, profile.time_horizon, profile.training_frequency,
                json_value(profile.dietary_preferences), json_value(profile.constraints), profile.timezone,
                profile.distance_unit, profile.weight_unit,
            ],
        )
        profile.updated_at = updated
        return profile

    @app.get("/api/profile-and-quality")
    def profile_and_quality(request: Request):
        profile = get_profile(request)
        counts = request.app.state.db.row(
            """
            SELECT (SELECT count(DISTINCT day) FROM daily_metrics) AS daily_days,
                   (SELECT count(*) FROM sleep_sessions) AS sleep_sessions,
                   (SELECT count(*) FROM exercise_sessions) AS exercise_sessions,
                   (SELECT count(*) FROM nutrition_entries WHERE confirmed) AS confirmed_meals
            """
        )
        return {
            "profile": profile, "data_quality": counts, "generated_at": datetime.now(UTC),
            "method_version": "profile-quality-v1",
        }

    @app.post("/api/nutrition/uploads", response_model=NutritionDraft)
    async def upload_meal(
        request: Request, photo: Annotated[UploadFile, File()], note: Annotated[str | None, Form()] = None,
    ):
        content = await photo.read(15 * 1024 * 1024 + 1)
        try:
            return request.app.state.nutrition.create_draft(content, note)
        except NutritionError as error:
            _raise_bad_request(error)

    @app.get("/api/nutrition/drafts/{draft_id}", response_model=NutritionDraft)
    def get_draft(request: Request, draft_id: str):
        try:
            return request.app.state.nutrition.get_draft(draft_id)
        except NutritionError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/api/nutrition/drafts/{draft_id}/image")
    def draft_image(request: Request, draft_id: str):
        try:
            path = request.app.state.nutrition.image_path(draft_id)
        except NutritionError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=3600"})

    @app.post("/api/nutrition/drafts/{draft_id}/analyze", response_model=NutritionDraft)
    async def analyze_draft(request: Request, draft_id: str):
        try:
            status = await request.app.state.assistant.status()
            if not status.authenticated or not status.image_capable_model:
                raise NutritionError(status.reason or "ChatGPT sign-in is required for meal analysis.")
            return await request.app.state.nutrition.analyze(draft_id, request.app.state.assistant)
        except (NutritionError, AssistantError) as error:
            _raise_bad_request(error)

    @app.post("/api/nutrition/drafts/{draft_id}/confirm", response_model=NutritionDraft)
    def confirm_draft(request: Request, draft_id: str, confirmation: ConfirmMealRequest):
        try:
            return request.app.state.nutrition.confirm(draft_id, confirmation)
        except NutritionError as error:
            _raise_bad_request(error)

    @app.delete("/api/nutrition/drafts/{draft_id}", status_code=204)
    def cancel_draft(request: Request, draft_id: str):
        try:
            request.app.state.nutrition.cancel(draft_id)
        except NutritionError as error:
            _raise_bad_request(error)

    @app.get("/api/assistant/status", response_model=AssistantStatus)
    async def assistant_status(request: Request):
        return await request.app.state.assistant.status()

    @app.post("/api/assistant/login")
    async def assistant_login(request: Request):
        try:
            return await request.app.state.assistant.start_login()
        except AssistantError as error:
            _raise_bad_request(error)

    @app.post("/api/assistant/threads", response_model=AssistantThread)
    async def create_thread(request: Request, body: AssistantThreadCreate):
        if not body.disclosure_accepted:
            raise HTTPException(status_code=400, detail="Accept the AI data disclosure before continuing.")
        status = await request.app.state.assistant.status()
        if not status.authenticated:
            raise HTTPException(status_code=401, detail=status.reason or "ChatGPT sign-in is required.")
        provider_id = await request.app.state.assistant.create_thread()
        provider_name = status.provider
        local_id = uuid.uuid4()
        created = datetime.now(UTC)
        request.app.state.db.execute(
            "INSERT INTO assistant_threads VALUES (?, ?, ?, ?, ?, ?, '{}')",
            [local_id, provider_name, provider_id, created, created, body.title],
        )
        return AssistantThread(id=local_id, provider=provider_name, created_at=created, title=body.title)

    @app.get("/api/assistant/conversation", response_model=AssistantConversation)
    def assistant_conversation(request: Request):
        thread = request.app.state.db.row(
            "SELECT * FROM assistant_threads ORDER BY updated_at DESC LIMIT 1"
        )
        if not thread:
            return AssistantConversation()
        messages = request.app.state.db.rows(
            "SELECT * FROM assistant_messages WHERE thread_id=? ORDER BY created_at, id",
            [thread["id"]],
        )
        return AssistantConversation(
            thread=AssistantThread(
                id=thread["id"], provider=thread["provider"],
                created_at=thread["created_at"], title=thread["title"],
            ),
            messages=[
                AssistantMessage(
                    id=message["id"], role=message["role"], text=message["text"],
                    image_url=(
                        f"/api/nutrition/drafts/{message['image_draft_id']}/image"
                        if message["image_draft_id"] else None
                    ),
                    created_at=message["created_at"],
                )
                for message in messages
            ],
        )

    @app.post("/api/assistant/threads/{thread_id}/turns")
    async def start_turn(request: Request, thread_id: str, body: AssistantTurn):
        row = request.app.state.db.row("SELECT * FROM assistant_threads WHERE id=?", [thread_id])
        if not row:
            raise HTTPException(status_code=404, detail="Assistant thread not found.")
        image_path = None
        if body.image_draft_id:
            try:
                image_path = request.app.state.nutrition.image_path(str(body.image_draft_id))
            except NutritionError as error:
                _raise_bad_request(error)
        try:
            await request.app.state.assistant.resume_thread(row["provider_thread_id"])
            turn_id = await request.app.state.assistant.start_turn(
                row["provider_thread_id"], body.text, image_path=image_path
            )
        except AssistantError as error:
            _raise_bad_request(error)
        created = datetime.now(UTC)
        with request.app.state.db.transaction() as connection:
            connection.execute(
                "INSERT INTO assistant_messages VALUES (?, ?, 'user', ?, ?, ?, NULL)",
                [uuid.uuid4(), thread_id, body.text, body.image_draft_id, created],
            )
            connection.execute(
                "UPDATE assistant_threads SET updated_at=? WHERE id=?", [created, thread_id]
            )
        persistence_task = asyncio.create_task(
            _store_assistant_reply(
                request.app, thread_id, row["provider_thread_id"], turn_id,
            )
        )
        request.app.state.assistant_tasks.add(persistence_task)
        persistence_task.add_done_callback(request.app.state.assistant_tasks.discard)
        return {"turn_id": turn_id, "status": "started"}

    @app.get("/api/assistant/threads/{thread_id}/events")
    async def assistant_events(request: Request, thread_id: str, live: bool = Query(False)):
        row = request.app.state.db.row("SELECT * FROM assistant_threads WHERE id=?", [thread_id])
        if not row:
            raise HTTPException(status_code=404, detail="Assistant thread not found.")

        try:
            after_sequence = int(request.headers.get("last-event-id", "0"))
        except ValueError:
            after_sequence = 0
        if live and after_sequence == 0:
            after_sequence = int(getattr(request.app.state.assistant, "_event_sequence", 0))

        async def stream():
            async for event in request.app.state.assistant.events(
                row["provider_thread_id"], after_sequence=after_sequence
            ):
                if await request.is_disconnected():
                    break
                public = _public_assistant_event(event)
                if public:
                    sequence = int(event.get("_ambrosia_sequence", 0))
                    yield (
                        f"id: {sequence}\nevent: {public['event']}\n"
                        f"data: {json.dumps(public['data'])}\n\n"
                    )

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/api/sync")
    async def sync_now(request: Request):
        try:
            return await asyncio.to_thread(request.app.state.sync.run, "manual")
        except GoogleHealthError as error:
            _raise_bad_request(error)

    frontend = app_settings.frontend_dist or Path(__file__).resolve().parents[1] / "web" / "dist"
    if frontend.is_dir():
        assets = frontend / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", response_class=HTMLResponse)
        def frontend_fallback(path: str):
            if path.startswith("api/"):
                raise HTTPException(status_code=404, detail="API route not found.")
            return FileResponse(frontend / "index.html")

    return app


def _public_assistant_event(event: dict) -> dict | None:
    method = event.get("method")
    params = event.get("params") or {}
    if method == "item/agentMessage/delta":
        return {"event": "message_delta", "data": {"text": params.get("delta", "")}}
    if method == "item/completed":
        item = params.get("item") or {}
        if item.get("type") == "agentMessage":
            return {"event": "message_completed", "data": {"text": item.get("text", "")}}
        if item.get("type") == "mcpToolCall":
            return {"event": "evidence", "data": {"tool": item.get("tool"), "status": item.get("status")}}
    if method == "turn/completed":
        turn = params.get("turn") or {}
        return {"event": "turn_completed", "data": {"status": turn.get("status"), "error": turn.get("error")}}
    return None


app = create_app()
