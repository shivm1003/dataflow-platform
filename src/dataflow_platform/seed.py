"""Seed scrapers table from scrape_details.json (read-only)."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import datetime, time
from pathlib import Path
from typing import Any

from sqlalchemy import select

from dataflow_platform.config import get_settings
from dataflow_platform.db import SessionLocal
from dataflow_platform.models import (
    FeedDelivery,
    FilterFlag,
    ProxyUsage,
    Scraper,
    ScraperStatus,
)

logger = logging.getLogger(__name__)

_SCRAPED_COLUMNS_PATH = Path(__file__).with_name("scraped_columns.json")
_SCRAPED_COLUMNS_BY_SPIDER: dict[str, list[str]] | None = None


def _load_scraped_columns_map() -> dict[str, list[str]]:
    global _SCRAPED_COLUMNS_BY_SPIDER
    if _SCRAPED_COLUMNS_BY_SPIDER is not None:
        return _SCRAPED_COLUMNS_BY_SPIDER
    if not _SCRAPED_COLUMNS_PATH.is_file():
        logger.warning("scraped_columns.json missing at %s", _SCRAPED_COLUMNS_PATH)
        _SCRAPED_COLUMNS_BY_SPIDER = {}
        return _SCRAPED_COLUMNS_BY_SPIDER
    raw = json.loads(_SCRAPED_COLUMNS_PATH.read_text(encoding="utf-8"))
    _SCRAPED_COLUMNS_BY_SPIDER = {
        str(name): list(cols) for name, cols in raw.items() if isinstance(cols, list)
    }
    return _SCRAPED_COLUMNS_BY_SPIDER


def scraped_columns_for_spider(spider_name: str) -> list[str]:
    """Return item-dict keys for a spider (exact name, then case-insensitive)."""
    mapping = _load_scraped_columns_map()
    if spider_name in mapping:
        return list(mapping[spider_name])
    lowered = spider_name.lower()
    for name, cols in mapping.items():
        if name.lower() == lowered:
            return list(cols)
    return []


def _empty_to_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_int(value: Any) -> int | None:
    text = _empty_to_none(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _parse_bool(value: Any) -> bool | None:
    text = _empty_to_none(value)
    if text is None:
        return None
    lowered = text.lower()
    if lowered in {"true", "1", "yes", "y"}:
        return True
    if lowered in {"false", "0", "no", "n"}:
        return False
    return None


def _parse_datetime(value: Any) -> datetime | None:
    text = _empty_to_none(value)
    if text is None:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _parse_time(value: Any) -> time | None:
    text = _empty_to_none(value)
    if text is None:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _map_status(value: Any) -> ScraperStatus:
    text = (_empty_to_none(value) or "active").lower()
    return ScraperStatus.inactive if text == "inactive" else ScraperStatus.active


def _map_feed_delivery(value: Any) -> FeedDelivery:
    text = (_empty_to_none(value) or "xml browser").lower().replace("-", " ")
    mapping = {
        "xml browser": FeedDelivery.xml_browser,
        "json browser": FeedDelivery.json_browser,
        "xml download": FeedDelivery.xml_download,
        "csv download": FeedDelivery.csv_download,
    }
    return mapping.get(text, FeedDelivery.xml_browser)


def _map_filter_flag(value: Any) -> FilterFlag:
    text = (_empty_to_none(value) or "none").lower()
    mapping = {
        "none": FilterFlag.none,
        "no": FilterFlag.none,
        "pre": FilterFlag.pre,
        "pre filter": FilterFlag.pre,
        "post": FilterFlag.post,
        "post filter": FilterFlag.post,
        "both": FilterFlag.both,
        "yes": FilterFlag.both,
    }
    return mapping.get(text, FilterFlag.none)


def _map_proxy_usage(value: Any) -> ProxyUsage:
    text = (_empty_to_none(value) or "none").lower()
    mapping = {
        "none": ProxyUsage.none,
        "no": ProxyUsage.none,
        "low": ProxyUsage.low,
        "high": ProxyUsage.high,
    }
    return mapping.get(text, ProxyUsage.none)


def _default_scraped_columns(spider_name: str) -> list[str]:
    return scraped_columns_for_spider(spider_name)


def _pre_filter_from_meta(meta: dict[str, Any]) -> str | None:
    parts: list[str] = []
    scrape_type = _empty_to_none(meta.get("scrapeType"))
    if scrape_type:
        parts.append(f"scrapeType={scrape_type}")
    passes = _empty_to_none(meta.get("proFilterPasses"))
    if passes and passes != "0":
        parts.append(f"proFilterPasses={passes}")
    return "; ".join(parts) if parts else None


def seed_scrapers(path: Path | None = None) -> tuple[int, int]:
    """Insert or update scrapers from JSON. Returns (created, updated)."""
    settings = get_settings()
    seed_path = path or settings.seed_path
    if not seed_path.is_file():
        raise FileNotFoundError(f"Seed file not found: {seed_path}")

    data = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected object keyed by spider name in {seed_path}")

    # Runtime stats / optional schedule: empty seed must not wipe them on update.
    preserve_if_none = frozenset(
        {
            "jobs_count",
            "scraped_count",
            "skipped_jobs",
            "qa_passed",
            "feed_url",
            "last_scraped",
            "schedule_day",
            "schedule_time",
        }
    )

    created = 0
    updated = 0

    with SessionLocal() as session:
        for spider_name, meta in data.items():
            if not isinstance(meta, dict):
                logger.warning("Skipping %s: expected object metadata", spider_name)
                continue

            existing = session.scalar(select(Scraper).where(Scraper.spider_name == spider_name))
            values = {
                "status": _map_status(meta.get("status")),
                "pre_filter": _pre_filter_from_meta(meta),
                "post_filter": None,
                "feed_delivery": _map_feed_delivery(meta.get("feedDelivery")),
                "filter_flag": _map_filter_flag(meta.get("filterFlag")),
                "proxy_usage": _map_proxy_usage(meta.get("proxyUsage")),
                "domain_name": _empty_to_none(meta.get("domainName")),
                "client_name": _empty_to_none(meta.get("clientName")),
                "start_url": _empty_to_none(meta.get("startUrl")),
                "scraped_columns": _default_scraped_columns(spider_name),
                "last_scraped": _parse_datetime(meta.get("lastScraped")),
                "jobs_count": _parse_int(meta.get("jobsCount")),
                "scraped_count": _parse_int(meta.get("scrapedCount")),
                "skipped_jobs": _parse_int(meta.get("skippedJobs")),
                "qa_passed": _parse_bool(meta.get("qaPassed")),
                "feed_url": _empty_to_none(meta.get("feedUrl")),
                "schedule_day": _empty_to_none(meta.get("scheduleDay")),
                "schedule_time": _parse_time(meta.get("scheduleTime")),
            }

            if existing:
                for key, value in values.items():
                    if key in preserve_if_none and value is None:
                        continue
                    setattr(existing, key, value)
                updated += 1
            else:
                session.add(
                    Scraper(
                        scrape_id=uuid.uuid4(),
                        spider_name=spider_name,
                        lifetime_scraped_count=0,
                        run_count=0,
                        needs_rerun=False,
                        **values,
                    )
                )
                created += 1

        session.commit()

    logger.info("Seed complete from %s: created=%s updated=%s", seed_path, created, updated)
    return created, updated


def sync_scraped_columns() -> tuple[int, int]:
    """
    Ensure every spider in scraped_columns.json has matching scraped_columns in DB.

    Creates a minimal Active row when the spider is missing from scrape_details.json.
    Returns (created, updated).
    """
    mapping = _load_scraped_columns_map()
    created = 0
    updated = 0
    with SessionLocal() as session:
        for spider_name, columns in mapping.items():
            existing = session.scalar(select(Scraper).where(Scraper.spider_name == spider_name))
            if existing is None:
                session.add(
                    Scraper(
                        scrape_id=uuid.uuid4(),
                        spider_name=spider_name,
                        status=ScraperStatus.active,
                        scraped_columns=list(columns),
                        lifetime_scraped_count=0,
                        run_count=0,
                        needs_rerun=False,
                    )
                )
                created += 1
            elif existing.scraped_columns != columns:
                existing.scraped_columns = list(columns)
                updated += 1
        session.commit()
    logger.info("scraped_columns sync: created=%s updated=%s", created, updated)
    return created, updated


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        created, updated = seed_scrapers()
        cols_created, cols_updated = sync_scraped_columns()
    except Exception as exc:  # noqa: BLE001
        logger.error("Seed failed: %s", exc)
        sys.exit(1)
    print(
        f"Seeded scrapers from {get_settings().seed_path} "
        f"(created={created}, updated={updated})"
    )
    print(
        f"Synced scraped_columns from spider item dicts "
        f"(created={cols_created}, updated={cols_updated})"
    )


if __name__ == "__main__":
    main()
