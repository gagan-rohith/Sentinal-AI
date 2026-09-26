---
service: notification-worker
team: messaging
namespace: messaging
tags: [notifications, sqs, ses, worker]
---

# notification-worker

Consumes notification requests from SQS and sends email through SES and push through the push provider.

## Dependencies

- sqs-notifications
- ses
- kafka (user events)
- s3 bucket for rendered templates

## SLOs

- 99% of notifications sent within 2 minutes

## Known failure modes

- Poison messages when producers send malformed payloads.
- IAM changes removing S3 or SES permissions.

## Operational notes

- The notifications queue has no dead letter queue configured yet (tracked in MSG-412).
