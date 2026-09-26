---
service: analytics-consumer
team: data-platform
namespace: data
tags: [kafka, analytics, s3, streaming]
---

# analytics-consumer

Kafka consumer that aggregates product and order events and writes hourly files to the S3 data lake.

## Dependencies

- kafka (topics orders.events, clicks.events; 24 partitions each)
- s3-datalake

## SLOs

- Consumer lag under 10k messages
- Hourly files delivered within 20 minutes of the hour

## Known failure modes

- Rebalance loops when batch processing exceeds max.poll.interval.ms.
- Disk usage from local spill files.
- IAM permission changes on the data lake bucket.

## Operational notes

- 3 replicas, 8 consumer threads each.
