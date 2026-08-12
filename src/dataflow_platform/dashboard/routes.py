"""HTML dashboard routes for scraper registry visibility."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from dataflow_platform.auth import (
    LOGIN_ERROR,
    clear_login_failures,
    clear_session,
    current_user,
    effective_client_name,
    get_db,
    get_user_by_username,
    login_client_ip,
    login_rate_limited,
    record_login_failure,
    set_session_user,
    user_can_access_scraper,
    verify_password,
)
from dataflow_platform.models import User, UserRole
from dataflow_platform.services import (
    ScraperServiceError,
    activity_feed,
    coverage_quality,
    dashboard_metrics,
    distinct_clients,
    get_scraper_by_name,
    job_center,
    list_recent_runs,
    list_scrapers,
    next_schedule_label,
    overview_series,
    schedule_summary,
    sort_sources_rows,
    sources_rows,
    spider_detail_qa,
    spider_period_stats,
    spider_previous_run_delta,
    spider_volume_series,
    top_jobs,
)
from dataflow_platform.status_mapping import derive_display_name, source_directory_status

router = APIRouter(tags=["dashboard"])

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _safe_next(raw: str | None) -> str:
    path = (raw or "").strip() or "/"
    if not path.startswith("/") or path.startswith("//"):
        return "/"
    return path


def _login_redirect(request: Request) -> RedirectResponse:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return RedirectResponse(url=f"/login?next={quote(next_path, safe='/?=&')}", status_code=303)


def _render(
    request: Request,
    name: str,
    *,
    user: User | None = None,
    bare: bool = False,
    status_code: int = 200,
    **context: object,
) -> HTMLResponse:
    path = request.url.path
    if path.startswith("/dashboard/scrapers") or path.startswith("/sources"):
        nav = "scrapers"
    else:
        nav = "dashboard"
    context.setdefault("nav", nav)
    context.setdefault("bare", bare)
    context.setdefault("current_user", user)
    return templates.TemplateResponse(
        request=request,
        name=name,
        context=context,
        status_code=status_code,
    )


def _date_label() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.strftime('%a')}, {now.strftime('%B')} {now.day}"


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _fmt_ago(value: datetime | None) -> str:
    if value is None:
        return "never"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    seconds = int((datetime.now(timezone.utc) - value.astimezone(timezone.utc)).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _fmt_runtime(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds}s"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {rem}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _fmt_int(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}"


def _enum_value(value: object) -> str:
    return getattr(value, "value", str(value) if value is not None else "")


def _build_insights(session: Session, client_name: str | None) -> list[dict[str, str]]:
    metrics = dashboard_metrics(session, client_name=client_name)
    schedule = schedule_summary(session, client_name=client_name)
    jc = job_center(session, client_name=client_name)
    tips: list[dict[str, str]] = []
    if metrics.get("success_rate") is not None:
        tips.append(
            {
                "cls": "up" if metrics["success_rate"] >= 90 else "warn",
                "icon": "↑" if metrics["success_rate"] >= 90 else "!",
                "text": f"7-day success rate is {metrics['success_rate']}%.",
            }
        )
    if metrics.get("urls_delta_pct") is not None:
        delta = metrics["urls_delta_pct"]
        tips.append(
            {
                "cls": "up" if delta >= 0 else "err",
                "icon": "↑" if delta >= 0 else "↓",
                "text": f"Items scraped today changed by {delta}% vs yesterday.",
            }
        )
    attention = jc["counts"].get("attention", 0)
    if attention:
        tips.append(
            {
                "cls": "err",
                "icon": "!",
                "text": f"{attention} scraper(s) need attention.",
            }
        )
    tips.append(
        {
            "cls": "warn",
            "icon": "⏱",
            "text": f"{schedule['upcoming']} job(s) queued / never run.",
        }
    )
    return tips[:4]


def _picker_clients(session: Session, user: User) -> list[str]:
    if user.role == UserRole.client and user.client_name:
        return [user.client_name]
    return distinct_clients(session)


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    next: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> Response:
    user = current_user(request, session)
    if user is not None:
        return RedirectResponse(url=_safe_next(next), status_code=303)
    return _render(
        request,
        "login.html",
        bare=True,
        error=None,
        next=_safe_next(next),
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str | None = Form(default=None),
    session: Session = Depends(get_db),
) -> Response:
    ip = login_client_ip(request)
    next_path = _safe_next(next)
    if login_rate_limited(ip):
        return _render(
            request,
            "login.html",
            bare=True,
            error="Too many failed attempts. Try again later.",
            next=next_path,
            status_code=429,
        )

    user = get_user_by_username(session, username.strip())
    if (
        user is None
        or not user.is_active
        or not verify_password(password, user.password_hash)
    ):
        record_login_failure(ip)
        return _render(
            request,
            "login.html",
            bare=True,
            error=LOGIN_ERROR,
            next=next_path,
            status_code=401,
        )

    clear_login_failures(ip)
    set_session_user(request, user)
    return RedirectResponse(url=next_path, status_code=303)


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    clear_session(request)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
def dashboard_home(
    request: Request,
    client: str | None = Query(default=None),
    year: int | None = None,
    month: int | None = None,
    session: Session = Depends(get_db),
) -> Response:
    user = current_user(request, session)
    if user is None:
        return _login_redirect(request)

    client_filter = effective_client_name(user, client)
    now = datetime.now(timezone.utc)
    y = year or now.year
    m = month or now.month
    metrics = dashboard_metrics(session, client_name=client_filter)
    series = overview_series(session, year=y, month=m, client_name=client_filter)
    jc = job_center(session, client_name=client_filter, limit=5)
    activity = activity_feed(session, client_name=client_filter, limit=5)
    tops = top_jobs(session, client_name=client_filter, limit=5)
    schedule = schedule_summary(session, client_name=client_filter)
    quality = coverage_quality(session, client_name=client_filter)
    clients = _picker_clients(session, user)
    payload = {
        "series": series,
        "job_center": jc,
        "activity": activity,
        "top_jobs": tops,
        "quality": quality,
    }
    return _render(
        request,
        "index.html",
        user=user,
        date_label=_date_label(),
        clients=clients,
        client_filter=client_filter or "",
        lock_client_picker=user.role == UserRole.client,
        metrics=metrics,
        series=series,
        job_center=jc,
        schedule=schedule,
        quality=quality,
        insights=_build_insights(session, client_filter),
        dashboard_json=json.dumps(payload),
    )


@router.get("/sources", response_class=HTMLResponse)
def dashboard_sources(
    request: Request,
    client: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30),
    sort: str = Query(default="client"),
    order: str = Query(default="asc"),
    session: Session = Depends(get_db),
) -> Response:
    user = current_user(request, session)
    if user is None:
        return _login_redirect(request)

    client_filter = effective_client_name(user, client)
    query = (q or "").strip()
    if per_page not in {20, 30, 50}:
        per_page = 30
    sort_key = sort if sort in {
        "client", "scraper", "source", "feed", "type", "jobs", "extracted",
        "health", "status", "schedule", "created_at", "updated",
    } else "client"
    order_key = "desc" if (order or "").lower() == "desc" else "asc"
    rows = sort_sources_rows(
        sources_rows(session, client_name=client_filter, q=query or None),
        sort=sort_key,
        order=order_key,
    )
    metrics = dashboard_metrics(session, client_name=client_filter)
    scrapers = list_scrapers(session, client_name=client_filter, q=query or None)
    lifetime = sum(s.lifetime_scraped_count or 0 for s in scrapers)
    total_jobs = sum(r["jobs"] for r in rows)
    total_sources = len(rows)
    total_pages = max(1, (total_sources + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    page_rows = rows[start : start + per_page]
    return _render(
        request,
        "sources.html",
        user=user,
        date_label=_date_label(),
        clients=_picker_clients(session, user),
        client_filter=client_filter or "",
        lock_client_picker=user.role == UserRole.client,
        q=query,
        sources=page_rows,
        sources_total=total_sources,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        sort=sort_key,
        order=order_key,
        metrics=metrics,
        lifetime_fmt=f"{lifetime:,}",
        total_jobs=total_jobs,
    )


@router.get("/dashboard/scrapers/{spider_name}", response_class=HTMLResponse)
def dashboard_scraper_detail(
    request: Request,
    spider_name: str,
    session: Session = Depends(get_db),
) -> Response:
    user = current_user(request, session)
    if user is None:
        return _login_redirect(request)

    try:
        scraper = get_scraper_by_name(session, spider_name)
    except ScraperServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if not user_can_access_scraper(user, scraper.client_name):
        raise HTTPException(status_code=404, detail="Scraper not found")

    columns = list(scraper.scraped_columns or [])
    healthy = not scraper.needs_rerun and scraper.qa_passed is not False
    jobs = int(scraper.jobs_count or 0)
    scraped = int(scraper.scraped_count or 0)
    jobs_pct = min(100.0, round(100 * scraped / jobs, 1)) if jobs > 0 else None
    delta = spider_previous_run_delta(session, spider_name=spider_name)
    schedule_parts = []
    if scraper.schedule_day:
        schedule_parts.append(_compact_schedule_days(scraper.schedule_day))
    if scraper.schedule_time:
        schedule_parts.append(scraper.schedule_time.strftime("%H:%M"))
    schedule_label = " · ".join(schedule_parts) if schedule_parts else "—"
    next_run = next_schedule_label(scraper.schedule_day, scraper.schedule_time)
    auto_run = bool(scraper.schedule_time or (scraper.schedule_day or "").strip())

    view = {
        "scrape_id": str(scraper.scrape_id),
        "spider_name": scraper.spider_name,
        "display_label": derive_display_name(scraper.spider_name, scraper.display_name),
        "feed_delivery": _enum_value(scraper.feed_delivery).replace("_", " ").title(),
        "filter_flag": _enum_value(scraper.filter_flag).replace("_", " ").title(),
        "proxy_usage": _enum_value(scraper.proxy_usage).replace("_", " ").title(),
        "status": _enum_value(scraper.status),
        "source_status": source_directory_status(scraper),
        "domain_name": scraper.domain_name or "—",
        "client_name": scraper.client_name or "—",
        "start_url": scraper.start_url or "",
        "scraped_columns": columns,
        "schedule_day": scraper.schedule_day or "—",
        "schedule_time": (
            scraper.schedule_time.strftime("%H:%M") if scraper.schedule_time else "—"
        ),
        "schedule_label": schedule_label,
        "next_run": next_run,
        "auto_run": auto_run,
        "last_scraped": _fmt_dt(scraper.last_scraped),
        "last_scraped_ago": _fmt_ago(scraper.last_scraped),
        "jobs_count": jobs,
        "scraped_count": scraped,
        "jobs_count_fmt": _fmt_int(scraper.jobs_count),
        "scraped_count_fmt": _fmt_int(scraper.scraped_count),
        "skipped_jobs": int(scraper.skipped_jobs or 0),
        "skipped_jobs_fmt": _fmt_int(scraper.skipped_jobs),
        "duplicate_count": int(scraper.duplicate_count or 0),
        "valid_count": int(scraper.valid_count or 0),
        "qa_passed": scraper.qa_passed,
        "feed_url": scraper.feed_url or "",
        "total_runtime": _fmt_runtime(scraper.total_runtime_seconds),
        "lifetime_scraped_fmt": _fmt_int(scraper.lifetime_scraped_count),
        "run_count_fmt": _fmt_int(scraper.run_count),
        "needs_rerun": scraper.needs_rerun,
        "qa_notes": scraper.qa_notes or "",
        "healthy": healthy,
        "jobs_pct": jobs_pct,
        "jobs_pct_label": (
            str(int(jobs_pct)) if jobs_pct is not None and abs(jobs_pct - round(jobs_pct)) < 0.05
            else (f"{jobs_pct:.1f}" if jobs_pct is not None else None)
        ),
        "scraped_delta_pct": delta["scraped_delta_pct"],
        "prev_scraped": delta["prev_scraped"],
    }

    recent = list_recent_runs(session, spider_name=spider_name, limit=20)
    runs = []
    for r in recent:
        qa_ok = r.success and not (r.error_message)
        runs.append(
            {
                "finished_at": _fmt_dt(r.finished_at),
                "status": "Succeeded" if r.success else "Failed",
                "success": r.success,
                "scraped_count": r.scraped_count,
                "jobs_count": r.jobs_count,
                "skipped_jobs": r.skipped_jobs if r.skipped_jobs is not None else 0,
                "qa": "Passed" if qa_ok else "Failed",
                "qa_ok": qa_ok,
                "runtime": _fmt_runtime(r.total_runtime_seconds),
            }
        )
    latest = runs[0] if runs else None
    qa = spider_detail_qa(scraper)
    volume_series = spider_volume_series(session, spider_name=spider_name)
    volume = spider_period_stats(session, spider_name=spider_name)
    detail_json = json.dumps({"volume": volume_series})
    return _render(
        request,
        "detail.html",
        user=user,
        scraper=view,
        runs=runs[:5],
        latest=latest,
        qa=qa,
        volume=volume,
        volume_series=volume_series,
        detail_json=detail_json,
    )


def _compact_schedule_days(schedule_day: str) -> str:
    """Mon,Tue,Wed,Thu,Fri → Mon–Fri when full weekday set; else leave as-is."""
    raw = schedule_day.strip()
    parts = [p.strip() for p in raw.replace(" ", "").split(",") if p.strip()]
    if len(parts) == 5 and parts[0][:3].lower() == "mon" and parts[-1][:3].lower() == "fri":
        return "Mon–Fri"
    if len(parts) == 4 and parts[0][:3].lower() == "mon" and parts[-1][:3].lower() == "thu":
        return "Mon–Thu"
    return raw
