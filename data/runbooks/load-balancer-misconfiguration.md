---
runbook_id: load-balancer-misconfiguration
title: Load balancer misconfiguration
tags: [load-balancer, alb, health-check, "502", target-group, terraform]
actions: []
---

# Load balancer misconfiguration

## Symptoms

- Clients get 502 or 503 from the load balancer.
- Target group reports unhealthy or zero healthy targets.
- Pods are healthy when checked inside the cluster.

## Likely causes

- Health check path, port or protocol changed and no longer matches the service.
- Security group change blocking load balancer to target traffic.
- Listener rule or target group registration changed.

## Diagnostic steps

1. Check target health and the health check failure reason.
2. Compare the health check path with the path the service actually serves.
3. Review the latest Terraform or console changes to the load balancer.

## Commands

```bash
aws elbv2 describe-target-health --target-group-arn <arn>
aws elbv2 describe-target-groups --target-group-arns <arn> --query 'TargetGroups[0].HealthCheckPath'
kubectl -n <namespace> exec deploy/<service> -- curl -s -o /dev/null -w "%{http_code}" localhost:8080/health
```

## Remediation

- Revert the health check or listener change through Terraform.
- Add a plan time check that validates health check paths.

## Rollback

- Apply the previous Terraform state for the load balancer module.

## Risk notes

- Console fixes drift from Terraform and get overwritten on the next apply. Fix in code.

## Escalation

- Platform networking team for listener and security group changes.
