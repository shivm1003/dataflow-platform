"""Dashboard auth helpers: passwords, sessions, client scoping, login rate limit."""

from __future__ import annotations

import time
from collections.abc import Generator
from threading import Lock
from uuid import UUID

import bcrypt
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from dataflow_platform.config import get_settings
from dataflow_platform.db import SessionLocal
from dataflow_platform.models import User, UserRole

SESSION_USER_ID = "user_id"

LOGIN_ERROR = "Invalid username or password."

# ponytail: in-memory rate limit — fine for single dataflow-api process; use Redis if multi-worker.
_fail_lock = Lock()
_fail_log: dict[str, list[float]] = {}


def normalize_client_name(value: str | None) -> str | None:
    """Canonical client identity: strip + lowercase; empty → None."""
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_user_by_id(session: Session, user_id: UUID) -> User | None:
    return session.scalar(select(User).where(User.id == user_id))


def get_user_by_username(session: Session, username: str) -> User | None:
    return session.scalar(select(User).where(User.username == username))


def login_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def login_rate_limited(ip: str) -> bool:
    settings = get_settings()
    window = settings.login_rate_limit_window_seconds
    max_attempts = settings.login_rate_limit_attempts
    now = time.monotonic()
    with _fail_lock:
        stamps = [t for t in _fail_log.get(ip, []) if now - t < window]
        _fail_log[ip] = stamps
        return len(stamps) >= max_attempts


def record_login_failure(ip: str) -> None:
    settings = get_settings()
    window = settings.login_rate_limit_window_seconds
    now = time.monotonic()
    with _fail_lock:
        stamps = [t for t in _fail_log.get(ip, []) if now - t < window]
        stamps.append(now)
        _fail_log[ip] = stamps


def clear_login_failures(ip: str) -> None:
    with _fail_lock:
        _fail_log.pop(ip, None)


def reset_login_rate_limit_for_tests() -> None:
    with _fail_lock:
        _fail_log.clear()


def set_session_user(request: Request, user: User) -> None:
    request.session.clear()
    request.session[SESSION_USER_ID] = str(user.id)


def clear_session(request: Request) -> None:
    request.session.clear()


def current_user(request: Request, session: Session) -> User | None:
    raw = request.session.get(SESSION_USER_ID)
    if not raw:
        return None
    try:
        user_id = UUID(str(raw))
    except (ValueError, TypeError):
        return None
    user = get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        return None
    return user


def effective_client_name(user: User, query_client: str | None) -> str | None:
    """Client role is locked to user.client_name; admin may use ?client= filter."""
    if user.role == UserRole.client:
        return normalize_client_name(user.client_name)
    return normalize_client_name(query_client)


def user_can_access_scraper(user: User, scraper_client_name: str | None) -> bool:
    if user.role == UserRole.admin:
        return True
    left = normalize_client_name(user.client_name)
    right = normalize_client_name(scraper_client_name)
    return bool(left) and left == right
