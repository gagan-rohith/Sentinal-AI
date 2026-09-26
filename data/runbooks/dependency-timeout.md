---
runbook_id: dependency-timeout
title: Downstream dependency timeouts
tags: [dependency, timeout, circuit-breaker, third-party, latency, fallback]
actions: []
---

# Downstream dependency timeouts

## Symptoms

- Logs show `Timeout calling <dependency>` and circuit breaker state changes.
- Latency of the service tracks the dependency's latency.
- Thread or connection pools for outbound calls are exhausted.

## Likely causes

- Third party or internal dependency degraded.
- Timeouts set too high, so callers wait instead of failing fast.
- No fallback path for the dependency.
- Retry storms multiplying load on the dependency.

## Diagnostic steps

1. Measure the dependency latency from the client side and check its status page.
2. Check timeout, retry and circuit breaker settings.
3. Check outbound pool usage.

## Commands

```bash
kubectl -n <namespace> logs deploy/<service> --since=15m | grep -i "circuitbreaker"
curl -o /dev/null -s -w "%{time_total}\n" https://<dependency>/health
```

## Remediation

- Lower the timeout to fit the caller's latency budget and cap retries.
- Serve cached or default responses while the breaker is open.
- Contact the dependency owner or vendor.

## Rollback

- Revert timeout and breaker config changes through the config repo.

## Risk notes

- Aggressive retries can turn a partial outage at the dependency into a full one.

## Escalation

- Vendor support for third party outages. Internal owner's on-call for internal dependencies.
