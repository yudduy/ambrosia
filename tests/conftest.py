from __future__ import annotations

from pathlib import Path

import pytest

from ambrosia.config import Settings
from ambrosia.db import Database


@pytest.fixture
def app_settings(tmp_path: Path) -> Settings:
    return Settings(home=tmp_path / "runtime")


@pytest.fixture
def database(app_settings: Settings):
    value = Database(app_settings)
    yield value
    value.close()

