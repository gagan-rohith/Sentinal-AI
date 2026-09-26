---
service: billing-service
team: billing
namespace: finance
tags: [billing, invoices, postgres, kafka, s3]
---

# billing-service

Generates invoices and publishes billing events. Writes invoice PDFs to S3.

## Dependencies

- postgres-billing
- kafka (billing.events)
- s3-invoices

## SLOs

- Invoices generated within 1 hour of order completion

## Known failure modes

- Migrations on the invoices table hitting lock timeouts.
- Debug logging left on, filling ephemeral storage.
- Database credential rotation.

## Operational notes

- Migrations run as a pre-deploy job.
