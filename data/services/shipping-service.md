---
service: shipping-service
team: fulfillment
namespace: commerce
tags: [shipping, third-party, sqs, rates]
---

# shipping-service

Calculates shipping rates through a third party provider and books shipments.

## Dependencies

- shipping-rates-provider (third party, 10s timeout)
- postgres-orders
- sqs-shipments

## SLOs

- Rate quote p99 under 1s

## Known failure modes

- Provider latency causing thread exhaustion.
- Queue backlogs on shipment booking.

## Operational notes

- Circuit breaker `shipping-rates` opens at 50% failures over 20 calls.
