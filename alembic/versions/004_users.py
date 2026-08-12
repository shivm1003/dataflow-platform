"""Create users table for dashboard login

Revision ID: 004_users
Revises: 003_duplicate_valid
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004_users"
down_revision: str | None = "003_duplicate_valid"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    user_role = postgresql.ENUM("admin", "client", name="user_role", create_type=False)
    bind = op.get_bind()
    user_role.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("client_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_client_name", "users", ["client_name"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_client_name", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
    user_role = postgresql.ENUM("admin", "client", name="user_role", create_type=False)
    user_role.drop(op.get_bind(), checkfirst=True)
