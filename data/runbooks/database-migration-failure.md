---
runbook_id: database-migration-failure
title: Database migration failure
tags: [database, migration, schema, lock-timeout, deployment, postgres]
actions: [rollback_deployment]
---

# Database migration failure

## Symptoms

- SQL errors such as `column ... does not exist` or `relation ... does not exist`.
- Migration job failed or timed out while the new application version is running.
- Errors limited to code paths touching the changed tables.

## Likely causes

- Migration hit a lock timeout on a busy table.
- Pipeline rolled out the application without waiting for the migration.
- Migration not backwards compatible with the old version during rollout.

## Diagnostic steps

1. Check the migration job logs and the schema migrations table.
2. Confirm which application version is running.
3. Check for long running transactions that held locks.

## Commands

```sql
SELECT version, applied_at FROM schema_migrations ORDER BY applied_at DESC LIMIT 5;
SELECT pid, now() - xact_start AS age, left(query, 80) FROM pg_stat_activity
  WHERE xact_start IS NOT NULL ORDER BY age DESC LIMIT 10;
```

## Remediation

- Roll back the application to the version that matches the current schema.
- Rerun the migration during low traffic with `SET lock_timeout = '5s'` and retries.
- Make the pipeline block rollout on migration failure.

## Rollback

- If the migration partly applied, run its down migration only after confirming no new data depends on it.

## Risk notes

- Down migrations can drop data. Take a snapshot first.
- Application rollback needs approval from an admin.

## Escalation

- Database on-call for any manual schema change in production.
