# Architecture Decision Record: Lightweight Scheduler for MVP

## Status

Accepted

## Context

The product vision mentions Dagster as a scheduler. Dagster is excellent for data pipelines but heavy if its only role is “enqueue due work to Redis.”

## Decision

MVP scheduling uses:

- A `schedule` table in Postgres (cron expression per scraper)
- A small ticker process that polls due schedules and enqueues runs through the same path as manual API triggers

Dagster (or another scheduler) may be added later behind the same enqueue interface.

## Consequences

- Cron replacement ships without introducing a second orchestration framework.
- Manual and scheduled runs share identical worker/plugin behavior.
- Future Dagster integration is additive, not a rewrite.
