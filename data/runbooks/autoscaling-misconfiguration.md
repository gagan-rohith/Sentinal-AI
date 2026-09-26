---
runbook_id: autoscaling-misconfiguration
title: Autoscaling misconfiguration
tags: [autoscaling, hpa, kubernetes, capacity, max-replicas, saturation]
actions: []
---

# Autoscaling misconfiguration

## Symptoms

- HPA sits at `maxReplicas` while CPU stays above target.
- Latency and queueing rise with traffic.
- HPA events mention desired replicas above the maximum.

## Likely causes

- `maxReplicas` lowered.
- Target utilization set too high.
- Metrics server or custom metrics adapter not reporting.
- Resource requests changed, which changes the utilization percentage.

## Diagnostic steps

1. Check HPA current, desired and max replicas.
2. Check the HPA config history for recent changes.
3. Confirm the metrics the HPA reads are present.

## Commands

```bash
kubectl -n <namespace> get hpa <service>
kubectl -n <namespace> describe hpa <service> | grep -A10 Events
```

## Remediation

- Restore `maxReplicas` to a value that covers peak traffic with headroom.
- Alert when an HPA is at max for more than 10 minutes.
- Check cluster capacity so new replicas can schedule.

## Rollback

- Revert the HPA manifest.

## Risk notes

- Raising max replicas can push the database past its connection limit. Check downstream capacity.

## Escalation

- Platform team if the cluster autoscaler cannot add nodes.
