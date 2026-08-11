"""Status mapping and run dual-write checks."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
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
from dataflow_platform.services import _pct_delta, apply_run_summary
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

    from dataflow_platform.services import feed_health, next_schedule_label

    now = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)  # Saturday
    label = next_schedule_label("Daily", dtime(11, 30), now=now)
    assert "11:30" in label
    assert feed_health(status="Completed", jobs=10, extracted=10) == "green"
    assert feed_health(status="Completed", jobs=0, extracted=0) == "green"
    assert feed_health(status="Completed", jobs=10, extracted=8) == "yellow"
    assert feed_health(status="Needs attention", jobs=10, extracted=10) == "red"
    assert feed_health(status="Running", jobs=None, extracted=None) == ""


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
    )
    assert source_directory_status(queued) == "Running"  # type: ignore[arg-type]
    assert job_center_bucket(queued) == "scheduled"  # type: ignore[arg-type]

    waiting = SimpleNamespace(
        needs_rerun=False,
        qa_passed=True,
        last_scraped=datetime.now(timezone.utc) - timedelta(days=1),
        run_count=3,
        status=ScraperStatus.active,
        schedule_day="Mon,Tue,Wed,Thu,Fri",
        schedule_time=dtime(17, 0),
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
    )
    assert source_directory_status(bad) == "Needs attention"  # type: ignore[arg-type]
    assert job_center_bucket(bad) == "attention"  # type: ignore[arg-type]


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
    session.commit.assert_called_once()
