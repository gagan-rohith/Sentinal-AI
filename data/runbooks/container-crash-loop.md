---
runbook_id: container-crash-loop
title: Container CrashLoopBackOff
tags: [kubernetes, crashloop, startup, config, configmap, env]
actions: [rollback_deployment]
---

# Container CrashLoopBackOff

## Symptoms

- Pods in `CrashLoopBackOff` with increasing restart counts.
- Containers exit within seconds of start.
- Only pods created after a change are affected.

## Likely causes

- Missing or renamed environment variable or ConfigMap key.
- Secret not mounted or wrong key name.
- Failing startup dependency check.
- Bad image or entrypoint.

## Diagnostic steps

1. Read the previous container logs for the startup error.
2. Compare the container env with the ConfigMap and Secret keys.
3. Check what changed in config or image right before the first crash.

## Commands

```bash
kubectl -n <namespace> logs <pod> --previous
kubectl -n <namespace> get configmap <service>-config -o yaml
kubectl -n <namespace> describe pod <pod> | grep -A10 Events
```

## Remediation

- Restore the missing key and trigger a rollout.
- If the change came with a release, roll back the release.
- Validate required config keys in CI.

## Rollback

- Revert the ConfigMap change and restart the rollout.

## Risk notes

- Old pods keep serving only until they are replaced. Do not restart old healthy pods while new ones crash.

## Escalation

- Owning team. Platform team if the image cannot be pulled.
