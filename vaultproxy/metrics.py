from typing import Any

__all__ = ["METRICS_AVAILABLE", "generate_latest", "record_request_metrics"]

try:
    from prometheus_client import (  # type: ignore[import-not-found]
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    METRICS_AVAILABLE = True

    REQUESTS_TOTAL: Any = Counter(
        "vaultproxy_requests_total", "Total requests processed"
    )
    REQUEST_DURATION: Any = Histogram(
        "vaultproxy_request_duration_seconds", "Request latency in seconds"
    )
    MASKED_ENTITIES_TOTAL: Any = Counter(
        "vaultproxy_masked_entities_total", "Total masked entities across requests"
    )
    DEGRADED_REQUESTS_TOTAL: Any = Counter(
        "vaultproxy_degraded_requests_total",
        "Total requests processed in degraded mode",
    )
    CIRCUIT_BREAKER_STATE: Any = Gauge(
        "vaultproxy_circuit_breaker_state",
        "Circuit breaker status (0=CLOSED, 1=HALF_OPEN, 2=OPEN)",
    )

except ImportError:
    METRICS_AVAILABLE = False
    REQUESTS_TOTAL = None
    REQUEST_DURATION = None
    MASKED_ENTITIES_TOTAL = None
    DEGRADED_REQUESTS_TOTAL = None
    CIRCUIT_BREAKER_STATE = None

    def generate_latest() -> bytes:
        return b""


def record_request_metrics(
    duration_seconds: float, entity_count: int, degraded: bool, cb_state: str
) -> None:
    if not METRICS_AVAILABLE or REQUESTS_TOTAL is None:
        return
    REQUESTS_TOTAL.inc()
    REQUEST_DURATION.observe(duration_seconds)
    if entity_count > 0:
        MASKED_ENTITIES_TOTAL.inc(entity_count)
    if degraded:
        DEGRADED_REQUESTS_TOTAL.inc()

    cb_val = 0
    if cb_state == "HALF_OPEN":
        cb_val = 1
    elif cb_state == "OPEN":
        cb_val = 2
    CIRCUIT_BREAKER_STATE.set(cb_val)
