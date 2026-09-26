---
service: search-api
team: search
namespace: discovery
tags: [search, elasticsearch, redis, latency]
---

# search-api

Product search and listing endpoints backed by an Elasticsearch cluster and a Redis cache.

## Dependencies

- elasticsearch-products
- redis-cache
- postgres-catalog for listing filters

## SLOs

- p99 latency under 300ms
- Availability 99.9%

## Known failure modes

- Latency from CPU throttling during traffic bursts.
- Cache evictions when Redis fills up.
- HPA limits too low for sale events.

## Operational notes

- CPU request 1 core. HPA targets 60% CPU.
