"""Scraper registry, run history, and dashboard aggregate services."""

from __future__ import annotations

import calendar
import re
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from dataflow_platform.auth import normalize_client_name
from dataflow_platform.models import (
    FeedDelivery,
    FilterFlag,
    ProxyUsage,
    RunStatus,
    Scraper,
    ScraperRun,
    ScraperStatus,
)
from dataflow_platform.qa.rules import apply_qa_to_scraper
from dataflow_platform.status_mapping import (
    derive_display_name,
    feed_type_label,
    job_center_bucket,
    source_directory_status,
)

# Crontab and the operator UI use the server timezone (Europe/Berlin).
SCHEDULE_TZ = ZoneInfo("Europe/Berlin")

# Display-only original client schedules. Berlin (hour, minute) is a group key, not a conversion.
_DISPLAY_SCHEDULES: dict[tuple[str, int, int], tuple[str, str, time]] = {
    ("medblast", 22, 0): ("America/New_York", "Mon,Tue,Wed,Thu,Fri", time(17, 0)),
    ("hirediverse", 12, 30): ("America/Toronto", "Mon,Tue,Wed,Thu,Fri", time(8, 0)),
    ("diversifying", 10, 2): ("Europe/London", "Mon,Wed,Fri", time(8, 0)),
    ("diversifying", 11, 0): ("Europe/London", "Mon,Tue,Wed,Thu", time(8, 0)),
}
_CLIENT_DISPLAY_TZ: dict[str, str] = {
    "medblast": "America/New_York",
    "hirediverse": "America/Toronto",
    "diversifying": "Europe/London",
}


class ScraperServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def list_scrapers(
    session: Session,
    *,
    client_name: str | None = None,
    needs_rerun: bool | None = None,
    status: ScraperStatus | None = None,
    q: str | None = None,
) -> list[Scraper]:
    stmt = select(Scraper).order_by(Scraper.spider_name)
    stmt = _apply_scraper_filters(
        stmt, client_name=client_name, needs_rerun=needs_rerun, status=status, q=q
    )
    return list(session.scalars(stmt).all())


def _apply_scraper_filters(
    stmt: Select[tuple[Scraper]],
    *,
    client_name: str | None = None,
    needs_rerun: bool | None = None,
    status: ScraperStatus | None = None,
    q: str | None = None,
) -> Select[tuple[Scraper]]:
    client_name = normalize_client_name(client_name)
    if client_name:
        stmt = stmt.where(Scraper.client_name == client_name)
    if needs_rerun is not None:
        stmt = stmt.where(Scraper.needs_rerun.is_(needs_rerun))
    if status is not None:
        stmt = stmt.where(Scraper.status == status)
    query = (q or "").strip()
    if query:
        like = f"%{query}%"
        stmt = stmt.where(
            or_(
                Scraper.spider_name.ilike(like),
                Scraper.display_name.ilike(like),
                Scraper.client_name.ilike(like),
                Scraper.domain_name.ilike(like),
                Scraper.start_url.ilike(like),
                Scraper.feed_url.ilike(like),
            )
        )
    return stmt


def get_scraper_by_name(session: Session, spider_name: str) -> Scraper:
    scraper = session.scalar(select(Scraper).where(Scraper.spider_name == spider_name))
    if scraper is None:
        raise ScraperServiceError(f"Scraper {spider_name!r} not found", status_code=404)
    return scraper


def upsert_scraper(
    session: Session,
    *,
    spider_name: str,
    status: ScraperStatus | None = None,
    pre_filter: str | None = None,
    post_filter: str | None = None,
    feed_delivery: FeedDelivery | None = None,
    filter_flag: FilterFlag | None = None,
    proxy_usage: ProxyUsage | None = None,
    domain_name: str | None = None,
    client_name: str | None = None,
    start_url: str | None = None,
    display_name: str | None = None,
    scraped_columns: list[Any] | None = None,
    schedule_day: str | None = None,
    schedule_time: time | None = None,
) -> Scraper:
    client_name = normalize_client_name(client_name)
    existing = session.scalar(select(Scraper).where(Scraper.spider_name == spider_name))
    if existing is None:
        scraper = Scraper(
            scrape_id=uuid.uuid4(),
            spider_name=spider_name,
            status=status or ScraperStatus.active,
            pre_filter=pre_filter,
            post_filter=post_filter,
            feed_delivery=feed_delivery or FeedDelivery.xml_browser,
            filter_flag=filter_flag or FilterFlag.none,
            proxy_usage=proxy_usage or ProxyUsage.none,
            domain_name=domain_name,
            client_name=client_name,
            start_url=start_url,
            display_name=display_name,
            scraped_columns=scraped_columns or [],
            schedule_day=schedule_day,
            schedule_time=schedule_time,
            lifetime_scraped_count=0,
            run_count=0,
            needs_rerun=False,
        )
        session.add(scraper)
    else:
        scraper = existing
        if status is not None:
            scraper.status = status
        if pre_filter is not None:
            scraper.pre_filter = pre_filter
        if post_filter is not None:
            scraper.post_filter = post_filter
        if feed_delivery is not None:
            scraper.feed_delivery = feed_delivery
        if filter_flag is not None:
            scraper.filter_flag = filter_flag
        if proxy_usage is not None:
            scraper.proxy_usage = proxy_usage
        if domain_name is not None:
            scraper.domain_name = domain_name
        if client_name is not None:
            scraper.client_name = client_name
        if start_url is not None:
            scraper.start_url = start_url
        if display_name is not None:
            scraper.display_name = display_name
        if scraped_columns is not None:
            scraper.scraped_columns = scraped_columns
        if schedule_day is not None:
            scraper.schedule_day = schedule_day
        if schedule_time is not None:
            scraper.schedule_time = schedule_time

    session.commit()
    session.refresh(scraper)
    return scraper


