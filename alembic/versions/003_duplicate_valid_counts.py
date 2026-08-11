"""Add duplicate_count and valid_count to scrapers and scraper_runs

Revision ID: 003_duplicate_valid
Revises: 002_scraper_runs
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003_duplicate_valid"
down_revision: str | None = "002_scraper_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("scrapers", sa.Column("duplicate_count", sa.Integer(), nullable=True))
    op.add_column("scrapers", sa.Column("valid_count", sa.Integer(), nullable=True))
    op.add_column("scraper_runs", sa.Column("duplicate_count", sa.Integer(), nullable=True))
    op.add_column("scraper_runs", sa.Column("valid_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("scraper_runs", "valid_count")
    op.drop_column("scraper_runs", "duplicate_count")
    op.drop_column("scrapers", "valid_count")
    op.drop_column("scrapers", "duplicate_count")
