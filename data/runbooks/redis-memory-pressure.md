---
runbook_id: redis-memory-pressure
title: Redis memory pressure and evictions
tags: [redis, cache, eviction, maxmemory, ttl, memory]
actions: []
---

# Redis memory pressure and evictions

## Symptoms

- Redis `used_memory` at `maxmemory`.
- `evicted_keys` rising fast, or writes failing with `OOM command not allowed`.
- Cache hit ratio falls and database load and latency rise.

## Likely causes

- New key pattern written without TTL.
- Value sizes grew after a release.
- maxmemory set too low for the working set.
- Eviction policy `noeviction` turning memory pressure into write errors.

## Diagnostic steps

1. Check memory, eviction rate and hit ratio from `INFO`.
2. Sample keys to find the prefix taking the most memory and whether it has a TTL.
3. Line up the growth with deployments.

## Commands

```bash
redis-cli INFO memory | grep -E "used_memory_human|maxmemory_human|maxmemory_policy"
redis-cli INFO stats | grep -E "evicted_keys|keyspace_hits|keyspace_misses"
redis-cli --bigkeys
redis-cli --scan --pattern 'session:*' | head
```

## Remediation

- Set a TTL on the offending key pattern in code and expire existing keys in batches.
- Move unrelated workloads (sessions vs cache) to separate instances.
- Raise maxmemory only if the instance has room.

## Rollback

- Roll back the release that introduced the key pattern if the fix cannot ship quickly.

## Risk notes

- `KEYS *` blocks Redis. Use `SCAN`.
- Flushing the cache causes a thundering herd on the database.

## Escalation

- Page the owning team and the database on-call if database CPU rises above 80% from cache misses.
