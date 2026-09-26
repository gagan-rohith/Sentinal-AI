---
service: api-gateway
team: platform
namespace: edge
tags: [gateway, edge, alb, tls, dns]
---

# api-gateway

Edge gateway behind an AWS ALB. Terminates TLS, authenticates requests and routes to backend services.

## Dependencies

- checkout-api, search-api, auth-service
- coredns for service discovery
- ALB target group api-gateway-tg (health check path /health)

## SLOs

- Availability 99.99%
- Added latency under 20ms p99

## Known failure modes

- Certificate expiry on the public listener.
- Health check path drift after Terraform changes.
- DNS timeouts when CoreDNS is under-replicated.

## Operational notes

- Health endpoint is `/health`, not `/healthz`.
