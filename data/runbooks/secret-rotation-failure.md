---
runbook_id: secret-rotation-failure
title: Secret rotation failure
tags: [secrets, rotation, credentials, database, secrets-manager, password]
actions: [restart_service]
---

# Secret rotation failure

## Symptoms

- `password authentication failed` or `invalid credentials` right after a rotation.
- Existing pooled connections work, new connections fail.
- Pool size shrinks over time as connections are recycled.

## Likely causes

- Service reads secrets only at startup and never reloads.
- Rotation lambda updated the database but not the secret, or the other way round.
- Secret mounted as a file that is not refreshed.

## Diagnostic steps

1. Check the rotation history and status in the secret store.
2. Confirm the database accepts the current secret value.
3. Check when the running pods loaded their credentials.

## Commands

```bash
aws secretsmanager describe-secret --secret-id <secret> --query 'RotationEnabled,LastRotatedDate'
kubectl -n <namespace> get pods -l app=<service> -o custom-columns=NAME:.metadata.name,START:.status.startTime
```

## Remediation

- Rolling restart of the service so pods load the new secret. This is a production change and needs approval.
- Add secret reloading or use a dual user rotation strategy so the old credential stays valid until all clients switch.

## Rollback

- Restore the previous secret version (AWSPREVIOUS) if the new credential is invalid on the database.

## Risk notes

- Restarting every pod at once causes an outage. Use a rolling restart with surge.

## Escalation

- Security team owns rotation lambdas. Escalate if the rotation left the secret and database out of sync.
