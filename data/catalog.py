from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceProfile:
    name: str
    namespace: str
    team: str
    replicas: int
    baseline_rps: float
    baseline_p99_ms: float
    baseline_cpu_pct: float
    baseline_memory_pct: float
    dependencies: tuple[str, ...]


SERVICES: dict[str, ServiceProfile] = {
    s.name: s
    for s in [
        ServiceProfile(
            "checkout-api",
            "commerce",
            "checkout",
            6,
            420,
            180,
            38,
            52,
            ("payments-service", "orders-service", "postgres-checkout", "redis-cache"),
        ),
        ServiceProfile(
            "payments-service",
            "commerce",
            "payments",
            4,
            260,
            210,
            34,
            48,
            ("postgres-payments", "stripe-gateway", "auth-service"),
        ),
        ServiceProfile(
            "orders-service",
            "commerce",
            "orders",
            4,
            310,
            160,
            41,
            55,
            ("postgres-orders", "kafka", "inventory-service"),
        ),
        ServiceProfile(
            "auth-service",
            "identity",
            "identity",
            3,
            900,
            60,
            29,
            40,
            ("postgres-identity", "redis-sessions", "idp-jwks"),
        ),
        ServiceProfile(
            "inventory-service",
            "commerce",
            "inventory",
            3,
            180,
            140,
            33,
            50,
            ("postgres-inventory", "kafka"),
        ),
        ServiceProfile(
            "notification-worker",
            "messaging",
            "messaging",
            2,
            75,
            450,
            22,
            44,
            ("sqs-notifications", "ses", "kafka"),
        ),
        ServiceProfile(
            "search-api",
            "discovery",
            "search",
            5,
            650,
            120,
            45,
            58,
            ("elasticsearch-products", "redis-cache"),
        ),
        ServiceProfile(
            "user-profile-service",
            "identity",
            "identity",
            3,
            220,
            90,
            27,
            46,
            ("postgres-identity", "redis-cache", "s3-avatars"),
        ),
        ServiceProfile(
            "api-gateway",
            "edge",
            "platform",
            6,
            2400,
            40,
            36,
            42,
            ("checkout-api", "search-api", "auth-service", "coredns"),
        ),
        ServiceProfile(
            "analytics-consumer",
            "data",
            "data-platform",
            3,
            1200,
            300,
            52,
            61,
            ("kafka", "s3-datalake"),
        ),
        ServiceProfile(
            "billing-service",
            "finance",
            "billing",
            2,
            90,
            250,
            30,
            47,
            ("postgres-billing", "kafka", "s3-invoices"),
        ),
        ServiceProfile(
            "shipping-service",
            "commerce",
            "fulfillment",
            3,
            140,
            220,
            31,
            45,
            ("shipping-rates-provider", "postgres-orders", "sqs-shipments"),
        ),
    ]
}
