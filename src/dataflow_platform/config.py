"""Application settings loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+asyncpg://dataflow:dataflow_dev@localhost:5433/dataflow"
    )
    database_url_sync: str = (
        "postgresql://dataflow:dataflow_dev@localhost:5433/dataflow"
    )
    seed_scrape_details_path: str = Field(
        default="../crawlers/mapping_files/scrape_details.json"
    )

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # QA thresholds
    qa_stale_hours: int = 36
    qa_coverage_ratio: float = 0.5

    @property
    def repo_root(self) -> Path:
        return _repo_root()

    @property
    def seed_path(self) -> Path:
        path = Path(self.seed_scrape_details_path)
        if not path.is_absolute():
            path = self.repo_root / path
        return path.resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
