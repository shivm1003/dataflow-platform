"""FastAPI routes for scraper registry and run reporting."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from dataflow_platform import __version__
from dataflow_platform.api.schemas import (
    HealthOut,
    RunSummaryRequest,
    ScraperOut,
    ScraperRunOut,
    UpsertScraperRequest,
)
from dataflow_platform.db import SessionLocal
from dataflow_platform.models import Scraper, ScraperStatus
from dataflow_platform.services import (
    ScraperServiceError,
    activity_feed,
    apply_run_summary,
    dashboard_metrics,
    get_scraper_by_name,
    job_center,
    list_recent_runs,
    list_scrapers,
    mark_scraper_running,
    overview_series,
    sources_rows,
    top_jobs,
    upsert_scraper,
)

router = APIRouter()


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(status="ok", version=__version__)


@router.get("/scrapers", response_model=list[ScraperOut])
def get_scrapers(
    client_name: str | None = Query(default=None, alias="clientName"),
    needs_rerun: bool | None = None,
    status: ScraperStatus | None = None,
    q: str | None = None,
    session: Session = Depends(get_db),
) -> list[Scraper]:
    return list_scrapers(
        session,
        client_name=client_name,
        needs_rerun=needs_rerun,
        status=status,
        q=q,
    )


@router.get("/scrapers/{spider_name}", response_model=ScraperOut)
def get_scraper(spider_name: str, session: Session = Depends(get_db)) -> Scraper:
    try:
        return get_scraper_by_name(session, spider_name)
    except ScraperServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.put("/scrapers/{spider_name}", response_model=ScraperOut)
def put_scraper(
    spider_name: str,
    body: UpsertScraperRequest,
    session: Session = Depends(get_db),
) -> Scraper:
    if body.spider_name != spider_name:
        raise HTTPException(status_code=400, detail="spider_name in path and body must match")
    return upsert_scraper(
        session,
        spider_name=spider_name,
        status=body.status,
        pre_filter=body.pre_filter,
        post_filter=body.post_filter,
        feed_delivery=body.feed_delivery,
        filter_flag=body.filter_flag,
        proxy_usage=body.proxy_usage,
        domain_name=body.domain_name,
        client_name=body.client_name,
        start_url=body.start_url,
        display_name=body.display_name,
        scraped_columns=body.scraped_columns,
        schedule_day=body.schedule_day,
        schedule_time=body.schedule_time,
    )


@router.post("/scrapers/{spider_name}/running", response_model=ScraperOut)
def post_scraper_running(
    spider_name: str,
    session: Session = Depends(get_db),
) -> Scraper:
    """Mark scraper as Running when a crawl starts (called from Scrapy)."""
    try:
        return mark_scraper_running(session, spider_name)
    except ScraperServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/scrapers/{spider_name}/runs", response_model=ScraperOut)
def post_run_summary(
    spider_name: str,
    body: RunSummaryRequest,
    session: Session = Depends(get_db),
) -> Scraper:
    try:
        return apply_run_summary(
            session,
            spider_name,
            scraped_count=body.scraped_count,
            jobs_count=body.jobs_count,
            skipped_jobs=body.skipped_jobs,
            duplicate_count=body.duplicate_count,
            valid_count=body.valid_count,
            feed_url=body.feed_url,
            total_runtime_seconds=body.total_runtime_seconds,
            success=body.success,
            error_message=body.error_message,
        )
    except ScraperServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/scrapers/{spider_name}/runs", response_model=list[ScraperRunOut])
def get_scraper_runs(
    spider_name: str,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[ScraperRunOut]:
    try:
        get_scraper_by_name(session, spider_name)
    except ScraperServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    runs = list_recent_runs(session, spider_name=spider_name, limit=limit)
    return [
        ScraperRunOut(
            id=r.id,
            scrape_id=r.scrape_id,
            spider_name=r.spider_name,
            started_at=r.started_at,
            finished_at=r.finished_at,
            status=r.status.value if hasattr(r.status, "value") else str(r.status),
            scraped_count=r.scraped_count,
            jobs_count=r.jobs_count,
            skipped_jobs=r.skipped_jobs,
            duplicate_count=r.duplicate_count,
            valid_count=r.valid_count,
            total_runtime_seconds=r.total_runtime_seconds,
            feed_url=r.feed_url,
            error_message=r.error_message,
            success=r.success,
        )
        for r in runs
    ]


@router.get("/dashboard/metrics")
def get_dashboard_metrics(
    client: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    return dashboard_metrics(session, client_name=client or None)


@router.get("/dashboard/overview-series")
def get_overview_series(
    client: str | None = Query(default=None),
    year: int | None = None,
    month: int | None = None,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return overview_series(
        session,
        year=year or now.year,
        month=month or now.month,
        client_name=client or None,
    )


@router.get("/dashboard/job-center")
def get_job_center(
    client: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=50),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    return job_center(session, client_name=client or None, limit=limit)


@router.get("/dashboard/activity")
def get_activity(
    client: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=50),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return activity_feed(session, client_name=client or None, limit=limit)


@router.get("/dashboard/top-jobs")
def get_top_jobs(
    client: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=20),
    sort: str = Query(default="count"),
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return top_jobs(session, client_name=client or None, limit=limit, sort=sort)


@router.get("/dashboard/sources")
def get_sources(
    client: str | None = Query(default=None),
    q: str | None = None,
    session: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return sources_rows(session, client_name=client or None, q=q)
