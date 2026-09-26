---
runbook_id: tls-certificate-expiration
title: TLS certificate expiration
tags: [tls, certificates, x509, cert-manager, acme, expiry]
actions: []
---

# TLS certificate expiration

## Symptoms

- Clients fail with `x509: certificate has expired or is not yet valid` or `sslv3 alert certificate expired`.
- Every client is affected at once, often starting at a round clock time.
- No deployment or traffic change lines up with the start.

## Likely causes

- Automatic renewal failed (cert-manager, ACM, Let's Encrypt) and nobody noticed.
- ACME challenge failing because DNS provider credentials were rotated or revoked.
- Certificate manually installed and never tracked.

## Diagnostic steps

1. Check the certificate served by the endpoint and its `notAfter` date.
2. Check the cert-manager Certificate and CertificateRequest status and events.
3. Check the issuer and the DNS or HTTP challenge logs.

## Commands

```bash
echo | openssl s_client -connect <host>:443 -servername <host> 2>/dev/null | openssl x509 -noout -dates
kubectl -n <namespace> describe certificate <name>
kubectl -n cert-manager logs deploy/cert-manager --since=24h | grep -i <name>
```

## Remediation

- Fix the issuer credentials and trigger renewal: `cmctl renew <certificate>`.
- If renewal cannot be fixed quickly, issue a certificate manually and install it in the secret.
- Add alerting on certificates that expire within 21 days.

## Rollback

- Keep the previous secret version so a bad manual certificate can be swapped back.

## Risk notes

- Installing a certificate with the wrong chain breaks older clients. Validate the full chain before rollout.

## Escalation

- Security team owns the CA accounts. Escalate if the issuer account itself is locked.
