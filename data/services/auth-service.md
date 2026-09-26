---
service: auth-service
team: identity
namespace: identity
tags: [auth, jwt, jwks, sessions]
---

# auth-service

Issues and validates session tokens. Verifies JWTs from the external identity provider using its JWKS.

## Dependencies

- postgres-identity
- redis-sessions
- idp-jwks (identity provider JWKS endpoint)

## SLOs

- Availability 99.99%
- p99 latency under 150ms

## Known failure modes

- JWKS cache (24h TTL) out of date after key rotation.
- Crash on startup when required env vars are missing.

## Operational notes

- The identity provider rotates signing keys quarterly.
