# Architecture Decision Record: Orchestration vs Execution Separation

## Status

Accepted

## Context

TeamCrawlers currently runs Scrapy spiders via sequential cron/bash scripts. We are introducing a control plane that schedules, queues, monitors, and audits runs. Scraping business logic must remain outside that control plane.

## Decision

The platform owns orchestration only: scraper registry, run lifecycle, queue dispatch, retries, and history.

Execution engines (starting with Scrapy) are plugins. Plugins receive a task payload and return a result (`ok`, `exit_code`, `log_ref`). The core never imports spider modules or embeds site-specific logic.

## Consequences

- New engines (Playwright, API ingest, etc.) can be added without changing the worker framework.
- Existing Scrapy project stays intact under `crawlers/`.
- Workers remain generic: resolve plugin by `engine` field, call `execute()`, update run status.
