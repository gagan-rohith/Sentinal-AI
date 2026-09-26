---
runbook_id: cpu-throttling
title: CPU throttling in Kubernetes
tags: [kubernetes, cpu, throttling, cfs, limits, latency]
actions: []
---

# CPU throttling in Kubernetes

## Symptoms

- Latency rises while average CPU utilization looks moderate.
- `container_cpu_cfs_throttled_periods_total` increasing, throttled ratio above 25%.
- Worker or thread pools saturated during bursts.

## Likely causes

- CPU limit set too low for bursty workloads. The CFS quota is used up early in each 100ms period.
- Limit reduced as part of a cost exercise.
- Runtime thread count sized for the node rather than the limit.

## Diagnostic steps

1. Compare the throttled ratio with latency over the same window.
2. Check the current CPU request and limit and when they last changed.
3. Look at per-second CPU usage, not averages, to see bursts.

## Commands

```bash
kubectl -n <namespace> get deploy <service> -o jsonpath='{.spec.template.spec.containers[0].resources}'
```

```promql
rate(container_cpu_cfs_throttled_periods_total{pod=~"<service>.*"}[5m])
  / rate(container_cpu_cfs_periods_total{pod=~"<service>.*"}[5m])
```

## Remediation

- Raise the CPU limit or remove it and keep a realistic request.
- Size runtime worker threads to the CPU limit.
- Alert on the throttled ratio.

## Rollback

- Revert the resource change in the manifest.

## Risk notes

- Removing limits lets a noisy pod affect neighbours. Keep requests accurate so the scheduler places pods correctly.

## Escalation

- Platform team if node CPU is also saturated.