def apply_run_summary(
    session: Session,
    spider_name: str,
    *,
    scraped_count: int,
    jobs_count: int | None = None,
    skipped_jobs: int | None = None,
    duplicate_count: int | None = None,
    valid_count: int | None = None,
    feed_url: str | None = None,
    total_runtime_seconds: int | None = None,
    success: bool = True,
    error_message: str | None = None,
) -> Scraper:
    """Insert a scraper_runs row and update the scraper's latest-run fields + QA."""
    scraper = get_scraper_by_name(session, spider_name)

    this_run = max(0, int(scraped_count))
    finished_at = datetime.now(timezone.utc)
    started_at = None
    if total_runtime_seconds is not None and total_runtime_seconds >= 0:
        started_at = finished_at - timedelta(seconds=int(total_runtime_seconds))

    run = ScraperRun(
        id=uuid.uuid4(),
        scrape_id=scraper.scrape_id,
        spider_name=scraper.spider_name,
        started_at=started_at,
        finished_at=finished_at,
        status=RunStatus.succeeded if success else RunStatus.failed,
        scraped_count=this_run,
        jobs_count=jobs_count,
        skipped_jobs=skipped_jobs,
        duplicate_count=duplicate_count,
        valid_count=valid_count,
        total_runtime_seconds=total_runtime_seconds,
        feed_url=feed_url,
        error_message=error_message,
        success=success,
    )
    session.add(run)

    scraper.scraped_count = this_run
    scraper.jobs_count = jobs_count
    scraper.skipped_jobs = skipped_jobs
    scraper.duplicate_count = duplicate_count
    scraper.valid_count = valid_count
    scraper.feed_url = feed_url
    scraper.total_runtime_seconds = total_runtime_seconds
    scraper.last_scraped = finished_at
    scraper.run_count = int(scraper.run_count or 0) + 1
    if success:
        scraper.lifetime_scraped_count = int(scraper.lifetime_scraped_count or 0) + this_run

    result = apply_qa_to_scraper(scraper)
    if not success:
        scraper.qa_passed = False
        scraper.needs_rerun = True
        failed = list(result.failed_rules)
        if "failed_run" not in failed:
            failed.append("failed_run")
        note = ", ".join(failed)
        if error_message:
            note = f"{note}; {error_message}" if note else error_message
        scraper.qa_notes = note

    scraper.is_running = False

    session.commit()
    session.refresh(scraper)
    return scraper


def mark_scraper_running(session: Session, spider_name: str) -> Scraper:
    """Mark a scraper as currently crawling (dashboard Running status)."""
    scraper = get_scraper_by_name(session, spider_name)
    scraper.is_running = True
    session.commit()
    session.refresh(scraper)
    return scraper


def list_recent_runs(
    session: Session,
    *,
    spider_name: str | None = None,
    client_name: str | None = None,
    limit: int = 50,
) -> list[ScraperRun]:
    client_name = normalize_client_name(client_name)
    stmt = select(ScraperRun).order_by(ScraperRun.finished_at.desc()).limit(limit)
    if spider_name:
        stmt = stmt.where(ScraperRun.spider_name == spider_name)
    if client_name:
        stmt = stmt.join(Scraper, Scraper.scrape_id == ScraperRun.scrape_id).where(
            Scraper.client_name == client_name
        )
    return list(session.scalars(stmt).all())


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _fmt_compact(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".rstrip("0").rstrip(".")
    if n >= 1_000:
        val = n / 1_000
        return f"{val:.1f}K".rstrip("0").rstrip(".")
    return str(n)


def _pct_delta(current: int, previous: int) -> float | None:
    if previous <= 0:
        return None
    delta = round(100 * (current - previous) / previous, 1)
    if delta == 0:
        return None
    # Cap display noise when prior baseline was tiny (e.g. failed partial scrape).
    return max(-100.0, min(100.0, delta))


_WEEKDAY_ALIASES = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}


def _parse_schedule_weekdays(schedule_day: str | None) -> set[int] | None:
    """Return weekday ints (Mon=0) or None for daily/unspecified."""
    raw = (schedule_day or "").strip().lower()
    if not raw or raw in {"daily", "every day", "everyday", "all", "*"}:
        return None
    found: set[int] = set()
    for part in re.split(r"[,;/|\s]+", raw):
        token = part.strip().lower()
        if not token:
            continue
        if token in _WEEKDAY_ALIASES:
            found.add(_WEEKDAY_ALIASES[token])
        elif token[:3] in _WEEKDAY_ALIASES:
            found.add(_WEEKDAY_ALIASES[token[:3]])
    return found or None


def display_schedule_for(
    client_name: str | None, berlin_time: time | None
) -> dict[str, Any] | None:
    """Original client-local schedule for Sources NEXT RUN, or None if unmapped."""
    client = normalize_client_name(client_name)
    if not client or berlin_time is None:
        return None
    row = _DISPLAY_SCHEDULES.get((client, berlin_time.hour, berlin_time.minute))
    if row is None:
        return None
    tz_name, days, local_time = row
    return {"tz": ZoneInfo(tz_name), "tz_name": tz_name, "days": days, "local_time": local_time}


def next_run_display_label(
    client_name: str | None,
    schedule_time: time | None,
    *,
    now: datetime | None = None,
    last_completed: datetime | None = None,
) -> str:
    """Sources / Job Center Next Run: client-local clock, or — if unmapped.

    If last_completed already falls on the candidate's local calendar day, skip
    that slot so Next Run is never earlier than Last Completed on the same day.
    """
    mapped = display_schedule_for(client_name, schedule_time)
    if mapped is None:
        return "—"
    now = now or datetime.now(timezone.utc)
    zone = mapped["tz"]
    cursor = now
    if last_completed is not None:
        lc = last_completed
        if lc.tzinfo is None:
            lc = lc.replace(tzinfo=timezone.utc)
        candidate = next_schedule_at(
            mapped["days"], mapped["local_time"], now=now, tz=zone
        )
        if candidate is not None and lc.astimezone(zone).date() >= candidate.astimezone(zone).date():
            cursor = candidate
    return next_schedule_label(
        mapped["days"], mapped["local_time"], now=cursor, tz=zone
    )


def display_tz_for(client_name: str | None) -> ZoneInfo | None:
    """IANA zone for Sources LAST COMPLETED, or None if unknown."""
    client = normalize_client_name(client_name)
    if not client:
        return None
    name = _CLIENT_DISPLAY_TZ.get(client)
    return ZoneInfo(name) if name else None


def last_completed_label(finished_at: datetime | None, tz: ZoneInfo | None) -> str:
    if tz is None:
        return "—"
    if finished_at is None:
        return "Never"
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    return finished_at.astimezone(tz).strftime("%b %d, %Y %I:%M %p")


