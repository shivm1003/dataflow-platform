"""Add scraper_runs history and scrapers.display_name

Revision ID: 002_scraper_runs
Revises: 001_create_scrapers
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_scraper_runs"
down_revision: str | None = "001_create_scrapers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_status = postgresql.ENUM("succeeded", "failed", name="run_status", create_type=False)
    bind = op.get_bind()
    run_status.create(bind, checkfirst=True)

    op.add_column("scrapers", sa.Column("display_name", sa.String(length=255), nullable=True))

    op.create_table(
        "scraper_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("scrape_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("spider_name", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", run_status, nullable=False),
        sa.Column("scraped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_count", sa.Integer(), nullable=True),
        sa.Column("skipped_jobs", sa.Integer(), nullable=True),
        sa.Column("total_runtime_seconds", sa.Integer(), nullable=True),
        sa.Column("feed_url", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["scrape_id"], ["scrapers.scrape_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_scraper_runs_scrape_id", "scraper_runs", ["scrape_id"])
    op.create_index("ix_scraper_runs_spider_name", "scraper_runs", ["spider_name"])
    op.create_index("ix_scraper_runs_finished_at", "scraper_runs", ["finished_at"])
    op.create_index(
        "ix_scraper_runs_spider_finished",
        "scraper_runs",
        ["spider_name", "finished_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_scraper_runs_spider_finished", table_name="scraper_runs")
    op.drop_index("ix_scraper_runs_finished_at", table_name="scraper_runs")
    op.drop_index("ix_scraper_runs_spider_name", table_name="scraper_runs")
    op.drop_index("ix_scraper_runs_scrape_id", table_name="scraper_runs")
    op.drop_table("scraper_runs")
    op.drop_column("scrapers", "display_name")
    op.execute("DROP TYPE IF EXISTS run_status")
