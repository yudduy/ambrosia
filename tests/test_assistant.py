from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ambrosia.assistant import (
    AssistantError,
    OmpSidecarProvider,
    assistant_provider,
    strict_output_schema,
)
from ambrosia.config import Settings
from ambrosia.models import DailyInsightDraft, MealAnalysis


def test_meal_schema_is_strict_for_every_nested_object():
    schema = strict_output_schema(MealAnalysis.model_json_schema())

    def assert_strict(node):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node.get("properties", {}))
            for value in node.values():
                assert_strict(value)
        elif isinstance(node, list):
            for value in node:
                assert_strict(value)

    assert_strict(schema)
    assert_strict(strict_output_schema(DailyInsightDraft.model_json_schema()))


def test_verified_fallback_configuration_selects_omp(tmp_path: Path):
    settings = Settings(home=tmp_path / "runtime")
    settings.ensure_directories()
    settings.assistant_provider_path.write_text(json.dumps({"provider": "omp"}))

    assert isinstance(assistant_provider(settings), OmpSidecarProvider)


def test_omp_rejects_images_outside_sanitized_upload_directory(tmp_path: Path):
    settings = Settings(home=tmp_path / "runtime")
    provider = OmpSidecarProvider(settings)
    image = tmp_path / "not-an-upload.webp"
    image.write_bytes(b"not read")

    async def check():
        with pytest.raises(AssistantError, match="sanitized upload directory"):
            await provider.start_turn("thread", "analyze", image_path=image)

    asyncio.run(check())
