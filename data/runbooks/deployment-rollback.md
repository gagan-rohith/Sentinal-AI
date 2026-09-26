---
runbook_id: deployment-rollback
title: Rolling back a bad deployment
tags: [deployment, rollback, release, regression, kubernetes]
actions: [rollback_deployment]
---

# Rolling back a bad deployment

## Symptoms

- Error rate, latency or crash count changed within minutes of a deployment finishing.
- New exception types appear in logs that reference code touched by the release.
- Only pods running the new version are affected during a canary or rolling update.

## Likely causes

- Code regression not covered by tests.
- Config or environment differences between staging and production.
- Incompatible schema or API contract with a dependency.

## Diagnostic steps

1. Identify the deployment id, version and change summary from the deploy history.
2. Compare error rates between old and new pods if both are still running.
3. Check whether the release included a database migration.
4. Confirm the previous version is still available in the registry.

## Commands

```bash
kubectl -n <namespace> rollout history deploy/<service>
kubectl -n <namespace> rollout undo deploy/<service> --to-revision=<revision>
kubectl -n <namespace> rollout status deploy/<service>
```

## Remediation

- Roll back to the previous version. Prefer the pipeline rollback job so the deploy record stays accurate.
- Pause further deploys of the service until the regression is understood.
- Add a regression test before redeploying the fix.

## Rollback

- If the rollback itself fails health checks, roll forward to the previous-previous known good version or scale the old ReplicaSet back up.

## Risk notes

- Rolling back application code after a forward-only migration can break reads or writes. Check migration compatibility first.
- A rollback is a production change and requires approval from an admin on call.

## Escalation

- Escalate to the release manager if the previous version is not available or the rollback is blocked by a migration.
