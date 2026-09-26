---
service: user-profile-service
team: identity
namespace: identity
tags: [profiles, postgres, redis, s3]
---

# user-profile-service

Stores user profiles, addresses and avatars.

## Dependencies

- postgres-identity
- redis-cache
- s3-avatars

## SLOs

- Availability 99.9%
- p99 latency under 250ms

## Known failure modes

- Serializer regressions on optional address fields.
- JWT validation failures after key rotation.

## Operational notes

- Addresses may have an empty `line2` and `region`.
