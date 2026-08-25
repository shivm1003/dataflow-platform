"""Status mapping and run dual-write checks."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from dataflow_platform.models import (
    FeedDelivery,
    ProxyUsage,
    RunStatus,
    Scraper,
    ScraperRun,
    ScraperStatus,
)
from dataflow_platform.services import (
    _fmt_pct,
    _pct_delta,
    apply_run_summary,
    scheduled_badge_count,
    throughput_label_for_day,
    validation_pct_from_counts,
)
from dataflow_platform.status_mapping import (
    derive_display_name,
    feed_type_label,
    job_center_bucket,
    proxy_yes,
    source_directory_status,
)


def test_pct_delta() -> None:
    assert _pct_delta(3014, 2972) == 1.4
    assert _pct_delta(90, 100) == -10.0
    assert _pct_delta(10, 0) is None
    assert _pct_delta(0, 0) is None
    assert _pct_delta(100, 100) is None
    assert _pct_delta(62, 1) == 100.0
    assert _pct_delta(0, 100) == -100.0
    assert _pct_delta(691, 2) == 100.0


def test_fmt_pct_drops_trailing_zero() -> None:
    assert _fmt_pct(100.0) == "100"
    assert _fmt_pct(4.2) == "4.2"
    assert _fmt_pct(0) == "0"
    assert _fmt_pct(None) is None


def test_validation_pct_uses_remaining_scraped_when_one_fails() -> None:
    # 27 scrapers with title+description, 1 empty fail (0/0) — not blank, not 0%.
    assert (
        validation_pct_from_counts(2528, 2528, has_scrapers=True, qa_failed=1) == 100.0
    )
    # Unreported valid_count still shows 0% of remaining scraped, not a blank row.
    assert validation_pct_from_counts(0, 2528, has_scrapers=True, qa_failed=1) == 0.0
    assert validation_pct_from_counts(0, 0, has_scrapers=True, qa_failed=1) == 0.0
    assert validation_pct_from_counts(0, 0, has_scrapers=False, qa_failed=0) is None
    assert validation_pct_from_counts(75, 80, has_scrapers=True, qa_failed=0) == 93.8


def test_host_and_feed_label() -> None:
    from dataflow_platform.services import _feed_label, _host, sort_sources_rows

    assert _host("https://www.jobs.nhs.uk/path") == "jobs.nhs.uk"
    assert _host("http://careers.baptistonline.org:443/") == "careers.baptistonline.org"
    assert _feed_label(
        "https://teamcrawlers-feeds.nyc3.cdn.digitaloceanspaces.com/medblast/x.xml"
    ) == "teamcrawlers"
    assert _feed_label("https://cdn.example.com/feed.xml") == "cdn.example.com"
    rows = [
        {"client": "B", "scraper": "z", "source_host": "b.com", "feed": "teamcrawlers",
         "type": "XML", "jobs": 2, "extracted": 1, "health": "green", "status": "Completed",
         "schedule": "Daily", "created_at": "b", "updated": "b"},
        {"client": "A", "scraper": "a", "source_host": "a.com", "feed": "teamcrawlers",
         "type": "JSON", "jobs": 10, "extracted": 9, "health": "yellow", "status": "Running",
         "schedule": "Mon", "created_at": "a", "updated": "a"},
    ]
    assert sort_sources_rows(rows, sort="client", order="asc")[0]["client"] == "A"
    assert sort_sources_rows(rows, sort="jobs", order="desc")[0]["jobs"] == 10


def test_next_schedule_and_feed_health() -> None:
    from datetime import time as dtime

    from dataflow_platform.services import feed_health, next_schedule_at, next_schedule_label

    now = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)  # Saturday 12:00 CEST
    label = next_schedule_label("Daily", dtime(11, 30), now=now)
    assert "11:30" in label
    # Weekday 22:00 Berlin Mon–Fri; before that clock time, next run is still today.
    monday_evening = datetime(2026, 8, 17, 17, 52, tzinfo=timezone.utc)  # 19:52 CEST
    nxt = next_schedule_at("Mon,Tue,Wed,Thu,Fri", dtime(22, 0), now=monday_evening)
    assert nxt is not None
    assert nxt.date() == date(2026, 8, 17)
    assert nxt.hour == 22
    after = datetime(2026, 8, 17, 20, 5, tzinfo=timezone.utc)  # 22:05 CEST
    nxt2 = next_schedule_at("Mon,Tue,Wed,Thu,Fri", dtime(22, 0), now=after)
    assert nxt2 is not None
    assert nxt2.date() == date(2026, 8, 18)
    assert feed_health(status="Completed", jobs=10, extracted=10) == "green"
    assert feed_health(status="Completed", jobs=0, extracted=0) == "green"
    assert feed_health(status="Completed", jobs=10, extracted=8) == "yellow"
    assert feed_health(status="Needs attention", jobs=10, extracted=10) == "red"
    assert feed_health(status="Running", jobs=None, extracted=None) == ""


def test_sources_display_schedule_map() -> None:
    from datetime import time as dtime
    from zoneinfo import ZoneInfo

    from dataflow_platform.services import (
        display_schedule_for,
        display_tz_for,
        last_completed_label,
        next_run_display_label,
        next_schedule_at,
        next_schedule_label,
    )

    ny = ZoneInfo("America/New_York")
    mb = display_schedule_for("Medblast", dtime(23, 0))
    assert mb is not None
    assert mb["days"] == "Mon,Tue,Wed,Thu,Fri"
    assert mb["local_time"] == dtime(17, 0)
    assert mb["tz"] == ny

    div12 = display_schedule_for("diversifying", dtime(10, 2))
    assert div12 is not None
    assert div12["days"] == "Mon,Wed,Fri"
    assert div12["local_time"] == dtime(8, 0)

    div20 = display_schedule_for("diversifying", dtime(11, 0))
    assert div20 is not None
    assert div20["days"] == "Mon,Tue,Wed,Thu"

    hd = display_schedule_for("hirediverse", dtime(12, 30))
    assert hd is not None
    assert hd["tz"] == ZoneInfo("America/Toronto")
    assert hd["local_time"] == dtime(8, 0)

    assert display_schedule_for("waterjobs", dtime(9, 0)) is None
    assert display_schedule_for("medblast", dtime(17, 0)) is None  # Berlin key only
    assert next_schedule_label("Mon,Tue,Wed,Thu,Fri", None) == "Mon,Tue,Wed,Thu,Fri"

    # NY 17:00 Mon–Fri, still today before 17:00.
    before = datetime(2026, 8, 18, 16, 0, tzinfo=ny)  # Tue 16:00 EDT
    nxt = next_schedule_at("Mon,Tue,Wed,Thu,Fri", dtime(17, 0), now=before, tz=ny)
    assert nxt is not None
    local = nxt.astimezone(ny)
    assert local.date() == date(2026, 8, 18)
    assert local.hour == 17

    # US/Eastern DST week: after 17:00 Fri 6 Mar 2026 EST → Mon 9 Mar 17:00 EDT.
    after_fri = datetime(2026, 3, 6, 22, 30, tzinfo=timezone.utc)  # 17:30 EST
    dst = next_schedule_at("Mon,Tue,Wed,Thu,Fri", dtime(17, 0), now=after_fri, tz=ny)
    assert dst is not None
    dst_local = dst.astimezone(ny)
    assert dst_local.date() == date(2026, 3, 9)
    assert dst_local.hour == 17
    assert dst_local.tzname() == "EDT"

    assert last_completed_label(None, None) == "—"
    assert last_completed_label(datetime(2026, 8, 18, 21, 0, tzinfo=timezone.utc), None) == "—"
    assert last_completed_label(None, ny) == "Never"
    done = datetime(2026, 8, 18, 21, 0, tzinfo=timezone.utc)  # 17:00 EDT
    assert last_completed_label(done, ny) == "Aug 18, 2026 05:00 PM"
    # Failed runs are excluded by the success=true query; helper never sees them.
    assert display_tz_for("waterjobs") is None
    assert display_tz_for("medblast") == ny

    # Job Center Scheduled uses the same client-local label as Sources Next Run.
    now = datetime(2026, 8, 18, 16, 0, tzinfo=ny)
    assert next_run_display_label("medblast", dtime(23, 0), now=now) == next_schedule_label(
        mb["days"], mb["local_time"], now=now, tz=ny
    )
    # Already completed today on the local day → Next Run skips to tomorrow's 5:00 PM.
    ran_today = datetime(2026, 8, 18, 17, 10, tzinfo=ny)
    after_run = next_run_display_label(
        "medblast", dtime(23, 0), now=now, last_completed=ran_today
    )
    assert "Aug 18" not in after_run
    assert "5:00 PM" in after_run
    nxt_dt = next_schedule_at(mb["days"], mb["local_time"], now=datetime(2026, 8, 18, 17, 0, tzinfo=ny), tz=ny)
    assert nxt_dt is not None
    assert nxt_dt.astimezone(ny).date() == date(2026, 8, 19)


def test_fleet_quality_rates() -> None:
    """Weighted completeness + dup/valid rates match plan formulas."""
    jobs_total, scraped_total = 100, 100
    assert min(100.0, round(100 * scraped_total / jobs_total, 1)) == 100.0
    jobs_total, scraped_total = 100, 80
    assert min(100.0, round(100 * scraped_total / jobs_total, 1)) == 80.0
    assert round(100 * 5 / 100, 1) == 5.0  # duplicates
    assert round(100 * 90 / 100, 1) == 90.0  # valid


def test_derive_display_name() -> None:
    assert derive_display_name("medblast_ukhealthcare") == "Ukhealthcare"
    assert derive_display_name("medblast_uk_healthcare") == "Uk Healthcare"
    assert derive_display_name("x", "UK Healthcare") == "UK Healthcare"


def test_feed_type_and_proxy() -> None:
    assert feed_type_label(FeedDelivery.xml_browser) == "XML"
    assert feed_type_label(FeedDelivery.json_browser) == "JSON"
    assert feed_type_label(FeedDelivery.csv_download) == "CSV"
    assert proxy_yes(ProxyUsage.none) is False
    assert proxy_yes(ProxyUsage.high) is True


def test_source_and_job_center_status() -> None:
    from datetime import time as dtime

    finished = SimpleNamespace(
        needs_rerun=False,
        qa_passed=True,
        last_scraped=datetime.now(timezone.utc),
        run_count=3,
        status=ScraperStatus.active,
        schedule_day="Mon,Tue,Wed,Thu,Fri",
        schedule_time=dtime(17, 0),
        is_running=False,
    )
    assert source_directory_status(finished) == "Completed"  # type: ignore[arg-type]
    assert job_center_bucket(finished) == "completed"  # type: ignore[arg-type]

    queued = SimpleNamespace(
        needs_rerun=False,
        qa_passed=None,
        last_scraped=None,
        run_count=0,
        status=ScraperStatus.active,
        schedule_day=None,
        schedule_time=None,
        is_running=False,
    )
    assert source_directory_status(queued) == "Completed"  # type: ignore[arg-type]
    assert job_center_bucket(queued) == "scheduled"  # type: ignore[arg-type]

    running = SimpleNamespace(
        needs_rerun=False,
        qa_passed=True,
        last_scraped=datetime.now(timezone.utc) - timedelta(days=1),
        run_count=3,
        status=ScraperStatus.active,
        schedule_day="Mon,Tue,Wed,Thu,Fri",
        schedule_time=dtime(17, 0),
        is_running=True,
    )
    assert source_directory_status(running) == "Running"  # type: ignore[arg-type]
    assert job_center_bucket(running) == "running"  # type: ignore[arg-type]

    waiting = SimpleNamespace(
        needs_rerun=False,
        qa_passed=True,
        last_scraped=datetime.now(timezone.utc) - timedelta(days=1),
        run_count=3,
        status=ScraperStatus.active,
        schedule_day="Mon,Tue,Wed,Thu,Fri",
        schedule_time=dtime(17, 0),
        is_running=False,
    )
    assert job_center_bucket(waiting) == "scheduled"  # type: ignore[arg-type]

    bad = SimpleNamespace(
        needs_rerun=True,
        qa_passed=False,
        last_scraped=datetime.now(timezone.utc),
        run_count=2,
        status=ScraperStatus.active,
        schedule_day=None,
        schedule_time=None,
        is_running=True,
    )
    assert source_directory_status(bad) == "Needs attention"  # type: ignore[arg-type]
    assert job_center_bucket(bad) == "attention"  # type: ignore[arg-type]

    # Badge includes Attention; rows stay exclusive via job_center_bucket.
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    yesterday = now - timedelta(days=1)
    fleet = [
        SimpleNamespace(
            needs_rerun=False,
            qa_passed=True,
            last_scraped=yesterday,
            run_count=3,
            schedule_day="Mon,Tue,Wed,Thu,Fri",
            schedule_time=dtime(22, 0),
            is_running=False,
        ),
        SimpleNamespace(
            needs_rerun=True,
            qa_passed=False,
            last_scraped=yesterday,
            run_count=2,
            schedule_day="Mon,Tue,Wed,Thu,Fri",
            schedule_time=dtime(22, 0),
            is_running=False,
        ),
        SimpleNamespace(
            needs_rerun=False,
            qa_passed=True,
            last_scraped=now,
            run_count=4,
            schedule_day="Mon,Tue,Wed,Thu,Fri",
            schedule_time=dtime(22, 0),
            is_running=False,
        ),
    ]
    assert scheduled_badge_count(fleet, now=now) == 2
    assert job_center_bucket(fleet[0], now=now) == "scheduled"
    assert job_center_bucket(fleet[1], now=now) == "attention"
    assert job_center_bucket(fleet[2], now=now) == "completed"


def test_throughput_label_for_day() -> None:
    today = date(2026, 8, 18)
    assert throughput_label_for_day(None, today=today) == "No successful runs yet"
    assert throughput_label_for_day(today, today=today) == "From successful runs today"
    assert (
        throughput_label_for_day(date(2026, 8, 17), today=today)
        == "From successful runs yesterday"
    )
    assert (
        throughput_label_for_day(date(2026, 8, 14), today=today)
        == "From successful runs on Friday"
    )


def test_apply_run_summary_dual_writes_run_row() -> None:
    scrape_id = uuid.uuid4()
    scraper = Scraper(
        scrape_id=scrape_id,
        spider_name="medblast_test",
        status=ScraperStatus.active,
        feed_delivery=FeedDelivery.xml_browser,
        filter_flag=__import__("dataflow_platform.models", fromlist=["FilterFlag"]).FilterFlag.none,
        proxy_usage=ProxyUsage.none,
        scraped_columns=[],
        lifetime_scraped_count=0,
        run_count=0,
        needs_rerun=False,
        is_running=True,
        scraped_count=None,
        jobs_count=None,
        skipped_jobs=None,
        feed_url=None,
        total_runtime_seconds=None,
        last_scraped=None,
        qa_passed=None,
        qa_notes=None,
        client_name="Medblast",
    )

    session = MagicMock()
    session.scalar.return_value = scraper

    added: list[object] = []

    def _add(obj: object) -> None:
        added.append(obj)

    session.add.side_effect = _add

    result = apply_run_summary(
        session,
        "medblast_test",
        scraped_count=12,
        jobs_count=15,
        skipped_jobs=0,
        feed_url="https://cdn.example/feed.xml",
        total_runtime_seconds=90,
        success=True,
    )

    assert result is scraper
    assert scraper.scraped_count == 12
    assert scraper.run_count == 1
    assert scraper.lifetime_scraped_count == 12
    assert len(added) == 1
    run = added[0]
    assert isinstance(run, ScraperRun)
    assert run.scrape_id == scrape_id
    assert run.spider_name == "medblast_test"
    assert run.scraped_count == 12
    assert run.success is True
    assert run.status == RunStatus.succeeded
    assert scraper.is_running is False
    session.commit.assert_called_once()


def test_ago_past_day_returns_weekday_date() -> None:
    from dataflow_platform.services import SCHEDULE_TZ, _ago

    recent = datetime.now(timezone.utc) - timedelta(hours=3)
    assert _ago(recent) == "3h ago"
    old = datetime.now(timezone.utc) - timedelta(days=2, hours=1)
    label = _ago(old)
    local = old.astimezone(SCHEDULE_TZ)
    assert label == f"{local.strftime('%a, %b')} {local.day}"
    assert "ago" not in label
