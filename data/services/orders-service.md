---
service: orders-service
team: orders
namespace: commerce
tags: [orders, postgres, kafka, jvm]
---

# orders-service

Creates and tracks orders and publishes order events to Kafka. JVM service.

## Dependencies

- postgres-orders
- kafka (topic orders.events)
- inventory-service

## SLOs

- Availability 99.9%
- p99 latency under 600ms

## Known failure modes

- Memory growth from the in-process product catalog cache. Heap is set to 75% of the container limit.
- Schema migrations on the orders table are slow because of its size.

## Operational notes

- Memory limit 512Mi, CPU limit 2 cores.
