---
runbook_id: postgres-connection-pool-exhaustion
title: PostgreSQL connection pool exhaustion
tags: [postgres, database, connection-pool, hikari, pgbouncer, 5xx, latency]
actions: [restart_service]
---

# PostgreSQL connection pool exhaustion

## Symptoms

- Application logs show `Connection is not available, request timed out` (HikariCP) or `QueuePool limit ... overflow reached` (SQLAlchemy).
- PostgreSQL rejects new sessions with `remaining connection slots are reserved for non-replication superuser connections`.
- 5xx rate and p99 latency rise together. Request threads are blocked, not busy on CPU.
- Pool metrics show active connections pinned at the pool maximum with a growing wait queue.

## Likely causes

- Traffic increase (campaign, retry storm, bot traffic) beyond what the fixed pool can serve.
- Slow queries or lock contention holding connections longer than usual.
- Connection leaks: code paths that do not return connections, or sessions left `idle in transaction`.
- Pool sized per pod without accounting for replica count, so total connections exceed `max_connections`.

## Diagnostic steps

1. Confirm pool saturation on the application side: active == max and waiting > 0.
2. Check traffic: compare requests per second to the same time last week.
3. On the database, count sessions by state and application.
4. Look for long running queries and sessions idle in transaction.
5. Check whether a deployment changed pool size, query patterns, or transaction scope.

## Commands

```sql
SELECT application_name, state, count(*) FROM pg_stat_activity GROUP BY 1, 2 ORDER BY 3 DESC;
SELECT pid, now() - query_start AS duration, state, left(query, 80)
  FROM pg_stat_activity WHERE state <> 'idle' ORDER BY duration DESC LIMIT 20;
SHOW max_connections;
```

```bash
kubectl -n <namespace> top pods -l app=<service>
kubectl -n <namespace> logs deploy/<service> --since=15m | grep -i "connection is not available"
```

## Remediation

- If traffic driven: rate limit or shed non-critical traffic, then raise the pool size only if `pool_size * replicas` stays under `max_connections` minus headroom.
- Put PgBouncer (transaction pooling) in front of PostgreSQL to multiplex connections.
- Terminate sessions stuck `idle in transaction` with `pg_terminate_backend(pid)`.
- If connections leaked, a rolling restart of the service releases them. This is a production state change and needs approval.
- Fix the slow queries that hold connections (add indexes, shorten transactions).

## Rollback

- Revert pool size changes through the service config and redeploy.
- If PgBouncer was introduced during the incident, point the service back at PostgreSQL directly.

## Risk notes

- Raising pool size without checking `max_connections` moves the failure to the database and can starve replication and admin sessions.
- Restarting all pods at once drops in-flight requests. Use a rolling restart.
- Terminating backends rolls back their open transactions.

## Escalation

- Page the owning service team and the database on-call if the database itself is at `max_connections`.
- Escalate to incident commander if checkout or payment success rate drops below 95% for more than 10 minutes.
