"""Pydantic API schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Any

from pydantic import BaseModel, Field

from dataflow_platform.models import FeedDelivery, FilterFlag, ProxyUsage, ScraperStatus


class ScraperOut(BaseModel):
    scrape_id: uuid.UUID
    spider_name: str
    status: ScraperStatus
    pre_filter: str | None
    post_filter: str | None
    feed_delivery: FeedDelivery
    filter_flag: FilterFlag
    proxy_usage: ProxyUsage
    domain_name: str | None
    client_name: str | None
    start_url: str | None
    display_name: str | None = None
    scraped_columns: list[Any]
    schedule_day: str | None
    schedule_time: time | None
    last_scraped: datetime | None
    jobs_count: int | None
    scraped_count: int | None
    skipped_jobs: int | None
    duplicate_count: int | None = None
    valid_count: int | None = None
    qa_passed: bool | None
    feed_url: str | None
    total_runtime_seconds: int | None
    lifetime_scraped_count: int
    run_count: int
    needs_rerun: bool
    is_running: bool = False
    qa_notes: str | None
    created_date: date
    updated_at: datetime

    model_config = {"from_attributes": True}


class UpsertScraperRequest(BaseModel):
    spider_name: str
    status: ScraperStatus | None = None
    pre_filter: str | None = None
    post_filter: str | None = None
    feed_delivery: FeedDelivery | None = None
    filter_flag: FilterFlag | None = None
    proxy_usage: ProxyUsage | None = None
    domain_name: str | None = None
    client_name: str | None = None
    start_url: str | None = None
    display_name: str | None = None
    scraped_columns: list[Any] | None = None
    schedule_day: str | None = None
    schedule_time: time | None = None


class RunSummaryRequest(BaseModel):
    scraped_count: int = Field(ge=0)
    jobs_count: int | None = Field(default=None, ge=0)
    skipped_jobs: int | None = Field(default=None, ge=0)
    duplicate_count: int | None = Field(default=None, ge=0)
    valid_count: int | None = Field(default=None, ge=0)
    feed_url: str | None = None
    total_runtime_seconds: int | None = Field(default=None, ge=0)
    success: bool = True
    error_message: str | None = None


class HealthOut(BaseModel):
    status: str
    version: str


class ScraperRunOut(BaseModel):
    id: uuid.UUID
    scrape_id: uuid.UUID
    spider_name: str
    started_at: datetime | None
    finished_at: datetime
    status: str
    scraped_count: int
    jobs_count: int | None
    skipped_jobs: int | None
    duplicate_count: int | None = None
    valid_count: int | None = None
    total_runtime_seconds: int | None
    feed_url: str | None
    error_message: str | None
    success: bool

    model_config = {"from_attributes": True}
