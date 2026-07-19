# Architecture Decision Record: Redis Streams for Work Dispatch

## Status

Accepted

## Context

We need a durable work queue between the API (and later the scheduler) and workers. The MVP runs a single sequential worker, but horizontal scale must not require redesign.

## Decision

Use Redis Streams with a consumer group for job dispatch.

- Stream key: configurable (default `tc:runs`)
- Consumer group: `tc-workers`
- Message payload: `run_id` (UUID string)
- Workers read with `XREADGROUP`, process one message at a time, then `XACK`
- Pending entries support reclaim for crashed workers later

Postgres remains the source of truth for run status. Redis carries dispatch signals only.

## Consequences

- Increasing worker count is a deployment/config change.
- At-least-once delivery requires idempotent status transitions in Postgres.
- Stream inspection gives queue visibility without coupling to Scrapy.
