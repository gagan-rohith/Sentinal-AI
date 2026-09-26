---
runbook_id: latency-spike
title: API latency spike
tags: [latency, p99, slow-query, dependency, saturation, index]
actions: []
---

# API latency spike

## Symptoms

- p99 or p95 latency above the SLO threshold while error rate may still be low.
- Request queues and thread pools filling up.
- Clients start timing out, which later shows as 504s.

## Likely causes

- Slow database queries: missing index, query plan regression, lock contention.
- Slow downstream dependency without a tight timeout.
- CPU saturation or CPU throttling.
- Garbage collection pauses.
- Autoscaler unable to add capacity.

## Diagnostic steps

1. Break latency down by endpoint. One endpoint points at a query or dependency, all endpoints point at saturation.
2. Check database CPU and the slow query log for sequential scans.
3. Check dependency latency from the client side.
4. Check CPU utilization and CFS throttling for the pods.
5. Check HPA status and replica count against traffic.

## Commands

```sql
EXPLAIN (ANALYZE, BUFFERS) <slow query>;
SELECT query, mean_exec_time, calls FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;
```

```bash
kubectl -n <namespace> get hpa <service>
kubectl -n <namespace> top pods -l app=<service>
```

## Remediation

- Missing index: create it with `CREATE INDEX CONCURRENTLY`, or disable the feature that issues the query.
- Slow dependency: lower the timeout, enable fallback or cached responses.
- Saturation: add replicas or raise CPU limits.

## Rollback

- Disable the feature flag or roll back the release that introduced the slow path.
- Drop a new index if it causes write amplification problems.

## Risk notes

- `CREATE INDEX` without `CONCURRENTLY` locks writes on the table.
- Raising timeouts usually makes cascading latency worse.

## Escalation

- Page the database on-call if database CPU stays above 90% for 10 minutes.
