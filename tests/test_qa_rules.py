"""Unit tests for QA rules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from dataflow_platform.config import Settings
from dataflow_platform.models import ScraperStatus
from dataflow_platform.qa.rules import evaluate_scraper


def _scraper(**kwargs):
    defaults = {
        "status": ScraperStatus.active,
        "scraped_count": 10,
        "jobs_count": 10,
        "last_scraped": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_empty_scrape_fails() -> None:
    settings = Settings(qa_stale_hours=36, qa_coverage_ratio=0.5)
    result = evaluate_scraper(
        _scraper(scraped_count=0, jobs_count=5),
        settings=settings,
    )
    assert result.passed is False
    assert "empty_scrape" in result.failed_rules
    assert result.needs_rerun is True


def test_coverage_drop_fails() -> None:
    settings = Settings(qa_stale_hours=36, qa_coverage_ratio=0.5)
    result = evaluate_scraper(
        _scraper(scraped_count=2, jobs_count=10),
        settings=settings,
    )
    assert "coverage_drop" in result.failed_rules


def test_stale_feed_fails() -> None:
    settings = Settings(qa_stale_hours=36, qa_coverage_ratio=0.5)
    result = evaluate_scraper(
        _scraper(last_scraped=datetime.now(timezone.utc) - timedelta(hours=48)),
        settings=settings,
    )
    assert "stale_feed" in result.failed_rules


def test_healthy_scraper_passes() -> None:
    settings = Settings(qa_stale_hours=36, qa_coverage_ratio=0.5)
    result = evaluate_scraper(_scraper(), settings=settings)
    assert result.passed is True
    assert result.needs_rerun is False
    assert result.failed_rules == []
