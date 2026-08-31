from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_home() -> Path:
    configured = os.environ.get("AMBROSIA_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / "Library" / "Application Support" / "Ambrosia"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AMBROSIA_", extra="ignore")

    home: Path = Field(default_factory=default_home)
    timezone: str = "America/Los_Angeles"
    bind_host: str = "127.0.0.1"
    port: int = 8787
    sync_interval_seconds: int = 3600
    frontend_dist: Path | None = None
    google_credentials: Path | None = None
    google_token: Path | None = None
    google_export: Path | None = None
    assistant_provider: str = "codex-app-server"

    @property
    def database_path(self) -> Path:
        return self.home / "ambrosia.duckdb"

    @property
    def raw_dir(self) -> Path:
        return self.home / "raw"

    @property
    def parquet_dir(self) -> Path:
        return self.home / "parquet"

    @property
    def upload_dir(self) -> Path:
        return self.home / "uploads"

    @property
    def temp_dir(self) -> Path:
        return self.home / "tmp"

    @property
    def codex_home(self) -> Path:
        return self.home / "codex"

    @property
    def assistant_provider_path(self) -> Path:
        return self.home / "assistant-provider.json"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def ensure_directories(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        for path in (self.raw_dir, self.parquet_dir, self.upload_dir, self.codex_home, self.temp_dir):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.home.chmod(0o700)
        except OSError:
            pass


settings = Settings()
