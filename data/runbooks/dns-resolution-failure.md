---
runbook_id: dns-resolution-failure
title: DNS resolution failures
tags: [dns, coredns, kubernetes, networking, ndots, timeouts]
actions: []
---

# DNS resolution failures

## Symptoms

- `lookup ... i/o timeout`, `EAI_AGAIN` or `no such host` errors across many dependencies at once.
- Failures are intermittent and not tied to one downstream.
- CoreDNS pods show high CPU or dropped queries.

## Likely causes

- CoreDNS under-replicated or throttled after node changes.
- High query volume from `ndots:5` search path expansion.
- conntrack table exhaustion on nodes for UDP traffic.
- Upstream resolver outage for external names.

## Diagnostic steps

1. Check CoreDNS replica count, CPU and restarts.
2. Look at CoreDNS metrics for request rate and SERVFAIL rate.
3. Resolve an internal name from a debug pod several times and time it.
4. Check node conntrack usage.

## Commands

```bash
kubectl -n kube-system get deploy coredns
kubectl -n kube-system top pods -l k8s-app=kube-dns
kubectl run dnsdebug --rm -it --image=busybox --restart=Never -- nslookup kubernetes.default
```

## Remediation

- Scale CoreDNS to at least 3 replicas and add a PodDisruptionBudget.
- Deploy NodeLocal DNSCache.
- Lower `ndots` in pod dnsConfig for services that mostly call external names.

## Rollback

- Scaling CoreDNS is safe to revert. Revert NodeLocal DNSCache by removing its DaemonSet.

## Risk notes

- Editing the CoreDNS ConfigMap reloads every CoreDNS pod. A syntax error takes down cluster DNS.

## Escalation

- Platform team owns CoreDNS. Page them if scaling does not recover resolution within 5 minutes.
