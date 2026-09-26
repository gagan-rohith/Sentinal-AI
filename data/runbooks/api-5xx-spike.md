---
runbook_id: api-5xx-spike
title: API 5xx error spike
tags: [5xx, http, errors, api, deployment, dependency]
actions: [rollback_deployment, restart_service]
---

# API 5xx error spike

## Symptoms

- HTTP 500, 502, 503 or 504 responses above the SLO error budget burn threshold.
- Error rate alert fires on the service or on the API gateway.
- Users report failed requests or error pages.

## Likely causes

- A recent deployment introduced a regression.
- A feature flag change enabled a broken code path.
- A downstream dependency (database, cache, third party) is failing or slow.
- Resource exhaustion: connection pools, threads, memory.
- Infrastructure change in front of the service (load balancer, ingress, DNS).

## Diagnostic steps

1. Split errors by status code. 500 usually means application exceptions, 502 and 503 point at the proxy or unavailable upstream, 504 at timeouts.
2. Line up the error start time with deployments, flag changes and config changes in the last hour.
3. Read the top exception messages in the service logs for the window.
4. Check dependency health and latency.
5. Check saturation metrics: CPU, memory, pool usage.

## Commands

```bash
kubectl -n <namespace> rollout history deploy/<service>
kubectl -n <namespace> logs deploy/<service> --since=15m | grep -E "ERROR|Exception" | sort | uniq -c | sort -rn | head
```

## Remediation

- If errors started with a deployment and the stack traces point at new code, roll back the deployment.
- If a feature flag changed, turn the flag off.
- If a dependency is failing, follow that dependency's runbook and enable fallbacks.
- If a pool or resource is exhausted, follow the matching resource runbook.

## Rollback

- Roll back to the last known good version: `kubectl -n <namespace> rollout undo deploy/<service>` or the pipeline rollback job.
- Revert config or flag changes through the same system that made them.

## Risk notes

- Rollbacks that cross a schema migration can fail if the old version cannot read the new schema. Check migration history first.
- Restarting pods rarely fixes application exceptions and hides evidence. Capture logs first.

## Escalation

- Page the owning team if the error rate is above 5% for 5 minutes.
- Declare a SEV1 when a revenue path (checkout, payments, login) is failing for more than 10% of users.
