"""Periodic QA sweep for active scrapers."""

from __future__ import annotations

import logging
import sys

from sqlalchemy import select

from dataflow_platform.db import SessionLocal
from dataflow_platform.models import Scraper, ScraperStatus
from dataflow_platform.qa.rules import apply_qa_to_scraper

logger = logging.getLogger(__name__)


def sweep_scrapers() -> list[str]:
    """Re-evaluate all active scrapers; return spider names that need re-run."""
    needs: list[str] = []
    with SessionLocal() as session:
        scrapers = list(
            session.scalars(
                select(Scraper).where(Scraper.status == ScraperStatus.active)
            ).all()
        )
        for scraper in scrapers:
            result = apply_qa_to_scraper(scraper)
            if result.needs_rerun:
                needs.append(scraper.spider_name)
                logger.info(
                    "needs_rerun spider=%s rules=%s",
                    scraper.spider_name,
                    result.failed_rules,
                )
        session.commit()
    return needs


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        needs = sweep_scrapers()
    except Exception as exc:  # noqa: BLE001
        logger.error("QA sweep failed: %s", exc)
        sys.exit(1)
    if not needs:
        print("No scrapers need re-run.")
        return
    print("Scrapers needing re-run:")
    for name in needs:
        print(name)


if __name__ == "__main__":
    main()
