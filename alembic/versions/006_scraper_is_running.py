"""Add scrapers.is_running for live crawl status

Revision ID: 006_scraper_is_running
Revises: 005_normalize_client_names
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006_scraper_is_running"
down_revision: str | None = "005_normalize_client_names"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scrapers",
        sa.Column("is_running", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("scrapers", "is_running")