def next_schedule_label(
    schedule_day: str | None,
    schedule_time: time | None,
    *,
    now: datetime | None = None,
    tz: ZoneInfo | None = None,
) -> str:
    """Human label for the next scheduled run from day + time config."""
    candidate = next_schedule_at(schedule_day, schedule_time, now=now, tz=tz)
    if candidate is None:
        if schedule_time is None and not (schedule_day or "").strip():
            return "—"
        return (schedule_day or "").strip() or "—"
    return candidate.strftime("%a, %b %d · %I:%M %p").replace(" 0", " ")


def next_schedule_at(
    schedule_day: str | None,
    schedule_time: time | None,
    *,
    now: datetime | None = None,
    tz: ZoneInfo | None = None,
) -> datetime | None:
    """Next datetime for schedule_day + schedule_time. Default tz is cron Europe/Berlin."""
    now = now or datetime.now(timezone.utc)
    if schedule_time is None:
        return None
    zone = tz or SCHEDULE_TZ
    weekdays = _parse_schedule_weekdays(schedule_day)
    cursor = now.astimezone(zone)
    for offset in range(0, 8):
        day = cursor.date() + timedelta(days=offset)
        if weekdays is not None and day.weekday() not in weekdays:
            continue
        candidate = datetime(
            day.year,
            day.month,
            day.day,
            schedule_time.hour,
            schedule_time.minute,
            schedule_time.second,
            tzinfo=zone,
        )
        if candidate > cursor:
            return candidate
    day = cursor.date() + timedelta(days=1)
    return datetime(
        day.year,
        day.month,
        day.day,
        schedule_time.hour,
        schedule_time.minute,
        schedule_time.second,
        tzinfo=zone,
    )


