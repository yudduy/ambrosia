from __future__ import annotations

import hashlib
import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .assistant import CodexAppServerProvider, analyze_meal
from .config import Settings, settings
from .db import Database, json_value
from .models import ConfirmMealRequest, MealAnalysis, NutritionDraft


MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_IMAGE_SIDE = 1600


class NutritionError(ValueError):
    pass


def _json(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value)


class NutritionService:
    def __init__(self, database: Database, app_settings: Settings = settings):
        self.db = database
        self.settings = app_settings

    def create_draft(self, content: bytes, note: str | None) -> NutritionDraft:
        if not content:
            raise NutritionError("Choose a meal photo to continue.")
        if len(content) > MAX_UPLOAD_BYTES:
            raise NutritionError("Meal photos must be 15 MB or smaller.")
        draft_id = uuid.uuid4()
        target = self.settings.upload_dir / f"{draft_id}.webp"
        temporary = target.with_suffix(".webp.part")
        try:
            with Image.open(io.BytesIO(content)) as source:
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
                image.save(temporary, format="WEBP", quality=86, method=6, exif=b"")
        except (UnidentifiedImageError, OSError, ValueError) as error:
            temporary.unlink(missing_ok=True)
            raise NutritionError("The uploaded file is not a readable meal photo.") from error
        temporary.chmod(0o600)
        temporary.replace(target)
        image_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        existing = self.db.row(
            """
            SELECT * FROM nutrition_drafts WHERE image_sha256=? AND status IN ('uploaded', 'analyzing', 'ready')
              AND expires_at > ? ORDER BY created_at DESC LIMIT 1
            """,
            [image_hash, datetime.now(UTC)],
        )
        if existing:
            target.unlink(missing_ok=True)
            return self._draft(existing)
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)
        self.db.execute(
            "INSERT INTO nutrition_drafts VALUES (?, ?, ?, 'uploaded', ?, ?, ?, NULL, NULL)",
            [draft_id, created, expires, note, str(target), image_hash],
        )
        return self.get_draft(str(draft_id))

    async def analyze(self, draft_id: str, provider: CodexAppServerProvider) -> NutritionDraft:
        row = self._row(draft_id)
        if row["status"] == "ready":
            return self._draft(row)
        if row["status"] not in ("uploaded", "failed"):
            raise NutritionError(f"A {row['status']} meal draft cannot be analyzed.")
        self.db.execute("UPDATE nutrition_drafts SET status='analyzing' WHERE id=?", [draft_id])
        try:
            analysis = await analyze_meal(provider, Path(row["image_path"]), row["note"])
        except Exception:
            self.db.execute("UPDATE nutrition_drafts SET status='failed' WHERE id=?", [draft_id])
            raise
        self.db.execute(
            "UPDATE nutrition_drafts SET status='ready', analysis=? WHERE id=?",
            [analysis.model_dump_json(), draft_id],
        )
        return self.get_draft(draft_id)

    def confirm(self, draft_id: str, request: ConfirmMealRequest) -> NutritionDraft:
        row = self._row(draft_id)
        if row["status"] != "ready":
            raise NutritionError("Analyze this meal and review the ranges before confirming it.")
        analysis = request.analysis
        with self.db.transaction() as connection:
            result = connection.execute(
                """
                INSERT INTO nutrition_entries (
                  record_id, eaten_at, meal_type, description, calories_low, calories_high,
                  protein_low, protein_high, carbs_low, carbs_high, fat_low, fat_high,
                  sodium_low, sodium_high, ingredients, confidence, confirmed, thumbnail_path,
                  source, provenance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, ?, 'AMBROSIA', ?)
                RETURNING id
                """,
                [
                    f"ambrosia:{draft_id}", request.eaten_at, analysis.meal_type, analysis.description,
                    analysis.calories.low, analysis.calories.high, analysis.protein_g.low,
                    analysis.protein_g.high, analysis.carbs_g.low, analysis.carbs_g.high,
                    analysis.fat_g.low, analysis.fat_g.high,
                    analysis.sodium_mg.low if analysis.sodium_mg else None,
                    analysis.sodium_mg.high if analysis.sodium_mg else None,
                    json_value(analysis.ingredients), analysis.confidence, row["image_path"],
                    json_value({"method": "confirmed-ai-photo-range-v1", "draft_id": draft_id}),
                ],
            ).fetchone()
            connection.execute(
                "UPDATE nutrition_drafts SET status='confirmed', analysis=?, confirmed_entry_id=? WHERE id=?",
                [analysis.model_dump_json(), result[0], draft_id],
            )
        return self.get_draft(draft_id)

    def cancel(self, draft_id: str) -> None:
        row = self._row(draft_id)
        if row["status"] == "confirmed":
            raise NutritionError("Confirmed meals cannot be discarded from the draft flow.")
        Path(row["image_path"]).unlink(missing_ok=True)
        self.db.execute("DELETE FROM nutrition_drafts WHERE id=?", [draft_id])

    def cleanup_expired(self) -> int:
        rows = self.db.rows(
            "SELECT id, image_path FROM nutrition_drafts WHERE status != 'confirmed' AND expires_at <= ?",
            [datetime.now(UTC)],
        )
        for row in rows:
            Path(row["image_path"]).unlink(missing_ok=True)
            self.db.execute("UPDATE nutrition_drafts SET status='expired' WHERE id=?", [row["id"]])
        return len(rows)

    def get_draft(self, draft_id: str) -> NutritionDraft:
        return self._draft(self._row(draft_id))

    def image_path(self, draft_id: str) -> Path:
        return Path(self._row(draft_id)["image_path"])

    def _row(self, draft_id: str) -> dict:
        try:
            parsed = uuid.UUID(draft_id)
        except ValueError as error:
            raise NutritionError("Meal draft not found.") from error
        row = self.db.row("SELECT * FROM nutrition_drafts WHERE id=?", [parsed])
        if not row:
            raise NutritionError("Meal draft not found.")
        return row

    @staticmethod
    def _draft(row: dict) -> NutritionDraft:
        analysis = _json(row["analysis"])
        return NutritionDraft(
            id=row["id"], created_at=row["created_at"], expires_at=row["expires_at"],
            status=row["status"], note=row["note"],
            thumbnail_url=f"/api/nutrition/drafts/{row['id']}/image",
            analysis=MealAnalysis.model_validate(analysis) if analysis else None,
        )

