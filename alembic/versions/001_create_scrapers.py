"""Create scrapers table

Revision ID: 001_create_scrapers
Revises:
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_create_scrapers"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    scraper_status = postgresql.ENUM("active", "inactive", name="scraper_status", create_type=False)
    feed_delivery = postgresql.ENUM(
        "xml_browser",
        "json_browser",
        "xml_download",
        "csv_download",
        name="feed_delivery",
        create_type=False,
    )
    filter_flag = postgresql.ENUM(
        "none",
        "pre",
        "post",
        "both",
        name="filter_flag",
        create_type=False,
    )
    proxy_usage = postgresql.ENUM(
        "none",
        "low",
        "high",
        name="proxy_usage",
        create_type=False,
    )

    bind = op.get_bind()
    scraper_status.create(bind, checkfirst=True)
    feed_delivery.create(bind, checkfirst=True)
    filter_flag.create(bind, checkfirst=True)
    proxy_usage.create(bind, checkfirst=True)

    op.create_table(
        "scrapers",
        sa.Column("scrape_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("spider_name", sa.String(length=255), nullable=False),
        sa.Column("status", scraper_status, nullable=False, server_default="active"),
        sa.Column("pre_filter", sa.Text(), nullable=True),
        sa.Column("post_filter", sa.Text(), nullable=True),
        sa.Column("feed_delivery", feed_delivery, nullable=False, server_default="xml_browser"),
        sa.Column("filter_flag", filter_flag, nullable=False, server_default="none"),
        sa.Column("proxy_usage", proxy_usage, nullable=False, server_default="none"),
        sa.Column("domain_name", sa.String(length=255), nullable=True),
        sa.Column("client_name", sa.String(length=255), nullable=True),
        sa.Column("start_url", sa.Text(), nullable=True),
        sa.Column(
            "scraped_columns",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("schedule_day", sa.String(length=128), nullable=True),
        sa.Column("schedule_time", sa.Time(), nullable=True),
        sa.Column("last_scraped", sa.DateTime(timezone=True), nullable=True),
        sa.Column("jobs_count", sa.Integer(), nullable=True),
        sa.Column("scraped_count", sa.Integer(), nullable=True),
        sa.Column("skipped_jobs", sa.Integer(), nullable=True),
        sa.Column("qa_passed", sa.Boolean(), nullable=True),
        sa.Column("feed_url", sa.Text(), nullable=True),
        sa.Column("total_runtime_seconds", sa.Integer(), nullable=True),
        sa.Column("lifetime_scraped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("needs_rerun", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("qa_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_date",
            sa.Date(),
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("spider_name"),
    )
    op.create_index("ix_scrapers_spider_name", "scrapers", ["spider_name"])
    op.create_index("ix_scrapers_client_name", "scrapers", ["client_name"])


def downgrade() -> None:
    op.drop_index("ix_scrapers_client_name", table_name="scrapers")
    op.drop_index("ix_scrapers_spider_name", table_name="scrapers")
    op.drop_table("scrapers")
    op.execute("DROP TYPE IF EXISTS proxy_usage")
    op.execute("DROP TYPE IF EXISTS filter_flag")
    op.execute("DROP TYPE IF EXISTS feed_delivery")
    op.execute("DROP TYPE IF EXISTS scraper_status")
