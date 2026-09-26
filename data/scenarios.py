from dataclasses import dataclass, field

from core.enums import ChangeType, Severity


@dataclass(frozen=True)
class Anomaly:
    baseline: float
    peak: float
    unit: str
    # Physical ceilings (pool size, replica caps) are not scaled per variant or exceeded by noise.
    hard_limit: bool = False


@dataclass(frozen=True)
class Scenario:
    category: str
    runbook_ids: tuple[str, ...]
    services: tuple[str, str, str]
    title: str
    description: str
    symptoms: tuple[str, ...]
    error_messages: tuple[str, ...]
    log_errors: tuple[str, ...]
    anomalies: dict[str, Anomaly]
    root_cause: str
    remediation: str
    severities: tuple[Severity, Severity, Severity]
    tags: tuple[str, ...]
    change: tuple[ChangeType, str] | None = None
    change_offset_min: int = 20
    # An unrelated deploy shortly before the incident, so agents have to rule it out.
    distractor_deploy: str | None = None
    extra_logs: tuple[str, ...] = field(default_factory=tuple)


S1, S2, S3 = Severity.SEV1, Severity.SEV2, Severity.SEV3

SCENARIOS: list[Scenario] = [
    Scenario(
        category="postgres_pool_exhaustion",
        runbook_ids=("postgres-connection-pool-exhaustion", "api-5xx-spike"),
        services=("checkout-api", "orders-service", "payments-service"),
        title="{service} 5xx spike after traffic increase",
        description=(
            "{service} is returning HTTP 500 and 503 errors for a large share of requests. "
            "Latency climbed sharply at the same time as a traffic increase. "
            "Requests appear to be waiting on the database."
        ),
        symptoms=(
            "HTTP 5xx error rate above 15%",
            "p99 latency above 4 seconds",
            "request threads blocked waiting for database connections",
            "traffic roughly 2.5x normal",
        ),
        error_messages=(
            "HikariPool-1 - Connection is not available, request timed out after 30000ms",
            "FATAL: remaining connection slots are reserved for non-replication superuser "
            "connections",
        ),
        log_errors=(
            "HikariPool-1 - Connection is not available, request timed out after 30000ms",
            "Failed to obtain JDBC Connection; pool stats (total=100, active=100, idle=0, "
            "waiting=412)",
            "POST /api/v1/checkout 503 Service Unavailable duration=30012ms",
            "FATAL: remaining connection slots are reserved for non-replication superuser "
            "connections",
            "slow query: SELECT ... FROM cart_items WHERE cart_id = $1 took 2840ms",
        ),
        anomalies={
            "error_rate_pct": Anomaly(0.3, 18.0, "%"),
            "p99_latency_ms": Anomaly(180, 4300, "ms"),
            "requests_per_sec": Anomaly(420, 1050, "req/s"),
            "db_connections_in_use": Anomaly(38, 100, "connections", hard_limit=True),
            "db_pool_wait_ms": Anomaly(2, 9500, "ms"),
        },
        change=(ChangeType.TRAFFIC, "Flash sale campaign launched; traffic about 2.5x baseline"),
        change_offset_min=25,
        distractor_deploy="Copy change on order confirmation page",
        root_cause=(
            "PostgreSQL connection pool exhaustion. The traffic surge from the flash sale "
            "saturated the fixed pool of 100 connections, slow queries held connections longer, "
            "and requests queued until they timed out and returned 5xx."
        ),
        remediation=(
            "Raise the connection pool size within the database max_connections budget, put "
            "PgBouncer in front of PostgreSQL, terminate idle-in-transaction sessions, rate limit "
            "campaign traffic, and restart the service only if connections have leaked."
        ),
        severities=(S1, S2, S2),
        tags=("database", "postgres", "connection-pool", "5xx", "traffic"),
    ),
    Scenario(
        category="k8s_oom_killed",
        runbook_ids=("k8s-oom-killed",),
        services=("orders-service", "search-api", "analytics-consumer"),
        title="{service} pods OOMKilled and restarting",
        description=(
            "Pods for {service} are being terminated with exit code 137 and restarting. "
            "Memory climbs steadily until each container is killed."
        ),
        symptoms=(
            "pods restarting with exit code 137",
            "container memory at 99% of limit before each restart",
            "intermittent 503 responses during restarts",
        ),
        error_messages=(
            "Container {service} terminated: reason=OOMKilled exitCode=137",
            "Back-off restarting failed container",
        ),
        log_errors=(
            "Container {service} terminated: reason=OOMKilled exitCode=137",
            "java.lang.OutOfMemoryError: Java heap space",
            "GC overhead: 91% of time spent in garbage collection over last 60s",
            "memory usage 508Mi of 512Mi limit",
            "Back-off restarting failed container {service} in pod {pod}",
        ),
        anomalies={
            "memory_pct": Anomaly(55, 99, "%"),
            "pod_restarts": Anomaly(0, 7, "count"),
            "error_rate_pct": Anomaly(0.3, 6.0, "%"),
        },
        change=(
            ChangeType.DEPLOYMENT,
            "Increase in-process product catalog cache from 256MB to 2GB",
        ),
        root_cause=(
            "The container memory limit of 512Mi is too small after a release enlarged the "
            "in-process cache. Heap usage grows until the kernel OOM kills the container."
        ),
        remediation=(
            "Raise the memory limit to 1Gi and cap the cache size through configuration. "
            "If that cannot be done quickly, roll back the release that enlarged the cache."
        ),
        severities=(S2, S2, S3),
        tags=("kubernetes", "oom", "memory", "restarts"),
    ),
    Scenario(
        category="kafka_consumer_lag",
        runbook_ids=("kafka-consumer-lag",),
        services=("analytics-consumer", "notification-worker", "billing-service"),
        title="Kafka consumer lag growing for {service}",
        description=(
            "Consumer lag for the {service} consumer group has grown past 200k messages and "
            "throughput has dropped. The group keeps rebalancing."
        ),
        symptoms=(
            "consumer lag above 200k messages and rising",
            "consumer throughput dropped by over 90%",
            "frequent consumer group rebalances",
        ),
        error_messages=(
            "consumer poll timeout has expired; leaving group",
            "Attempt to heartbeat failed since group is rebalancing",
        ),
        log_errors=(
            "Member consumer-{service}-3 sending LeaveGroup request to coordinator: consumer "
            "poll timeout has expired",
            "Attempt to heartbeat failed since group is rebalancing",
            "Revoking previously assigned partitions [events-0, events-1, events-2]",
            "Batch of 5000 records took 412s to process (max.poll.interval.ms=300000)",
        ),
        anomalies={
            "kafka_consumer_lag": Anomaly(200, 250000, "messages"),
            "consumer_throughput": Anomaly(1200, 80, "msgs/s"),
            "rebalances_per_min": Anomaly(0, 6, "count"),
        },
        change=(ChangeType.CONFIG, "Increased max.poll.records from 500 to 5000"),
        root_cause=(
            "The consumer group is stuck in a rebalance loop. Raising max.poll.records to 5000 "
            "made each batch take longer than max.poll.interval.ms, so consumers are evicted "
            "from the group before they commit offsets."
        ),
        remediation=(
            "Revert max.poll.records to 500 or raise max.poll.interval.ms above the worst batch "
            "time, then scale consumers to the partition count to drain the backlog."
        ),
        severities=(S2, S3, S2),
        tags=("kafka", "consumer-lag", "rebalance", "streaming"),
    ),
    Scenario(
        category="bad_deployment",
        runbook_ids=("api-5xx-spike", "deployment-rollback"),
        services=("payments-service", "user-profile-service", "shipping-service"),
        title="{service} 5xx errors after deployment",
        description=(
            "Minutes after a new release of {service}, roughly a third of requests fail with "
            "HTTP 500. No traffic change was observed."
        ),
        symptoms=(
            "HTTP 500 rate jumped from under 1% to about 30%",
            "errors started within minutes of a deployment",
            "stack traces point to the response serializer",
        ),
        error_messages=(
            "java.lang.NullPointerException at AddressSerializer.serialize("
            "AddressSerializer.java:48)",
            "GET /api/v1/addresses 500 Internal Server Error",
        ),
        log_errors=(
            "java.lang.NullPointerException at AddressSerializer.serialize("
            "AddressSerializer.java:48)",
            "Unhandled exception while writing response body",
            "GET /api/v1/addresses 500 Internal Server Error duration=35ms",
        ),
        anomalies={
            "error_rate_pct": Anomaly(0.4, 31.0, "%"),
        },
        change=(ChangeType.DEPLOYMENT, "Refactor serializer for address payloads"),
        change_offset_min=12,
        root_cause=(
            "The latest deployment introduced a regression in the address response serializer. "
            "Records without an optional field throw a NullPointerException and return 500."
        ),
        remediation=(
            "Roll back to the previous version, then add a regression test for addresses "
            "without the optional field before redeploying."
        ),
        severities=(S1, S2, S2),
        tags=("deployment", "regression", "5xx", "rollback"),
    ),
    Scenario(
        category="dns_resolution_failure",
        runbook_ids=("dns-resolution-failure",),
        services=("api-gateway", "notification-worker", "inventory-service"),
        title="DNS lookup failures from {service}",
        description=(
            "{service} is intermittently failing to resolve internal service names. Calls to "
            "downstream services fail with lookup timeouts."
        ),
        symptoms=(
            "intermittent name resolution timeouts",
            "errors spread across all downstream dependencies",
            "CoreDNS pods at high CPU",
        ),
        error_messages=(
            "dial tcp: lookup payments-service.commerce.svc.cluster.local on 10.96.0.10:53: "
            "i/o timeout",
            "getaddrinfo EAI_AGAIN orders-service.commerce.svc.cluster.local",
        ),
        log_errors=(
            "dial tcp: lookup payments-service.commerce.svc.cluster.local on 10.96.0.10:53: "
            "i/o timeout",
            "getaddrinfo EAI_AGAIN orders-service.commerce.svc.cluster.local",
            "upstream connect error: name resolution failed",
        ),
        anomalies={
            "error_rate_pct": Anomaly(0.2, 9.0, "%"),
            "dns_lookup_errors_per_min": Anomaly(0, 850, "count"),
            "coredns_cpu_pct": Anomaly(20, 98, "%"),
        },
        change=(
            ChangeType.INFRASTRUCTURE,
            "Node pool rotation reduced CoreDNS replicas from 3 to 1",
        ),
        root_cause=(
            "CoreDNS was left with a single replica after a node pool rotation. With ndots:5 "
            "search path expansion each lookup produces several queries, and the single "
            "replica is overloaded and drops requests."
        ),
        remediation=(
            "Scale CoreDNS back to at least 3 replicas, add a PodDisruptionBudget, enable "
            "NodeLocal DNSCache, and lower ndots for services that call external names."
        ),
        severities=(S1, S2, S3),
        tags=("dns", "coredns", "kubernetes", "networking"),
    ),
    Scenario(
        category="tls_certificate_expired",
        runbook_ids=("tls-certificate-expiration",),
        services=("api-gateway", "payments-service", "auth-service"),
        title="TLS handshake failures on {service}",
        description=(
            "Clients connecting to {service} fail the TLS handshake. Errors started at "
            "midnight UTC and affect every client."
        ),
        symptoms=(
            "all HTTPS clients failing handshake",
            "errors started at a round clock time",
            "no recent deployment",
        ),
        error_messages=(
            "x509: certificate has expired or is not yet valid",
            "SSL routines:ssl3_read_bytes:sslv3 alert certificate expired",
        ),
        log_errors=(
            "x509: certificate has expired or is not yet valid: current time is after notAfter",
            "SSL routines:ssl3_read_bytes:sslv3 alert certificate expired",
            "cert-manager: failed to renew certificate {service}-tls: ACME DNS-01 challenge "
            "failed: access denied",
        ),
        anomalies={
            "error_rate_pct": Anomaly(0.1, 97.0, "%"),
            "tls_handshake_failures_per_min": Anomaly(0, 5200, "count"),
        },
        root_cause=(
            "The TLS certificate for {service} expired because cert-manager could not renew "
            "it. The ACME DNS-01 challenge has been failing since the DNS provider credentials "
            "were revoked."
        ),
        remediation=(
            "Issue and install a replacement certificate, restore the DNS provider credentials "
            "used by cert-manager, and alert on certificates expiring within 21 days."
        ),
        severities=(S1, S1, S2),
        tags=("tls", "certificates", "cert-manager", "expiry"),
    ),
    Scenario(
        category="jwt_auth_failure",
        runbook_ids=("jwt-authentication-failure",),
        services=("auth-service", "user-profile-service", "checkout-api"),
        title="Spike in 401 responses on {service}",
        description=(
            "{service} is rejecting valid user sessions with HTTP 401. The failures began "
            "shortly after the identity provider rotated its signing key."
        ),
        symptoms=(
            "401 rate above 40% for logged in users",
            "only tokens issued after the rotation are rejected",
            "users forced to log in repeatedly",
        ),
        error_messages=(
            "JWT verification failed: kid 2026-key-b not found in JWKS",
            "401 Unauthorized: invalid token signature",
        ),
        log_errors=(
            "JWT verification failed: kid 2026-key-b not found in JWKS",
            "Using cached JWKS fetched 19h ago (ttl=24h)",
            "401 Unauthorized: invalid token signature",
        ),
        anomalies={
            "auth_failures_per_min": Anomaly(15, 3800, "count"),
            "error_rate_pct": Anomaly(0.5, 42.0, "%"),
        },
        change=(ChangeType.SECRET_ROTATION, "Identity provider rotated JWT signing key"),
        change_offset_min=30,
        root_cause=(
            "The identity provider rotated its JWT signing key, but {service} caches the JWKS "
            "for 24 hours and does not refetch when it sees an unknown key id, so tokens signed "
            "with the new key are rejected."
        ),
        remediation=(
            "Force a JWKS refresh by restarting or reloading the service, change the verifier "
            "to refetch JWKS on unknown kid, and publish new keys before they are used for "
            "signing."
        ),
        severities=(S1, S2, S2),
        tags=("auth", "jwt", "jwks", "key-rotation"),
    ),
    Scenario(
        category="redis_memory_eviction",
        runbook_ids=("redis-memory-pressure",),
        services=("search-api", "checkout-api", "user-profile-service"),
        title="{service} latency up as Redis evicts keys",
        description=(
            "Redis used by {service} hit maxmemory and is evicting keys. Cache hit ratio "
            "collapsed and latency and database load increased."
        ),
        symptoms=(
            "Redis memory at maxmemory",
            "thousands of evictions per second",
            "cache hit ratio dropped from 95% to about 40%",
        ),
        error_messages=("OOM command not allowed when used memory > 'maxmemory'",),
        log_errors=(
            "OOM command not allowed when used memory > 'maxmemory'",
            "cache miss rate high; falling back to database for product lookups",
            "redis keyspace: 4.1M keys without expiry under prefix session:",
        ),
        anomalies={
            "redis_memory_pct": Anomaly(68, 100, "%"),
            "redis_evicted_keys_per_sec": Anomaly(0, 4500, "keys/s"),
            "cache_hit_ratio_pct": Anomaly(95, 41, "%"),
            "p99_latency_ms": Anomaly(120, 1400, "ms"),
        },
        change=(ChangeType.DEPLOYMENT, "Store user sessions in the shared cache cluster"),
        change_offset_min=45,
        root_cause=(
            "Redis reached maxmemory because a release started writing session keys without a "
            "TTL. The allkeys-lru policy evicts hot cache entries instead, so the hit ratio "
            "collapsed and requests fell through to the database."
        ),
        remediation=(
            "Set a TTL on session keys and expire the existing ones, move sessions to a "
            "separate Redis instance, and alert on memory above 85% of maxmemory."
        ),
        severities=(S2, S2, S3),
        tags=("redis", "cache", "eviction", "memory"),
    ),
    Scenario(
        category="cpu_throttling",
        runbook_ids=("cpu-throttling",),
        services=("search-api", "orders-service", "inventory-service"),
        title="{service} p99 latency high while CPU looks normal",
        description=(
            "{service} p99 latency has tripled. Average CPU utilization looks moderate, but "
            "containers are being throttled heavily."
        ),
        symptoms=(
            "p99 latency tripled",
            "average CPU utilization around 45%",
            "CFS throttled periods above 60%",
        ),
        error_messages=("request exceeded latency budget of 500ms",),
        log_errors=(
            "request exceeded latency budget of 500ms (took 1630ms)",
            "worker pool saturation: 64/64 threads busy",
        ),
        anomalies={
            "cpu_throttled_pct": Anomaly(2, 68, "%"),
            "p99_latency_ms": Anomaly(120, 1650, "ms"),
            "cpu_pct": Anomaly(40, 46, "%"),
        },
        change=(ChangeType.CONFIG, "Reduced CPU limit from 2 cores to 500m for cost savings"),
        change_offset_min=60,
        root_cause=(
            "The CPU limit was cut to 500m. Request handling is bursty, so containers use "
            "their CFS quota early in each period and are throttled, which inflates latency "
            "even though average utilization looks moderate."
        ),
        remediation=(
            "Restore the CPU limit to 2 cores or remove the limit while keeping the request, "
            "and alert on container_cpu_cfs_throttled_periods_total."
        ),
        severities=(S2, S3, S3),
        tags=("kubernetes", "cpu", "throttling", "latency"),
    ),
    Scenario(
        category="disk_pressure",
        runbook_ids=("disk-pressure",),
        services=("analytics-consumer", "billing-service", "search-api"),
        title="{service} pods evicted due to disk pressure",
        description=(
            "Nodes running {service} report DiskPressure and the kubelet is evicting pods. "
            "Writes fail with no space left on device."
        ),
        symptoms=(
            "node condition DiskPressure=True",
            "pods evicted for ephemeral-storage",
            "write failures with ENOSPC",
        ),
        error_messages=(
            "write /var/log/app/{service}.log: no space left on device",
            "The node was low on resource: ephemeral-storage",
        ),
        log_errors=(
            "write /var/log/app/{service}.log: no space left on device",
            "The node was low on resource: ephemeral-storage. Container {service} was using "
            "18Gi, which exceeds its request of 0",
            "DEBUG dumping full request payload (size=48213 bytes)",
        ),
        anomalies={
            "disk_used_pct": Anomaly(58, 97, "%"),
            "pod_evictions": Anomaly(0, 5, "count"),
            "log_bytes_per_sec": Anomaly(20000, 2400000, "bytes/s"),
        },
        change=(ChangeType.CONFIG, "Set LOG_LEVEL=DEBUG while investigating a billing bug"),
        change_offset_min=180,
        root_cause=(
            "Debug logging was left enabled after an investigation. The service wrote full "
            "request payloads to local log files, filled the node's ephemeral storage and "
            "triggered kubelet evictions."
        ),
        remediation=(
            "Set LOG_LEVEL back to INFO, clear the oversized log files, set ephemeral-storage "
            "requests and limits, and log to stdout with rotation."
        ),
        severities=(S2, S2, S3),
        tags=("disk", "kubernetes", "logging", "eviction"),
    ),
    Scenario(
        category="dependency_timeout",
        runbook_ids=("dependency-timeout", "latency-spike"),
        services=("shipping-service", "checkout-api", "orders-service"),
        title="{service} requests timing out on downstream dependency",
        description=(
            "{service} requests are slow and timing out. Threads are blocked waiting on the "
            "third party shipping rates provider."
        ),
        symptoms=(
            "p99 latency above 10 seconds",
            "request threads blocked on outbound HTTP calls",
            "circuit breaker opening and closing repeatedly",
        ),
        error_messages=(
            "Timeout calling shipping-rates-provider after 10000ms",
            "CircuitBreaker 'shipping-rates' is OPEN and does not permit further calls",
        ),
        log_errors=(
            "Timeout calling shipping-rates-provider after 10000ms",
            "CircuitBreaker 'shipping-rates' is OPEN and does not permit further calls",
            "outbound pool exhausted: 200/200 connections to rates.shipping-provider.example",
        ),
        anomalies={
            "p99_latency_ms": Anomaly(220, 10400, "ms"),
            "error_rate_pct": Anomaly(0.4, 12.0, "%"),
            "dependency_p99_ms": Anomaly(300, 11800, "ms"),
        },
        root_cause=(
            "The third party shipping rates provider degraded to over 10 seconds p99. The "
            "service had no tight timeout or fallback, so request threads blocked on the "
            "provider and latency cascaded to callers."
        ),
        remediation=(
            "Cut the provider timeout to 2 seconds, serve cached rates as a fallback, tune the "
            "circuit breaker, and open a ticket with the provider."
        ),
        severities=(S2, S2, S3),
        tags=("dependency", "timeout", "circuit-breaker", "latency"),
    ),
    Scenario(
        category="slow_query_latency",
        runbook_ids=("latency-spike",),
        services=("search-api", "inventory-service", "user-profile-service"),
        title="Latency spike on {service} listing endpoints",
        description=(
            "Listing endpoints on {service} slowed from about 100ms to several seconds after a "
            "feature release. Database CPU is high."
        ),
        symptoms=(
            "listing endpoint p99 above 3 seconds",
            "database CPU above 90%",
            "slow query log full of sequential scans",
        ),
        error_messages=("slow query: Seq Scan on products (rows=41234001) took 3120ms",),
        log_errors=(
            "slow query: Seq Scan on products (rows=41234001) took 3120ms",
            "GET /api/v1/products?region=eu-west 200 duration=3350ms",
        ),
        anomalies={
            "p99_latency_ms": Anomaly(110, 3400, "ms"),
            "db_cpu_pct": Anomaly(35, 94, "%"),
        },
        change=(ChangeType.DEPLOYMENT, "Add region filter to product listing API"),
        change_offset_min=30,
        root_cause=(
            "The new region filter queries products.region, which has no index, so every "
            "listing request runs a sequential scan over a 40M row table."
        ),
        remediation=(
            "Create an index on products.region with CREATE INDEX CONCURRENTLY, or disable the "
            "region filter until the index exists. Add EXPLAIN checks to query reviews."
        ),
        severities=(S2, S3, S3),
        tags=("latency", "database", "index", "query-plan"),
    ),
    Scenario(
        category="failed_db_migration",
        runbook_ids=("database-migration-failure", "deployment-rollback"),
        services=("billing-service", "orders-service", "user-profile-service"),
        title="{service} errors after failed schema migration",
        description=(
            "{service} is failing requests with missing column errors. The schema migration in "
            "the latest release did not complete but the application was rolled out."
        ),
        symptoms=(
            "SQL errors referencing a missing column",
            "migration job exited with a lock timeout",
            "new application version running on all pods",
        ),
        error_messages=(
            'ERROR: column "discount_code" does not exist',
            "migration 0042_add_discount_code failed: canceling statement due to lock timeout",
        ),
        log_errors=(
            'ERROR: column "discount_code" does not exist at character 58',
            "migration 0042_add_discount_code failed: canceling statement due to lock timeout",
            "POST /api/v1/invoices 500 Internal Server Error",
        ),
        anomalies={
            "error_rate_pct": Anomaly(0.3, 24.0, "%"),
        },
        change=(ChangeType.DEPLOYMENT, "Add discount codes to invoices (migration 0042)"),
        change_offset_min=15,
        root_cause=(
            "Schema migration 0042 failed on a lock timeout, but the deploy pipeline did not "
            "gate on migration success. The new version expects the discount_code column, "
            "which does not exist."
        ),
        remediation=(
            "Roll back the application to the previous version, rerun migration 0042 with a "
            "lock_timeout during low traffic, and make the pipeline block rollout when a "
            "migration fails."
        ),
        severities=(S1, S2, S2),
        tags=("database", "migration", "deployment", "schema"),
    ),
    Scenario(
        category="broken_feature_flag",
        runbook_ids=("feature-flag-rollback", "api-5xx-spike"),
        services=("checkout-api", "search-api", "payments-service"),
        title="{service} failures after feature flag change",
        description=(
            "{service} started failing requests for non-USD customers after a feature flag "
            "was ramped to 100%."
        ),
        symptoms=(
            "errors only for non-USD currencies",
            "failures started when a flag was changed",
            "no deployment in the window",
        ),
        error_messages=("PricingEngineV2: KeyError 'currency_rounding' for currency EUR",),
        log_errors=(
            "PricingEngineV2: KeyError 'currency_rounding' for currency EUR",
            "flag new-pricing-engine evaluated true for 100% of requests",
            "POST /api/v1/quote 500 Internal Server Error",
        ),
        anomalies={
            "error_rate_pct": Anomaly(0.3, 21.0, "%"),
        },
        change=(
            ChangeType.FEATURE_FLAG,
            "Ramped feature flag new-pricing-engine from 5% to 100%",
        ),
        change_offset_min=10,
        root_cause=(
            "Ramping new-pricing-engine to 100% exposed a code path that has no rounding "
            "configuration for non-USD currencies, so those requests fail."
        ),
        remediation=(
            "Turn the new-pricing-engine flag off, add the missing currency rounding "
            "configuration, and ramp again gradually with error rate guards."
        ),
        severities=(S1, S2, S2),
        tags=("feature-flag", "5xx", "config"),
    ),
    Scenario(
        category="load_balancer_misconfiguration",
        runbook_ids=("load-balancer-misconfiguration",),
        services=("api-gateway", "checkout-api", "search-api"),
        title="{service} returning 502 from load balancer",
        description=(
            "The load balancer in front of {service} is returning 502 and 503. Pods are running "
            "and healthy from inside the cluster."
        ),
        symptoms=(
            "load balancer 502 and 503 responses",
            "target group reports no healthy targets",
            "pods healthy when checked directly",
        ),
        error_messages=(
            "502 Bad Gateway",
            "Target group {service}-tg has no healthy targets",
        ),
        log_errors=(
            "ELB health check GET /healthz 404 Not Found",
            "Target group {service}-tg has no healthy targets",
            "502 Bad Gateway returned to client",
        ),
        anomalies={
            "error_rate_pct": Anomaly(0.1, 64.0, "%"),
            "healthy_targets": Anomaly(6, 0, "count", hard_limit=True),
        },
        change=(
            ChangeType.INFRASTRUCTURE,
            "Terraform change updated target group health check path to /healthz",
        ),
        change_offset_min=8,
        root_cause=(
            "A Terraform change set the target group health check path to /healthz, but the "
            "service serves /health. Every target fails its health check and the load balancer "
            "has nothing to route to."
        ),
        remediation=(
            "Revert the health check path to /health through Terraform and add a plan check "
            "that validates health check paths against the service."
        ),
        severities=(S1, S1, S2),
        tags=("load-balancer", "health-check", "terraform", "networking"),
    ),
    Scenario(
        category="secret_rotation_failure",
        runbook_ids=("secret-rotation-failure",),
        services=("payments-service", "billing-service", "notification-worker"),
        title="{service} cannot authenticate to database after credential rotation",
        description=(
            "New database connections from {service} fail with password authentication "
            "errors. Existing connections still work."
        ),
        symptoms=(
            "new database connections failing authentication",
            "errors started right after a scheduled credential rotation",
            "existing pooled connections keep working",
        ),
        error_messages=('FATAL: password authentication failed for user "{service}_app"',),
        log_errors=(
            'FATAL: password authentication failed for user "{service}_app"',
            "credentials loaded from /var/run/secrets/db at startup 6d ago",
            "unable to open new connection; pool size shrinking",
        ),
        anomalies={
            "error_rate_pct": Anomaly(0.2, 15.0, "%"),
            "db_auth_failures_per_min": Anomaly(0, 420, "count"),
        },
        change=(
            ChangeType.SECRET_ROTATION,
            "Automated rotation of database credentials in Secrets Manager",
        ),
        change_offset_min=20,
        root_cause=(
            "Secrets Manager rotated the database password, but {service} reads credentials "
            "only at startup. New connections still use the old password and fail."
        ),
        remediation=(
            "Do a rolling restart of {service} so it loads the new secret, then add secret "
            "reloading or a dual-credential rotation strategy."
        ),
        severities=(S1, S2, S2),
        tags=("secrets", "rotation", "database", "credentials"),
    ),
    Scenario(
        category="iam_permission_regression",
        runbook_ids=("iam-permission-issue",),
        services=("notification-worker", "analytics-consumer", "billing-service"),
        title="{service} getting AccessDenied from AWS",
        description=(
            "{service} is failing to write to S3 with AccessDenied after an IAM change was applied."
        ),
        symptoms=(
            "AccessDenied on s3:PutObject",
            "failures started after an IAM Terraform apply",
            "reads still succeed",
        ),
        error_messages=(
            "AccessDenied: assumed-role/{service}-role is not authorized to perform: s3:PutObject",
        ),
        log_errors=(
            "AccessDenied: User arn:aws:sts::123456789012:assumed-role/{service}-role/task is "
            "not authorized to perform: s3:PutObject",
            "failed to upload batch to s3://sentinel-{service}-output after 3 retries",
        ),
        anomalies={
            "error_rate_pct": Anomaly(0.1, 38.0, "%"),
            "s3_put_errors_per_min": Anomaly(0, 260, "count"),
        },
        change=(
            ChangeType.INFRASTRUCTURE,
            "Terraform refactor consolidated IAM policies for data services",
        ),
        change_offset_min=35,
        root_cause=(
            "An IAM Terraform refactor dropped the s3:PutObject statement from the {service} "
            "role, so every upload is denied."
        ),
        remediation=(
            "Restore the s3:PutObject statement on the role, reapply Terraform, and add policy "
            "tests or IAM Access Analyzer checks to the pipeline."
        ),
        severities=(S2, S2, S3),
        tags=("iam", "aws", "permissions", "s3"),
    ),
    Scenario(
        category="queue_backlog",
        runbook_ids=("queue-backlog",),
        services=("notification-worker", "shipping-service", "billing-service"),
        title="Queue backlog growing for {service}",
        description=(
            "The SQS queue consumed by {service} has grown past 150k messages. Workers are "
            "running but throughput is near zero."
        ),
        symptoms=(
            "queue depth above 150k and climbing",
            "the same message id failing repeatedly",
            "worker throughput near zero",
        ),
        error_messages=(
            "Failed to process message: JSONDecodeError: Expecting value: line 1 column 1",
        ),
        log_errors=(
            "Failed to process message 7f3c2a19: JSONDecodeError: Expecting value: line 1 column 1",
            "message 7f3c2a19 received 214 times; no dead letter queue configured",
            "visibility timeout expired, message returned to queue",
        ),
        anomalies={
            "queue_depth": Anomaly(50, 180000, "messages"),
            "messages_processed_per_sec": Anomaly(140, 3, "msgs/s"),
        },
        root_cause=(
            "A malformed poison message fails processing and is redelivered forever. The queue "
            "has no dead letter queue, so it blocks the workers and the backlog grows."
        ),
        remediation=(
            "Move the poison message aside, configure a dead letter queue with maxReceiveCount "
            "of 5, and make the worker skip unparseable payloads."
        ),
        severities=(S2, S3, S2),
        tags=("queue", "sqs", "backlog", "poison-message"),
    ),
    Scenario(
        category="container_crash_loop",
        runbook_ids=("container-crash-loop",),
        services=("inventory-service", "auth-service", "shipping-service"),
        title="{service} in CrashLoopBackOff after config change",
        description=(
            "All new {service} pods exit within seconds of starting and are in CrashLoopBackOff. "
            "Old pods are still serving."
        ),
        symptoms=(
            "pods in CrashLoopBackOff",
            "container exits with code 1 within 3 seconds",
            "only pods started after a config change are affected",
        ),
        error_messages=(
            "panic: missing required environment variable DATABASE_URL",
            "Back-off restarting failed container",
        ),
        log_errors=(
            "panic: missing required environment variable DATABASE_URL",
            "Back-off restarting failed container {service} in pod {pod}",
            "configmap {service}-config keys: DB_CONNECTION_URL, LOG_LEVEL, PORT",
        ),
        anomalies={
            "pod_restarts": Anomaly(0, 24, "count"),
            "available_replicas": Anomaly(3, 1, "count", hard_limit=True),
        },
        change=(
            ChangeType.CONFIG,
            "ConfigMap cleanup renamed DATABASE_URL to DB_CONNECTION_URL",
        ),
        change_offset_min=10,
        root_cause=(
            "A ConfigMap cleanup renamed DATABASE_URL to DB_CONNECTION_URL. The service "
            "requires DATABASE_URL, so new containers panic on startup and crash loop."
        ),
        remediation=(
            "Restore the DATABASE_URL key in the ConfigMap and restart the rollout, then "
            "validate required keys in CI."
        ),
        severities=(S2, S1, S2),
        tags=("kubernetes", "crashloop", "config", "configmap"),
    ),
    Scenario(
        category="autoscaling_misconfiguration",
        runbook_ids=("autoscaling-misconfiguration", "latency-spike"),
        services=("checkout-api", "search-api", "api-gateway"),
        title="{service} saturated during peak traffic, HPA not scaling",
        description=(
            "During the daily traffic peak {service} CPU is saturated and latency is high. The "
            "HorizontalPodAutoscaler is pinned at its maximum replica count."
        ),
        symptoms=(
            "CPU above 95% on every pod",
            "HPA at maxReplicas",
            "latency rising with traffic",
        ),
        error_messages=("HPA {service}: desired replicas 14 exceeds maxReplicas 4",),
        log_errors=(
            "HPA {service}: desired replicas 14 exceeds maxReplicas 4",
            "request queue length 380 exceeds threshold",
        ),
        anomalies={
            "cpu_pct": Anomaly(40, 97, "%"),
            "p99_latency_ms": Anomaly(150, 2600, "ms"),
            "replica_count": Anomaly(4, 4, "count", hard_limit=True),
            "requests_per_sec": Anomaly(500, 1400, "req/s"),
        },
        change=(ChangeType.CONFIG, "HPA maxReplicas lowered from 20 to 4"),
        change_offset_min=240,
        root_cause=(
            "HPA maxReplicas was lowered from 20 to 4, so {service} could not scale out for "
            "peak traffic. Pods saturate on CPU and latency climbs."
        ),
        remediation=(
            "Restore maxReplicas to 20, and alert when an HPA sits at maxReplicas for more "
            "than 10 minutes."
        ),
        severities=(S2, S2, S2),
        tags=("autoscaling", "hpa", "kubernetes", "capacity"),
    ),
]
