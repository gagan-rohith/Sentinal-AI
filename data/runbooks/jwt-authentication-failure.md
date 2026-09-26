---
runbook_id: jwt-authentication-failure
title: JWT authentication failures
tags: [auth, jwt, jwks, key-rotation, "401", oauth]
actions: [restart_service]
---

# JWT authentication failures

## Symptoms

- Spike in HTTP 401 responses for users with valid sessions.
- Logs show `signature verification failed` or `kid not found in JWKS`.
- Only tokens issued after a certain time are rejected.

## Likely causes

- Signing key rotated at the identity provider while services cache the old JWKS.
- Verifier does not refetch the JWKS when it sees an unknown `kid`.
- Clock skew between issuer and verifier causing `nbf` or `exp` failures.
- Audience or issuer claim changed in configuration.

## Diagnostic steps

1. Decode a failing token and read its `kid`, `iss`, `aud`, `exp`.
2. Compare the `kid` with the keys in the cached JWKS and in the provider's current JWKS.
3. Check when the provider last rotated keys.
4. Check node clocks for skew.

## Commands

```bash
curl -s https://<issuer>/.well-known/jwks.json | jq '.keys[].kid'
kubectl -n <namespace> logs deploy/<service> --since=30m | grep -i "jwks"
```

## Remediation

- Force the service to reload the JWKS. A rolling restart does this but is a production change and needs approval.
- Change the verifier to refetch JWKS on unknown `kid` with rate limiting.
- Ask the identity team to publish new keys at least 24 hours before signing with them.

## Rollback

- The identity provider can temporarily sign with the previous key while services catch up.

## Risk notes

- Disabling signature verification is never an acceptable mitigation.
- A full restart logs out users whose sessions live in memory.

## Escalation

- Page the identity team if the provider's JWKS endpoint is unavailable.
