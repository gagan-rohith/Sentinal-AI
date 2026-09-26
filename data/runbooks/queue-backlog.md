---
runbook_id: queue-backlog
title: Queue backlog
tags: [queue, sqs, backlog, poison-message, dead-letter-queue, workers]
actions: [restart_service]
---

# Queue backlog

## Symptoms

- Queue depth grows and age of oldest message increases.
- Worker throughput drops close to zero while workers are running.
- The same message id appears in failure logs again and again.

## Likely causes

- Poison message that always fails and is redelivered, with no dead letter queue.
- Workers crashed or scaled to zero.
- Downstream dependency of the workers failing.
- Producer burst larger than worker capacity.

## Diagnostic steps

1. Check queue depth, age of oldest message and receive count.
2. Search worker logs for repeated message ids.
3. Check the queue redrive policy.

## Commands

```bash
aws sqs get-queue-attributes --queue-url <url> --attribute-names ApproximateNumberOfMessages ApproximateAgeOfOldestMessage RedrivePolicy
kubectl -n <namespace> logs deploy/<service> --since=15m | grep -o "message [0-9a-f]*" | sort | uniq -c | sort -rn | head
```

## Remediation

- Move the poison message to a quarantine queue.
- Configure a dead letter queue with `maxReceiveCount` of 5.
- Make workers reject unparseable payloads instead of throwing.
- Scale workers temporarily to drain the backlog.

## Rollback

- Remove the redrive policy if it misroutes valid messages.

## Risk notes

- Purging the queue loses all messages. Never purge a production queue without the data owner.

## Escalation

- Owning team and the producer team if malformed messages keep arriving.
