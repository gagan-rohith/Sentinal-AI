---
runbook_id: disk-pressure
title: Node disk pressure and pod evictions
tags: [disk, kubernetes, ephemeral-storage, eviction, logging, enospc]
actions: []
---

# Node disk pressure and pod evictions

## Symptoms

- Node condition `DiskPressure=True`.
- Pods evicted with `The node was low on resource: ephemeral-storage`.
- Writes fail with `no space left on device`.

## Likely causes

- Verbose or debug logging written to local files.
- Temporary files or caches not cleaned up.
- Container images piling up on nodes.
- No ephemeral-storage limits on pods.

## Diagnostic steps

1. Find which nodes report DiskPressure and which pods were evicted.
2. Check ephemeral-storage usage per pod.
3. Check recent config changes to log levels or file based logging.

## Commands

```bash
kubectl get nodes -o custom-columns=NAME:.metadata.name,DISK:.status.conditions[?(@.type=="DiskPressure")].status
kubectl -n <namespace> get events --field-selector reason=Evicted
kubectl -n <namespace> exec <pod> -- du -sh /var/log/app
```

## Remediation

- Revert log level to INFO and log to stdout instead of files.
- Remove oversized files from affected pods or let evicted pods reschedule.
- Set ephemeral-storage requests and limits.

## Rollback

- Revert config changes through the config repo.

## Risk notes

- Deleting files from a running container may remove data the service still needs. Only delete logs and temp files.

## Escalation

- Platform team if node root volumes are full from images or system logs.
