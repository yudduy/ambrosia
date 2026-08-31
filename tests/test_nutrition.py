from __future__ import annotations

import io
from datetime import UTC, datetime

from PIL import Image

from ambrosia.models import ConfirmMealRequest, MealAnalysis
from ambrosia.nutrition import NutritionService


def image_bytes() -> bytes:
    value = io.BytesIO()
    image = Image.new("RGB", (2400, 1800), (210, 145, 72))
    exif = Image.Exif()
    exif[0x010E] = "private location description"
    image.save(value, format="JPEG", quality=90, exif=exif)
    return value.getvalue()


def meal_analysis() -> MealAnalysis:
    return MealAnalysis.model_validate(
        {
            "description": "Chicken and rice bowl",
            "meal_type": "lunch",
            "calories": {"low": 600, "high": 800},
            "protein_g": {"low": 35, "high": 50},
            "carbs_g": {"low": 60, "high": 90},
            "fat_g": {"low": 15, "high": 28},
            "sodium_mg": {"low": 700, "high": 1300},
            "ingredients": ["chicken", "rice"],
            "confidence": 0.72,
            "uncertainty_note": "Portion depth and cooking oil are not visible.",
        }
    )


def test_upload_strips_metadata_resizes_and_deduplicates(database, app_settings):
    service = NutritionService(database, app_settings)
    first = service.create_draft(image_bytes(), "after gym")
    second = service.create_draft(image_bytes(), "duplicate")
    assert first.id == second.id
    path = service.image_path(str(first.id))
    with Image.open(path) as sanitized:
        assert max(sanitized.size) <= 1600
        assert not sanitized.getexif()


def test_confirm_requires_ready_draft_and_commits_ranges(database, app_settings):
    service = NutritionService(database, app_settings)
    draft = service.create_draft(image_bytes(), None)
    analysis = meal_analysis()
    database.execute(
        "UPDATE nutrition_drafts SET status='ready', analysis=? WHERE id=?",
        [analysis.model_dump_json(), draft.id],
    )
    confirmed = service.confirm(
        str(draft.id), ConfirmMealRequest(eaten_at=datetime.now(UTC), analysis=analysis)
    )
    assert confirmed.status == "confirmed"
    row = database.row("SELECT * FROM nutrition_entries WHERE record_id=?", [f"ambrosia:{draft.id}"])
    assert row["calories_low"] == 600
    assert row["calories_high"] == 800
    assert row["confirmed"] is True

