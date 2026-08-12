"""Auth helpers: password, client scoping, login rate limit, client normalize."""

from __future__ import annotations

from types import SimpleNamespace

from dataflow_platform.auth import (
    effective_client_name,
    hash_password,
    login_rate_limited,
    normalize_client_name,
    record_login_failure,
    reset_login_rate_limit_for_tests,
    user_can_access_scraper,
    verify_password,
)
from dataflow_platform.config import get_settings
from dataflow_platform.models import UserRole


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("secret-pass")
    assert hashed != "secret-pass"
    assert verify_password("secret-pass", hashed)
    assert not verify_password("wrong", hashed)


def test_normalize_client_name() -> None:
    assert normalize_client_name("Medblast") == "medblast"
    assert normalize_client_name("  HIREDIVERSE ") == "hirediverse"
    assert normalize_client_name("") is None
    assert normalize_client_name("   ") is None
    assert normalize_client_name(None) is None


def test_effective_client_name_admin_and_client() -> None:
    admin = SimpleNamespace(role=UserRole.admin, client_name=None)
    client = SimpleNamespace(role=UserRole.client, client_name="Medblast")
    assert effective_client_name(admin, None) is None  # type: ignore[arg-type]
    assert effective_client_name(admin, "Hirediverse") == "hirediverse"  # type: ignore[arg-type]
    assert effective_client_name(client, "Hirediverse") == "medblast"  # type: ignore[arg-type]
    assert effective_client_name(client, None) == "medblast"  # type: ignore[arg-type]


def test_user_can_access_scraper_case_insensitive() -> None:
    admin = SimpleNamespace(role=UserRole.admin, client_name=None)
    client = SimpleNamespace(role=UserRole.client, client_name="medblast")
    assert user_can_access_scraper(admin, "Medblast")  # type: ignore[arg-type]
    assert user_can_access_scraper(client, "Medblast")  # type: ignore[arg-type]
    assert user_can_access_scraper(client, "MEDBLAST")  # type: ignore[arg-type]
    assert not user_can_access_scraper(client, "hirediverse")  # type: ignore[arg-type]


def test_login_rate_limit() -> None:
    reset_login_rate_limit_for_tests()
    get_settings.cache_clear()
    ip = "203.0.113.50"
    settings = get_settings()
    for _ in range(settings.login_rate_limit_attempts):
        assert not login_rate_limited(ip)
        record_login_failure(ip)
    assert login_rate_limited(ip)
    reset_login_rate_limit_for_tests()
    assert not login_rate_limited(ip)
