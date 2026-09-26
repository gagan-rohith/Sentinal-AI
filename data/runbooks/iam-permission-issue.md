---
runbook_id: iam-permission-issue
title: AWS IAM permission regression
tags: [iam, aws, permissions, access-denied, terraform, s3]
actions: []
---

# AWS IAM permission regression

## Symptoms

- `AccessDenied` or `not authorized to perform` errors in service logs.
- Failures start right after an IAM or Terraform change.
- Some API actions succeed while others fail for the same role.

## Likely causes

- Policy refactor dropped a statement or narrowed a resource ARN.
- Permission boundary or SCP added.
- Service assumed a different role after a deployment change.

## Diagnostic steps

1. Read the exact action and resource from the error message.
2. Simulate the call against the role policy.
3. Diff the latest Terraform apply for the role.
4. Check CloudTrail for the denied calls.

## Commands

```bash
aws iam simulate-principal-policy --policy-source-arn <role-arn> --action-names s3:PutObject --resource-arns <arn>
aws cloudtrail lookup-events --lookup-attributes AttributeKey=EventName,AttributeValue=PutObject --max-results 20
```

## Remediation

- Restore the missing statement in Terraform and apply.
- Add IAM policy tests or Access Analyzer policy checks to the pipeline.

## Rollback

- Revert the Terraform commit and apply the previous plan.

## Risk notes

- Do not grant wildcard actions as a quick fix. Restore the exact statement.

## Escalation

- Cloud security team must review any change to trust policies or boundaries.
