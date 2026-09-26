---
service: checkout-api
team: checkout
namespace: commerce
tags: [checkout, revenue, postgres, redis]
---

# checkout-api

Handles cart checkout, price confirmation and order submission. Tier 0 service: failures directly block revenue.

## Dependencies

- postgres-checkout (primary database, HikariCP pool of 100 connections shared across 6 replicas)
- payments-service, orders-service (synchronous HTTP)
- redis-cache (cart and price cache)

## SLOs

- Availability 99.95% over 30 days
- p99 latency under 800ms for POST /api/v1/checkout

## Known failure modes

- Database pool saturation during marketing campaigns. Campaign traffic is typically 2 to 3x baseline.
- Slow cart queries on very large carts.
- Downstream payment timeouts.

## Operational notes

- Deploys go through canary (10% for 15 minutes).
- The pool size is set per pod via `DB_POOL_SIZE`. Total connections are `DB_POOL_SIZE * replicas` and must stay under the database `max_connections` of 400.
