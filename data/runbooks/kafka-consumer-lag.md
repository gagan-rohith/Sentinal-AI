---
runbook_id: kafka-consumer-lag
title: Kafka consumer lag
tags: [kafka, consumer-lag, rebalance, streaming, max-poll]
actions: [restart_service]
---

# Kafka consumer lag

## Symptoms

- Consumer group lag grows steadily and does not recover.
- Consumer throughput drops while producer rate is normal.
- Logs show frequent rebalances, `poll timeout has expired` or heartbeat failures.

## Likely causes

- Processing a poll batch takes longer than `max.poll.interval.ms`, so the consumer is evicted and the group rebalances.
- `max.poll.records` increased, making batches slower.
- Slow downstream dependency called per message.
- Too few consumers for the partition count, or a hot partition.
- Poison message causing repeated failures.

## Diagnostic steps

1. Check lag per partition. Uniform lag suggests consumer slowness, one hot partition suggests key skew.
2. Count rebalances per minute from the consumer logs.
3. Compare batch processing time with `max.poll.interval.ms`.
4. Review recent consumer config changes.

## Commands

```bash
kafka-consumer-groups.sh --bootstrap-server <broker> --describe --group <group>
kubectl -n <namespace> logs deploy/<service> --since=15m | grep -ci rebalanc
```

## Remediation

- Revert `max.poll.records` or raise `max.poll.interval.ms` above the worst case batch time.
- Scale consumers up to the partition count.
- Move slow downstream calls out of the poll loop or batch them.
- Once stable, monitor lag until it drains.

## Rollback

- Revert consumer config through the config repo and redeploy.

## Risk notes

- Restarting consumers triggers another rebalance and can make lag worse in the short term.
- Resetting offsets skips messages. Only do it with data owner approval.

## Escalation

- Escalate to the data platform team if brokers show under-replicated partitions or high request latency.
