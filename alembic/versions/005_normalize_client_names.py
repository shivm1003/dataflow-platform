"""Normalize client_name to lowercase on scrapers and users

Revision ID: 005_normalize_client_names
Revises: 004_users
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "005_normalize_client_names"
down_revision: str | None = "004_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE scrapers SET client_name = lower(trim(client_name)) "
        "WHERE client_name IS NOT NULL"
    )
    op.execute(
        "UPDATE users SET client_name = lower(trim(client_name)) "
        "WHERE client_name IS NOT NULL"
    )


def downgrade() -> None:
    # Irreversible data normalization
    pass
