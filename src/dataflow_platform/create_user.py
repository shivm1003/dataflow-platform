"""CLI: create a dashboard user (admin or client)."""

from __future__ import annotations

import argparse
import sys

from dataflow_platform.auth import get_user_by_username, hash_password, normalize_client_name
from dataflow_platform.db import SessionLocal
from dataflow_platform.models import User, UserRole


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Create a dataflow dashboard user")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", choices=["admin", "client"], required=True)
    parser.add_argument(
        "--client",
        default=None,
        help="Required for client role. Any string; stored lowercase (e.g. Medblast → medblast)",
    )
    args = parser.parse_args(argv)

    role = UserRole(args.role)
    client_name = normalize_client_name(args.client)
    if role == UserRole.client:
        if not client_name:
            print("--client is required for client role", file=sys.stderr)
            raise SystemExit(2)
    elif client_name is not None:
        print("admin role must not set --client", file=sys.stderr)
        raise SystemExit(2)

    session = SessionLocal()
    try:
        if get_user_by_username(session, args.username):
            print(f"User already exists: {args.username}", file=sys.stderr)
            raise SystemExit(1)
        user = User(
            username=args.username,
            password_hash=hash_password(args.password),
            role=role,
            client_name=client_name,
            is_active=True,
        )
        session.add(user)
        session.commit()
        print(f"Created user {args.username} role={role.value} client={client_name or '—'}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
