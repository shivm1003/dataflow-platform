"""Database engine and session helpers."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from dataflow_platform.config import get_settings

_settings = get_settings()

sync_engine = create_engine(_settings.database_url_sync, pool_pre_ping=True)
SessionLocal = sessionmaker(sync_engine, expire_on_commit=False, class_=Session)


def get_sync_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
