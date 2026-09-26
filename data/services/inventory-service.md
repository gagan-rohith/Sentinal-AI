---
service: inventory-service
team: inventory
namespace: commerce
tags: [inventory, postgres, kafka]
---

# inventory-service

Tracks stock levels and reservations. Consumes order events from Kafka.

## Dependencies

- postgres-inventory
- kafka (topic orders.events)

## SLOs

- Availability 99.9%
- p99 latency under 400ms

## Known failure modes

- Startup crash when DATABASE_URL is missing from the ConfigMap.
- DNS lookup failures to Kafka brokers.

## Operational notes

- Requires env vars DATABASE_URL, KAFKA_BROKERS, PORT.
