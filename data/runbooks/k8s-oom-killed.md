---
runbook_id: k8s-oom-killed
title: Kubernetes pods OOMKilled
tags: [kubernetes, oom, memory, restarts, exit-137, jvm]
actions: [rollback_deployment, restart_service]
---

# Kubernetes pods OOMKilled

## Symptoms

- Pods restart with `reason: OOMKilled` and exit code 137.
- Container memory climbs to the limit before each restart.
- Intermittent 503s while pods restart. Possible CrashLoopBackOff if the restarts are fast.

## Likely causes

- Memory limit too low for the workload after a code or config change (bigger caches, larger batches).
- Memory leak in the application.
- JVM heap (`-Xmx`) set too close to the container limit, leaving no room for off-heap memory.
- Traffic or payload size increase.

## Diagnostic steps

1. Confirm the termination reason with `kubectl describe pod`.
2. Plot memory per pod over the last 24 hours. A sawtooth that resets on restart suggests a leak, a step change suggests config or code.
3. Check the last deployment and config changes for cache sizes, batch sizes or heap flags.
4. Compare the JVM or runtime heap setting with the container limit.

## Commands

```bash
kubectl -n <namespace> get pods -l app=<service>
kubectl -n <namespace> describe pod <pod> | grep -A5 "Last State"
kubectl -n <namespace> top pods -l app=<service> --containers
```

## Remediation

- Raise the memory limit to cover measured peak usage plus 25% headroom.
- Cap in-process caches and batch sizes through configuration.
- Set the JVM heap to about 75% of the container limit.
- If a recent release caused the growth and limits cannot be raised quickly, roll back the release.

## Rollback

- Revert the limit change through the deployment manifest if it destabilizes node scheduling.
- Roll back the release through the pipeline.

## Risk notes

- Raising limits can make pods unschedulable on small nodes. Check node allocatable memory.
- Restarting pods only resets the leak clock. It is not a fix.

## Escalation

- Page the owning team if more than half of the replicas are restarting.
- Involve the platform team if nodes themselves are under memory pressure.
