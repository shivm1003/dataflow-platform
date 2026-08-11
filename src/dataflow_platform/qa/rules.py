"""QA evaluation for a single scraper row."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from dataflow_platform.config import Settings, get_settings
from dataflow_platform.models import Scraper, ScraperStatus


@dataclass
class QAResult:
    passed: bool
    needs_rerun: bool
    failed_rules: list[str]
    notes: str


def evaluate_scraper(scraper: Scraper, settings: Settings | None = None) -> QAResult:
    """Apply v1 QA rules against the scraper's latest mirrored fields."""
    cfg = settings or get_settings()
    failed: list[str] = []

    if scraper.status != ScraperStatus.active:
        return QAResult(passed=True, needs_rerun=False, failed_rules=[], notes="")

    scraped = scraper.scraped_count
    jobs = scraper.jobs_count

    if scraped is not None and scraped == 0:
        failed.append("empty_scrape")

    if (
        scraped is not None
        and jobs is not None
        and jobs > 0
        and scraped < cfg.qa_coverage_ratio * jobs
    ):
        failed.append("coverage_drop")

    if scraper.last_scraped is None:
        failed.append("never_ran")
    else:
        last = scraper.last_scraped
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - last
        if age > timedelta(hours=cfg.qa_stale_hours):
            failed.append("stale_feed")

    # Explicit failure marker from run report (qa_passed False set before evaluate
    # with failed_run note handled by caller via run_failed flag in notes path).
    # Coverage/empty/stale are the automated checks here.

    passed = len(failed) == 0
    notes = ", ".join(failed) if failed else ""
    return QAResult(
        passed=passed,
        needs_rerun=not passed,
        failed_rules=failed,
        notes=notes,
    )


def apply_qa_to_scraper(scraper: Scraper, settings: Settings | None = None) -> QAResult:
    result = evaluate_scraper(scraper, settings)
    scraper.qa_passed = result.passed
    scraper.needs_rerun = result.needs_rerun
    scraper.qa_notes = result.notes or None
    return result
