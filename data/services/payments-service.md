---
service: payments-service
team: payments
namespace: commerce
tags: [payments, pci, postgres, third-party]
---

# payments-service

Authorizes and captures card payments through the Stripe gateway. PCI scoped.

## Dependencies

- postgres-payments
- stripe-gateway (third party)
- auth-service for service tokens

## SLOs

- Availability 99.95%
- p99 latency under 1500ms (includes gateway round trip)

## Known failure modes

- Database credential rotation: credentials are read at startup.
- Gateway latency spikes.
- TLS certificate on the internal endpoint managed by cert-manager.

## Operational notes

- Restarts must be rolling. Never scale below 2 replicas.
