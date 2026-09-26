---
runbook_id: feature-flag-rollback
title: Broken feature flag rollout
tags: [feature-flag, rollout, config, 5xx, ramp]
actions: []
---

# Broken feature flag rollout

## Symptoms

- Errors start the moment a flag is ramped, without a deployment.
- Errors limited to a segment the flag targets (region, currency, plan).
- Stack traces point at code behind the flag.

## Likely causes

- Code path behind the flag missing configuration for some segments.
- Flag ramped straight to 100% without a guarded rollout.
- Flag dependencies (other flags or config) not enabled together.

## Diagnostic steps

1. Check the flag audit log for recent changes and who made them.
2. Compare error rates for requests with the flag on and off.
3. Read the exceptions for missing config keys.

## Commands

```bash
curl -s -H "Authorization: Bearer $FLAG_TOKEN" https://flags.internal/api/flags/<flag>/audit | jq '.[0:5]'
kubectl -n <namespace> logs deploy/<service> --since=15m | grep -i "<flag>"
```

## Remediation

- Turn the flag off. This is the fastest and safest mitigation and does not need a deploy.
- Add the missing configuration, then ramp again in steps with error rate guards.

## Rollback

- Flag changes are reversible in the flag service.

## Risk notes

- Turning a flag off can strand data written in the new format. Check with the owning team.

## Escalation

- Owning feature team. Incident commander if the flag affects payments.