def _fmt_short_ago(value: datetime | None, *, now: datetime | None = None) -> str:
    if value is None:
        return "—"
    now = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    seconds = int((now - value.astimezone(timezone.utc)).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _fmt_pct(value: float | int | None) -> str | None:
    """Format percent without trailing .0 (100 not 100.0)."""
    if value is None:
        return None
    n = float(value)
    if abs(n - round(n)) < 0.05:
        return str(int(round(n)))
    return f"{n:.1f}"


def _fmt_short_date(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SCHEDULE_TZ).strftime("%b %d, %Y").replace(" 0", " ")


def throughput_label_for_day(run_day: date | None, *, today: date) -> str:
    if run_day is None:
        return "No successful runs yet"
    if run_day == today:
        return "From successful runs today"
    if run_day == today - timedelta(days=1):
        return "From successful runs yesterday"
    return f"From successful runs on {run_day.strftime('%A')}"


def _tz_day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    return start, start + timedelta(days=1)


def validation_pct_from_counts(
    valid_total: int,
    scraped_total: int,
    *,
    has_scrapers: bool,
    qa_failed: int,
) -> float | None:
    """100 * valid / scraped over items that were actually scraped.

    Empty/failed scrapers (0 scraped) do not blank the row; they just drop out of both sums.
    """
    if scraped_total > 0:
        return round(100 * valid_total / scraped_total, 1)
    if has_scrapers:
        return 0.0 if qa_failed else 100.0
    return None


def _fmt_until(value: datetime | None, *, now: datetime | None = None) -> str:
    if value is None:
        return "—"
    now = now or datetime.now(timezone.utc)
    seconds = int((value.astimezone(timezone.utc) - now).total_seconds())
    if seconds <= 0:
        return "due"
    if seconds < 3600:
        return f"Next in {seconds // 60}m"
    if seconds < 86400:
        return f"Next in {seconds // 3600}h"
    return f"Next in {seconds // 86400}d"

def feed_health(
    *,
    status: str,
    jobs: int | None,
    extracted: int | None,
) -> str:
    """green | yellow | red | empty string when not enough data."""
    if status == "Needs attention":
        return "red"
    if jobs is None or extracted is None:
        return ""
    if extracted == jobs:
        return "green"
    if extracted < jobs:
        return "yellow"
    return "yellow"


def _scraped_sum(
    session: Session,
    *,
    start: datetime,
    end: datetime,
    client_name: str | None = None,
) -> int:
    client_name = normalize_client_name(client_name)
    q = select(func.coalesce(func.sum(ScraperRun.scraped_count), 0)).where(
        ScraperRun.finished_at >= start,
        ScraperRun.finished_at < end,
        ScraperRun.success.is_(True),
    )
    if client_name:
        q = q.join(Scraper, Scraper.scrape_id == ScraperRun.scrape_id).where(
            Scraper.client_name == client_name
        )
    return int(session.scalar(q) or 0)


def dashboard_metrics(session: Session, *, client_name: str | None = None) -> dict[str, Any]:
    client_name = normalize_client_name(client_name)
    scrapers = list_scrapers(session, client_name=client_name)
    total = len(scrapers)
    active = sum(1 for s in scrapers if s.status == ScraperStatus.active)
    inactive = total - active
    alerts = sum(1 for s in scrapers if s.needs_rerun)
    active_pct = round(100 * active / total, 1) if total else 0.0
    client_count = 1 if client_name else len(distinct_clients(session))
    lifetime = sum(int(s.lifetime_scraped_count or 0) for s in scrapers)

    now = datetime.now(timezone.utc)
    today_start, tomorrow = _day_bounds(now.date())
    yesterday_start = today_start - timedelta(days=1)

    # UTC week: Monday 00:00
    week_start = today_start - timedelta(days=today_start.weekday())
    prev_week_start = week_start - timedelta(days=7)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if now.month == 1:
        prev_month_start = datetime(now.year - 1, 12, 1, tzinfo=timezone.utc)
    else:
        prev_month_start = datetime(now.year, now.month - 1, 1, tzinfo=timezone.utc)

    scraped_today = _scraped_sum(
        session, start=today_start, end=tomorrow, client_name=client_name
    )
    scraped_yesterday = _scraped_sum(
        session, start=yesterday_start, end=today_start, client_name=client_name
    )
    scraped_week = _scraped_sum(
        session, start=week_start, end=tomorrow, client_name=client_name
    )
    scraped_prev_week = _scraped_sum(
        session, start=prev_week_start, end=week_start, client_name=client_name
    )
    scraped_month = _scraped_sum(
        session, start=month_start, end=tomorrow, client_name=client_name
    )
    scraped_prev_month = _scraped_sum(
        session, start=prev_month_start, end=month_start, client_name=client_name
    )

    succ_q = select(func.count()).select_from(ScraperRun).where(
        ScraperRun.finished_at >= today_start - timedelta(days=7),
        ScraperRun.success.is_(True),
    )
    fail_q = select(func.count()).select_from(ScraperRun).where(
        ScraperRun.finished_at >= today_start - timedelta(days=7),
        ScraperRun.success.is_(False),
    )
    if client_name:
        join = Scraper.scrape_id == ScraperRun.scrape_id
        succ_q = succ_q.join(Scraper, join).where(Scraper.client_name == client_name)
        fail_q = fail_q.join(Scraper, join).where(Scraper.client_name == client_name)

    succ = int(session.scalar(succ_q) or 0)
    fail = int(session.scalar(fail_q) or 0)
    total_runs = succ + fail
    success_rate = round(100 * succ / total_runs, 1) if total_runs else None

    # ponytail: avg items/min from last successful run's calendar day (Europe/Berlin)
    last_run_q = select(func.max(ScraperRun.finished_at)).where(ScraperRun.success.is_(True))
    if client_name:
        last_run_q = last_run_q.join(Scraper, Scraper.scrape_id == ScraperRun.scrape_id).where(
            Scraper.client_name == client_name
        )
    last_at = session.scalar(last_run_q)
    today_berlin = datetime.now(SCHEDULE_TZ).date()
    if last_at is None:
        throughput = 0
        throughput_label = throughput_label_for_day(None, today=today_berlin)
    else:
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
        run_day = last_at.astimezone(SCHEDULE_TZ).date()
        day_start, day_end = _tz_day_bounds(run_day, SCHEDULE_TZ)
        runtime_q = (
            select(
                func.coalesce(func.sum(ScraperRun.scraped_count), 0),
                func.coalesce(func.sum(ScraperRun.total_runtime_seconds), 0),
            )
            .where(
                ScraperRun.finished_at >= day_start,
                ScraperRun.finished_at < day_end,
                ScraperRun.success.is_(True),
                ScraperRun.total_runtime_seconds.is_not(None),
                ScraperRun.total_runtime_seconds > 0,
            )
        )
        if client_name:
            runtime_q = runtime_q.join(
                Scraper, Scraper.scrape_id == ScraperRun.scrape_id
            ).where(Scraper.client_name == client_name)
        row = session.execute(runtime_q).one()
        items_sum, runtime_sum = int(row[0] or 0), int(row[1] or 0)
        throughput = round(items_sum / (runtime_sum / 60), 1) if runtime_sum > 0 else 0
        throughput_label = throughput_label_for_day(run_day, today=today_berlin)

    return {
        "total": total,
        "active": active,
        "inactive": inactive,
        "active_pct": active_pct,
        "active_pct_label": _fmt_pct(active_pct),
        "client_count": client_count,
        "alerts": alerts,
        "success_rate": success_rate,
        "scraped_today": scraped_today,
        "scraped_today_fmt": f"{scraped_today:,}",
        "scraped_yesterday": scraped_yesterday,
        "scraped_yesterday_fmt": f"{scraped_yesterday:,}",
        "last_updated_ago": _ago(last_at) if last_at else None,
        "urls_delta_pct": _pct_delta(scraped_today, scraped_yesterday),
        "scraped_week_delta_pct": _pct_delta(scraped_week, scraped_prev_week),
        "scraped_month_delta_pct": _pct_delta(scraped_month, scraped_prev_month),
        "throughput_per_min": throughput,
        "throughput_label": throughput_label,
        "lifetime": lifetime,
        "lifetime_fmt": f"{lifetime:,}",
        "client_name": client_name,
    }


def overview_series(
    session: Session,
    *,
    year: int,
    month: int,
    client_name: str | None = None,
) -> dict[str, Any]:
    client_name = normalize_client_name(client_name)
    days_in_month = calendar.monthrange(year, month)[1]
    month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        month_end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

    stmt = (
        select(
            func.date_trunc("day", ScraperRun.finished_at).label("day"),
            func.coalesce(func.sum(ScraperRun.scraped_count), 0),
        )
        .where(
            ScraperRun.finished_at >= month_start,
            ScraperRun.finished_at < month_end,
            ScraperRun.success.is_(True),
        )
        .group_by("day")
        .order_by("day")
    )
    if client_name:
        stmt = stmt.join(Scraper, Scraper.scrape_id == ScraperRun.scrape_id).where(
            Scraper.client_name == client_name
        )

    by_day: dict[int, int] = defaultdict(int)
    for day_ts, total in session.execute(stmt).all():
        if day_ts is None:
            continue
        if isinstance(day_ts, datetime):
            by_day[day_ts.day] = int(total)
        else:
            by_day[int(str(day_ts)[-2:])] = int(total)

    daily = [by_day.get(d, 0) for d in range(1, days_in_month + 1)]
    max_val = max(daily) if daily else 0
    # SVG height factor: higher scrape → lower y (0 top). Normalize to 0.2–0.85 band.
    normalized = [
        (0.85 - (v / max_val) * 0.65) if max_val else 0.7 for v in daily
    ]

    now = datetime.now(timezone.utc)
    today_start, tomorrow = _day_bounds(now.date())
    week_start = today_start - timedelta(days=now.weekday())
    year_start = datetime(year, 1, 1, tzinfo=timezone.utc)
    year_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    is_current_year = year == now.year

    def _sum_since(start: datetime, end: datetime | None = None) -> int:
        q = select(func.coalesce(func.sum(ScraperRun.scraped_count), 0)).where(
            ScraperRun.finished_at >= start,
            ScraperRun.success.is_(True),
        )
        if end is not None:
            q = q.where(ScraperRun.finished_at < end)
        if client_name:
            q = q.join(Scraper, Scraper.scrape_id == ScraperRun.scrape_id).where(
                Scraper.client_name == client_name
            )
        return int(session.scalar(q) or 0)

    year_total = _sum_since(year_start, year_end)
    if is_current_year:
        today_total = _sum_since(today_start, tomorrow)
        week_total = _sum_since(week_start, tomorrow)
        month_total = sum(daily)
        period = {
            "mode": "current",
            "today": today_total,
            "today_fmt": _fmt_compact(today_total),
            "week": week_total,
            "week_fmt": _fmt_compact(week_total),
            "month": month_total,
            "month_fmt": _fmt_compact(month_total),
            "year": year_total,
            "year_fmt": _fmt_compact(year_total),
        }
    else:
        period = {
            "mode": "past",
            "today": None,
            "today_fmt": "—",
            "week": None,
            "week_fmt": "—",
            "month": None,
            "month_fmt": "—",
            "year": year_total,
            "year_fmt": _fmt_compact(year_total),
        }

    tip_day = min(12, days_in_month)
    tip_value = daily[tip_day - 1] if daily else 0

    return {
        "year": year,
        "month": month,
        "days": days_in_month,
        "daily": daily,
        "normalized": normalized,
        "tip_day": tip_day,
        "tip_value": tip_value,
        "is_current_year": is_current_year,
        "period": period,
    }


def _ago(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    seconds = int((datetime.now(timezone.utc) - value.astimezone(timezone.utc)).total_seconds())
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _has_schedule(scraper: Any) -> bool:
    return bool(
        scraper.schedule_time is not None
        or (scraper.schedule_day or "").strip()
        or scraper.run_count == 0
        or scraper.last_scraped is None
    )


def _finished_successfully_today(scraper: Any, *, today_start: datetime) -> bool:
    if scraper.needs_rerun or scraper.qa_passed is False:
        return False
    last = scraper.last_scraped
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return last >= today_start


def scheduled_badge_count(scrapers: list[Any], *, now: datetime | None = None) -> int:
    """Scheduled tab badge: has schedule, not completed today, not running (includes Attention)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    n = 0
    for s in scrapers:
        if getattr(s, "is_running", False):
            continue
        if _finished_successfully_today(s, today_start=today_start):
            continue
        if _has_schedule(s):
            n += 1
    return n


def job_center(
    session: Session, *, client_name: str | None = None, limit: int = 5
) -> dict[str, Any]:
    scrapers = list_scrapers(session, client_name=client_name)
    now = datetime.now(timezone.utc)
    today_start, _ = _day_bounds(now.date())

    rows: list[dict[str, Any]] = []
    counts = {"completed": 0, "scheduled": 0, "attention": 0, "running": 0}

    for s in scrapers:
        bucket = job_center_bucket(s)
        # "completed today" only if finished today; older successes stay out of completed tab
        if bucket == "completed":
            ts = s.last_scraped
            if ts is None:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < today_start:
                continue
        counts[bucket] = counts.get(bucket, 0) + 1

        name = derive_display_name(s.spider_name, s.display_name)
        info = "—"
        if bucket == "attention":
            info = (s.qa_notes or "Needs attention").split(",")[0].strip()
        elif bucket == "scheduled":
            info = next_run_display_label(
                s.client_name, s.schedule_time, now=now, last_completed=s.last_scraped
            )
        elif bucket == "completed":
            info = f"{s.scraped_count or 0} items"

        rows.append(
            {
                "name": name,
                "spider_name": s.spider_name,
                "status": bucket,
                "info": info,
                "time": _ago(s.last_scraped),
            }
        )

    counts["completed_today"] = counts["completed"]
    # Badge includes Attention; rows stay exclusive (attention scrapers stay on that tab).
    counts["scheduled"] = scheduled_badge_count(scrapers, now=now)
    # Full counts; at most `limit` display rows per status bucket.
    display: list[dict[str, Any]] = []
    for bucket in ("completed", "scheduled", "attention"):
        display.extend([r for r in rows if r["status"] == bucket][:limit])
    return {"counts": counts, "jobs": display}


def activity_feed(
    session: Session, *, client_name: str | None = None, limit: int = 5
) -> list[dict[str, Any]]:
    runs = list_recent_runs(session, client_name=client_name, limit=limit)
    names = {
        s.spider_name: derive_display_name(s.spider_name, s.display_name)
        for s in list_scrapers(session, client_name=client_name)
    }
    items: list[dict[str, Any]] = []
    for run in runs:
        label = names.get(run.spider_name) or derive_display_name(run.spider_name)
        if run.success:
            text = f"{label} completed successfully"
            cls = "ok"
        else:
            text = f"{label} requires attention"
            cls = "err"
        items.append({"text": text, "time": _ago(run.finished_at), "cls": cls})
    return items


def top_jobs(
    session: Session,
    *,
    client_name: str | None = None,
    limit: int = 5,
    sort: str = "count",
) -> list[dict[str, Any]]:
    scrapers = [
        s
        for s in list_scrapers(session, client_name=client_name)
        if (s.scraped_count or 0) > 0 or (s.jobs_count or 0) > 0
    ]

    def coverage_pct(s: Scraper) -> float:
        if s.jobs_count and s.jobs_count > 0 and s.scraped_count is not None:
            return round(100 * min(1.0, s.scraped_count / s.jobs_count), 1)
        if s.qa_passed is True:
            return 100.0
        if s.qa_passed is False:
            return 0.0
        return 0.0

    def volume(s: Scraper) -> int:
        return int(s.scraped_count or s.jobs_count or 0)

    if sort == "success":
        scrapers.sort(key=lambda s: (coverage_pct(s), volume(s)), reverse=True)
    else:
        scrapers.sort(key=lambda s: (volume(s), coverage_pct(s)), reverse=True)

    selected = scrapers[:limit]
    max_count = max((volume(s) for s in selected), default=1) or 1
    return [
        {
            "name": derive_display_name(s.spider_name, s.display_name),
            "spider_name": s.spider_name,
            "count": volume(s),
            "pct": round(100 * volume(s) / max_count, 1),
            "coverage_pct": coverage_pct(s),
        }
        for s in selected
    ]


def _feed_label(feed_url: str | None) -> str:
    """Short feed link text — teamcrawlers brand when hosted there, else domain."""
    if not feed_url:
        return "—"
    host = _host(feed_url)
    if host == "—":
        return "—"
    if "teamcrawlers" in host.lower():
        return "teamcrawlers"
    return host


def _host(url: str | None) -> str:
    """Domain only: strip scheme, www, port, and path."""
    if not url:
        return "—"
    raw = url.strip()
    host = urlparse(raw).netloc
    if not host:
        host = raw.replace("https://", "").replace("http://", "").split("/")[0]
    host = host.split("@")[-1].split(":")[0]
    if host.lower().startswith("www."):
        host = host[4:]
    return host or "—"


_SOURCES_SORT_KEYS: dict[str, Any] = {
    "client": lambda r: (r["client"] or "").lower(),
    "scraper": lambda r: (r["scraper"] or "").lower(),
    "source": lambda r: (r["source_host"] or "").lower(),
    "feed": lambda r: (r["feed"] or "").lower(),
    "type": lambda r: (r["type"] or "").lower(),
    "jobs": lambda r: r["jobs"],
    "extracted": lambda r: r["extracted"],
    "health": lambda r: r["health"] or "",
    "status": lambda r: r["status"] or "",
    "schedule": lambda r: (r["schedule"] or "").lower(),
    "created_at": lambda r: r["created_at"] or "",
    "updated": lambda r: r["updated"] or "",
}


def sort_sources_rows(
    rows: list[dict[str, Any]],
    *,
    sort: str = "client",
    order: str = "asc",
) -> list[dict[str, Any]]:
    key_fn = _SOURCES_SORT_KEYS.get(sort) or _SOURCES_SORT_KEYS["client"]
    reverse = (order or "asc").lower() == "desc"
    return sorted(rows, key=key_fn, reverse=reverse)


def sources_rows(
    session: Session,
    *,
    client_name: str | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    scrapers = list_scrapers(session, client_name=client_name, q=q)
    now = datetime.now(timezone.utc)
    today_start, _ = _day_bounds(now.date())
    yesterday_start = today_start - timedelta(days=1)

    yday_by_scrape: dict[uuid.UUID, ScraperRun] = {}
    first_run_by_scrape: dict[uuid.UUID, datetime] = {}
    last_ok_by_scrape: dict[uuid.UUID, datetime] = {}
    if scrapers:
        ids = [s.scrape_id for s in scrapers]
        yday_stmt = (
            select(ScraperRun)
            .where(
                ScraperRun.success.is_(True),
                ScraperRun.finished_at >= yesterday_start,
                ScraperRun.finished_at < today_start,
                ScraperRun.scrape_id.in_(ids),
            )
            .order_by(ScraperRun.scrape_id, ScraperRun.finished_at.desc())
        )
        for run in session.scalars(yday_stmt).all():
            if run.scrape_id not in yday_by_scrape:
                yday_by_scrape[run.scrape_id] = run

        first_stmt = (
            select(ScraperRun.scrape_id, func.min(ScraperRun.finished_at))
            .where(ScraperRun.scrape_id.in_(ids))
            .group_by(ScraperRun.scrape_id)
        )
        for scrape_id, first_at in session.execute(first_stmt).all():
            if first_at is not None:
                first_run_by_scrape[scrape_id] = first_at

        last_ok_stmt = (
            select(ScraperRun.scrape_id, func.max(ScraperRun.finished_at))
            .where(ScraperRun.success.is_(True), ScraperRun.scrape_id.in_(ids))
            .group_by(ScraperRun.scrape_id)
        )
        for scrape_id, last_at in session.execute(last_ok_stmt).all():
            if last_at is not None:
                last_ok_by_scrape[scrape_id] = last_at

    rows: list[dict[str, Any]] = []
    for s in scrapers:
        status = source_directory_status(s)
        feed = _feed_label(s.feed_url) if s.feed_url else "—"
        last_ok = last_ok_by_scrape.get(s.scrape_id)
        schedule = next_run_display_label(
            s.client_name, s.schedule_time, now=now, last_completed=last_ok
        )
        updated = last_completed_label(
            last_ok,
            display_tz_for(s.client_name),
        )

        jobs = int(s.jobs_count) if s.jobs_count is not None else None
        extracted = int(s.scraped_count) if s.scraped_count is not None else None
        health = feed_health(status=status, jobs=jobs, extracted=extracted)

        yday = yday_by_scrape.get(s.scrape_id)
        jobs_delta_pct = None
        extracted_delta_pct = None
        if yday is not None:
            if jobs is not None and yday.jobs_count:
                jobs_delta_pct = _pct_delta(jobs, int(yday.jobs_count))
            if extracted is not None and yday.scraped_count:
                extracted_delta_pct = _pct_delta(extracted, int(yday.scraped_count))

        first_at = first_run_by_scrape.get(s.scrape_id)
        if first_at is not None:
            if first_at.tzinfo is None:
                first_at = first_at.replace(tzinfo=timezone.utc)
            created_at = first_at.astimezone(timezone.utc).strftime("%b %d, %Y %I:%M %p")
        elif s.created_date is not None:
            created_at = s.created_date.strftime("%b %d, %Y")
        else:
            created_at = "—"

        rows.append(
            {
                "client": s.client_name or "—",
                "scraper": derive_display_name(s.spider_name, s.display_name),
                "spider_name": s.spider_name,
                "source": s.start_url or "",
                "source_host": _host(s.start_url),
                "feed": feed,
                "feed_url": s.feed_url or "",
                "type": feed_type_label(s.feed_delivery),
                "jobs": jobs if jobs is not None else 0,
                "extracted": extracted if extracted is not None else 0,
                "jobs_delta_pct": jobs_delta_pct,
                "extracted_delta_pct": extracted_delta_pct,
                "health": health,
                "status": status,
                "schedule": schedule,
                "created_at": created_at,
                "updated": updated,
                "needs_rerun": s.needs_rerun,
                "detail_url": f"/dashboard/scrapers/{s.spider_name}",
            }
        )
    return rows


def spider_period_stats(session: Session, *, spider_name: str) -> dict[str, Any]:
    """Today / week / month / year scraped totals for one spider from scraper_runs."""
    now = datetime.now(timezone.utc)
    today_start, tomorrow = _day_bounds(now.date())
    week_start = today_start - timedelta(days=now.weekday())
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    year_start = datetime(now.year, 1, 1, tzinfo=timezone.utc)

    def _sum(start: datetime, end: datetime) -> int:
        q = select(func.coalesce(func.sum(ScraperRun.scraped_count), 0)).where(
            ScraperRun.spider_name == spider_name,
            ScraperRun.success.is_(True),
            ScraperRun.finished_at >= start,
            ScraperRun.finished_at < end,
        )
        return int(session.scalar(q) or 0)

    today = _sum(today_start, tomorrow)
    week = _sum(week_start, tomorrow)
    month = _sum(month_start, tomorrow)
    year = _sum(year_start, tomorrow)
    return {
        "today": today,
        "today_fmt": _fmt_compact(today),
        "week": week,
        "week_fmt": _fmt_compact(week),
        "month": month,
        "month_fmt": _fmt_compact(month),
        "year": year,
        "year_fmt": _fmt_compact(year),
    }


def spider_previous_run_delta(session: Session, *, spider_name: str) -> dict[str, Any]:
    """Compare latest two successful runs for scraped delta %."""
    runs = list(
        session.scalars(
            select(ScraperRun)
            .where(ScraperRun.spider_name == spider_name, ScraperRun.success.is_(True))
            .order_by(ScraperRun.finished_at.desc())
            .limit(2)
        ).all()
    )
    if not runs:
        return {"scraped_delta_pct": None, "prev_scraped": None}
    current = int(runs[0].scraped_count or 0)
    prev = int(runs[1].scraped_count or 0) if len(runs) > 1 else None
    return {
        "scraped_delta_pct": _pct_delta(current, prev) if prev is not None else None,
        "prev_scraped": prev,
    }


_VOLUME_RANGES = ("7d", "30d", "90d", "1y", "all")


def spider_volume_series(session: Session, *, spider_name: str) -> dict[str, Any]:
    """Daily scraped volume series for detail chart tabs (7d/30d/90d/1y/all)."""
    now = datetime.now(timezone.utc)
    today = now.date()
    lifetime = int(
        session.scalar(
            select(func.coalesce(func.sum(ScraperRun.scraped_count), 0)).where(
                ScraperRun.spider_name == spider_name,
                ScraperRun.success.is_(True),
            )
        )
        or 0
    )
    run_count = int(
        session.scalar(
            select(func.count()).select_from(ScraperRun).where(
                ScraperRun.spider_name == spider_name
            )
        )
        or 0
    )

    def _range_days(key: str) -> int | None:
        return {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(key)

    out: dict[str, Any] = {"lifetime": lifetime, "run_count": run_count, "ranges": {}}
    for key in _VOLUME_RANGES:
        days = _range_days(key)
        if days is None:
            # all: last 90 day buckets max for chart readability, full sum for total
            start_day = today - timedelta(days=89)
            start_dt, _ = _day_bounds(start_day)
            period_total = lifetime
        else:
            start_day = today - timedelta(days=days - 1)
            start_dt, _ = _day_bounds(start_day)
            end_dt = _day_bounds(today)[1]
            period_total = int(
                session.scalar(
                    select(func.coalesce(func.sum(ScraperRun.scraped_count), 0)).where(
                        ScraperRun.spider_name == spider_name,
                        ScraperRun.success.is_(True),
                        ScraperRun.finished_at >= start_dt,
                        ScraperRun.finished_at < end_dt,
                    )
                )
                or 0
            )

        # prior window of same length for delta
        if days is not None:
            prior_end = start_dt
            prior_start = prior_end - timedelta(days=days)
            prior_total = int(
                session.scalar(
                    select(func.coalesce(func.sum(ScraperRun.scraped_count), 0)).where(
                        ScraperRun.spider_name == spider_name,
                        ScraperRun.success.is_(True),
                        ScraperRun.finished_at >= prior_start,
                        ScraperRun.finished_at < prior_end,
                    )
                )
                or 0
            )
            delta_pct = _pct_delta(period_total, prior_total)
        else:
            delta_pct = None

        rows = session.execute(
            select(
                func.date_trunc("day", ScraperRun.finished_at).label("day"),
                func.coalesce(func.sum(ScraperRun.scraped_count), 0),
            )
            .where(
                ScraperRun.spider_name == spider_name,
                ScraperRun.success.is_(True),
                ScraperRun.finished_at >= start_dt,
            )
            .group_by("day")
            .order_by("day")
        ).all()
        by_day: dict[date, int] = {}
        for day_val, total in rows:
            if day_val is None:
                continue
            if isinstance(day_val, datetime):
                d = day_val.astimezone(timezone.utc).date()
            else:
                d = day_val
            by_day[d] = int(total or 0)

        chart_days = 90 if days is None else days
        labels: list[str] = []
        values: list[int] = []
        for i in range(chart_days):
            d = start_day + timedelta(days=i)
            if d > today:
                break
            labels.append(d.strftime("%b %d"))
            values.append(by_day.get(d, 0))

        peak = max(values) if values else 0
        normalized = [round(v / peak, 4) if peak else 0.0 for v in values]
        out["ranges"][key] = {
            "labels": labels,
            "values": values,
            "normalized": normalized,
            "period_total": period_total,
            "period_total_fmt": _fmt_compact(period_total),
            "delta_pct": delta_pct,
        }
    return out


def spider_detail_qa(scraper: Scraper) -> dict[str, Any]:
    """QA report block for detail page from latest scraper snapshot."""
    jobs = int(scraper.jobs_count or 0)
    scraped = int(scraper.scraped_count or 0)
    skipped = int(scraper.skipped_jobs or 0)
    dupes = int(scraper.duplicate_count or 0)
    valid = int(scraper.valid_count or 0)
    jobs_pct = min(100.0, round(100 * scraped / jobs, 1)) if jobs > 0 else None
    scraped_pct = 100.0 if scraped > 0 or jobs == 0 else 0.0
    skipped_pct = round(100 * skipped / scraped, 1) if scraped > 0 else 0.0
    dupe_pct = round(100 * dupes / scraped, 1) if scraped > 0 else 0.0
    if valid > 0 and scraped > 0:
        complete_pct = min(100.0, round(100 * valid / scraped, 1))
    elif scraped > 0 and scraper.qa_passed is not False:
        complete_pct = 100.0
    else:
        complete_pct = None
    passed = not scraper.needs_rerun and scraper.qa_passed is not False
    if passed:
        completeness_label = "Excellent" if (complete_pct or 0) >= 95 else "Good"
        banner = "All quality checks passed. Data looks good!"
        note = "All expected jobs were scraped successfully."
    else:
        completeness_label = "Needs review"
        banner = scraper.qa_notes or "Quality issues detected."
        note = scraper.qa_notes or "Needs attention."
    return {
        "passed": passed,
        "jobs": jobs,
        "scraped": scraped,
        "skipped": skipped,
        "duplicates": dupes,
        "valid": valid,
        "jobs_pct": jobs_pct,
        "scraped_pct": scraped_pct,
        "skipped_pct": skipped_pct,
        "dupe_pct": dupe_pct,
        "complete_pct": complete_pct,
        "completeness_label": completeness_label,
        "banner": banner,
        "note": note,
    }


def distinct_clients(session: Session) -> list[str]:
    scrapers = list_scrapers(session)
    return sorted({s.client_name for s in scrapers if s.client_name}, key=str.lower)


def schedule_summary(session: Session, *, client_name: str | None = None) -> dict[str, Any]:
    scrapers = list_scrapers(session, client_name=client_name)
    jc = job_center(session, client_name=client_name)
    upcoming = [s for s in scrapers if job_center_bucket(s) == "scheduled"]
    next_crawl = "—"
    times = [s.schedule_time for s in upcoming if s.schedule_time]
    if times:
        soonest = min(times)
        next_crawl = soonest.strftime("%I:%M %p").lstrip("0")
    return {
        "completed": jc["counts"].get("completed", 0),
        "running": 0,
        "upcoming": len(upcoming),
        "next_crawl": next_crawl,
    }


def coverage_quality(session: Session, *, client_name: str | None = None) -> dict[str, Any]:
    """Fleet Data Quality card: score, metric rows, summary bar, trust tiles."""
    from dataflow_platform.config import get_settings

    scrapers = list_scrapers(session, client_name=client_name)
    now = datetime.now(timezone.utc)
    stale_hours = get_settings().qa_stale_hours

    jobs_total = scraped_total = duplicate_total = valid_total = 0
    qa_passed = qa_failed = needs_rerun = with_feed = stale_or_attention = 0
    last_scraped_max: datetime | None = None
    next_run: datetime | None = None

    for s in scrapers:
        jobs = int(s.jobs_count or 0)
        scraped = int(s.scraped_count or 0)
        if jobs > 0 and s.scraped_count is not None:
            jobs_total += jobs
            scraped_total += scraped
        elif s.scraped_count is not None:
            scraped_total += scraped
        duplicate_total += int(s.duplicate_count or 0)
        valid_total += int(s.valid_count or 0)
        if s.qa_passed is True:
            qa_passed += 1
        elif s.qa_passed is False:
            qa_failed += 1
        if s.needs_rerun:
            needs_rerun += 1
        if s.feed_url:
            with_feed += 1
        if s.needs_rerun or s.qa_passed is False:
            stale_or_attention += 1
        if s.last_scraped:
            ts = s.last_scraped
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if last_scraped_max is None or ts > last_scraped_max:
                last_scraped_max = ts
        candidate = next_schedule_at(s.schedule_day, s.schedule_time, now=now)
        if candidate and (next_run is None or candidate < next_run):
            next_run = candidate

    scraper_total = len(scrapers)
    completeness = (
        min(100.0, round(100 * scraped_total / jobs_total, 1)) if jobs_total > 0 else None
    )
    duplicates = (
        round(100 * duplicate_total / scraped_total, 1) if scraped_total > 0 else None
    )
    valid_records = (
        round(100 * valid_total / scraped_total, 1) if scraped_total > 0 else None
    )

    score = completeness if completeness is not None else (
        valid_records if valid_records is not None else None
    )
    healthy = stale_or_attention == 0 and scrapers

    if stale_or_attention:
        summary = f"{stale_or_attention} need attention"
        summary_detail = "Data quality issues detected"
    elif scrapers:
        summary = "All clear"
        summary_detail = "No data quality issues detected"
    else:
        summary = "No scrapers yet"
        summary_detail = "Seed scrapers to see quality"

    validation_pct = validation_pct_from_counts(
        valid_total,
        scraped_total,
        has_scrapers=bool(scrapers),
        qa_failed=qa_failed,
    )
    validation_ok = validation_pct is not None and validation_pct >= 90 and qa_failed == 0

    fresh = True
    if last_scraped_max is None:
        fresh = False
    else:
        age = now - last_scraped_max.astimezone(timezone.utc)
        if age > timedelta(hours=stale_hours):
            fresh = False
    if needs_rerun:
        fresh = False
    freshness_status = "Up to date" if fresh and scrapers else ("Stale" if scrapers else "—")
    freshness_detail = (
        "Data is up to date" if fresh and scrapers else (
            "Feeds may be stale" if scrapers else "No runs yet"
        )
    )
    last_check = _fmt_short_ago(last_scraped_max, now=now)
    last_check_date = _fmt_short_date(last_scraped_max)
    next_check = _fmt_until(next_run, now=now)

    feeds_healthy = max(0, scraper_total - stale_or_attention)
    published_pct = (
        round(100 * with_feed / scraper_total) if scraper_total else None
    )

    score_pct = float(score) if score is not None else 0.0
    ring = "#6bbf8a" if healthy else "#e8926f"
    track = "#e8e6e1"
    donut_css = (
        f"conic-gradient({ring} 0 {score_pct}%, {track} {score_pct}% 100%)"
        if scrapers
        else None
    )

    segments = [
        {
            "key": "completeness",
            "label": "Completeness (Coverage)",
            "color": "#e8926f",
            "pct": completeness,
            "detail": f"{scraped_total:,} / {jobs_total:,}" if jobs_total else "—",
        },
        {
            "key": "valid",
            "label": "Data Validation",
            "color": "#5b8def",
            "pct": validation_pct,
            "detail": "All Records passed validation rules",
        },
    ]

    return {
        "completeness": completeness,
        "completeness_label": _fmt_pct(completeness),
        "duplicates": duplicates,
        "valid_records": valid_records,
        "jobs_total": jobs_total,
        "scraped_total": scraped_total,
        "duplicate_total": duplicate_total,
        "valid_total": valid_total,
        "qa_passed": qa_passed,
        "qa_failed": qa_failed,
        "needs_rerun": needs_rerun,
        "with_feed": with_feed,
        "stale_or_attention": stale_or_attention,
        "scraper_total": scraper_total,
        "summary": summary,
        "summary_detail": summary_detail,
        "segments": segments,
        "donut_css": donut_css,
        "score": score,
        "score_label": _fmt_pct(score),
        "healthy": bool(healthy),
        "validation_pct": validation_pct,
        "validation_label": _fmt_pct(validation_pct),
        "validation_ok": validation_ok,
        "freshness_status": freshness_status,
        "freshness_detail": freshness_detail,
        "last_check": last_check,
        "last_check_date": last_check_date,
        "next_check": next_check,
        "feeds_healthy": feeds_healthy,
        "published_pct": published_pct,
        "issues_detected": stale_or_attention,
    }
