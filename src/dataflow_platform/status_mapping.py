"""Map scraper/run state to Sources and Job Center labels."""

from __future__ import annotations

from datetime import datetime, timezone

from dataflow_platform.models import FeedDelivery, ProxyUsage, Scraper


def derive_display_name(spider_name: str, display_name: str | None = None) -> str:
    if display_name and display_name.strip():
        return display_name.strip()
    if "_" in spider_name:
        return spider_name.split("_", 1)[1].replace("_", " ").title()
    return spider_name


def feed_type_label(feed_delivery: FeedDelivery | str | None) -> str:
    value = getattr(feed_delivery, "value", feed_delivery) or ""
    if value.startswith("json"):
        return "JSON"
    if value.startswith("csv"):
        return "CSV"
    return "XML"


def proxy_yes(proxy_usage: ProxyUsage | str | None) -> bool:
    value = getattr(proxy_usage, "value", proxy_usage) or "none"
    return value != "none"


def source_directory_status(scraper: Scraper) -> str:
    """Sources table label: Completed | Running | Needs attention."""
    if scraper.needs_rerun or scraper.qa_passed is False:
        return "Needs attention"
    if getattr(scraper, "is_running", False):
        return "Running"
    return "Completed"


def job_center_bucket(scraper: Scraper, *, now: datetime | None = None) -> str:
    """Job Center tab key: completed | scheduled | attention | running.

    Completed = successful finish today. Scheduled = waiting on next cron
    (has schedule and not finished today, or never run). Attention = QA flags.
    Running = crawl in progress (is_running).
    """
    if scraper.needs_rerun or scraper.qa_passed is False:
        return "attention"
    if getattr(scraper, "is_running", False):
        return "running"

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

    last = scraper.last_scraped
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last >= today_start:
            return "completed"

    if (
        scraper.schedule_time is not None
        or (scraper.schedule_day or "").strip()
        or scraper.run_count == 0
        or last is None
    ):
        return "scheduled"
    return "completed"
