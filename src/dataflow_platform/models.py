"""SQLAlchemy models for the scraper registry."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ScraperStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"


class FeedDelivery(str, enum.Enum):
    xml_browser = "xml_browser"
    json_browser = "json_browser"
    xml_download = "xml_download"
    csv_download = "csv_download"


class FilterFlag(str, enum.Enum):
    none = "none"
    pre = "pre"
    post = "post"
    both = "both"


class ProxyUsage(str, enum.Enum):
    none = "none"
    low = "low"
    high = "high"


class RunStatus(str, enum.Enum):
    succeeded = "succeeded"
    failed = "failed"


class Scraper(Base):
    """One row per scraper — config plus latest run summary and lifetime stats."""

    __tablename__ = "scrapers"

    scrape_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    spider_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    status: Mapped[ScraperStatus] = mapped_column(
        Enum(ScraperStatus, name="scraper_status", native_enum=True),
        nullable=False,
        default=ScraperStatus.active,
    )
    pre_filter: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_filter: Mapped[str | None] = mapped_column(Text, nullable=True)
    feed_delivery: Mapped[FeedDelivery] = mapped_column(
        Enum(FeedDelivery, name="feed_delivery", native_enum=True),
        nullable=False,
        default=FeedDelivery.xml_browser,
    )
    filter_flag: Mapped[FilterFlag] = mapped_column(
        Enum(FilterFlag, name="filter_flag", native_enum=True),
        nullable=False,
        default=FilterFlag.none,
    )
    proxy_usage: Mapped[ProxyUsage] = mapped_column(
        Enum(ProxyUsage, name="proxy_usage", native_enum=True),
        nullable=False,
        default=ProxyUsage.none,
    )
    domain_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    start_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    scraped_columns: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    schedule_day: Mapped[str | None] = mapped_column(String(128), nullable=True)
    schedule_time: Mapped[time | None] = mapped_column(Time, nullable=True)

    # Latest run summary (overwritten each run)
    last_scraped: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    jobs_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scraped_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skipped_jobs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duplicate_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qa_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    feed_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_runtime_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Lifetime counters
    lifetime_scraped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    needs_rerun: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    qa_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_date: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    runs: Mapped[list[ScraperRun]] = relationship(
        "ScraperRun", back_populates="scraper", cascade="all, delete-orphan"
    )


class ScraperRun(Base):
    """Append-only history of crawl run summaries."""

    __tablename__ = "scraper_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scrape_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scrapers.scrape_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    spider_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status", native_enum=True),
        nullable=False,
    )
    scraped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skipped_jobs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duplicate_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_runtime_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feed_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    scraper: Mapped[Scraper] = relationship("Scraper", back_populates="runs")
