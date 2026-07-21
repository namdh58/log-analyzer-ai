"""Deterministic tests against the live Phase-1 infra (services are already running).

Uses a real trace_id captured in tests/fixtures/ (same checkout request that produced
logs_sample.json / trace_sample.json), so expected values are concrete, not guessed.
"""
import time

from retrieval.log_client import LogClient
from retrieval.metric_client import RESOURCE_SERVICES, MetricClient
from retrieval.trace_client import TraceClient

FIXTURE_TRACE_ID = "aa0a3d4773fc332d7590ef1d79c5937a"


def test_log_client_returns_sorted_masked_logs_for_real_trace():
    logs = LogClient().get_logs_by_trace_id(FIXTURE_TRACE_ID)
    assert len(logs) > 0
    timestamps = [entry.timestamp for entry in logs]
    assert timestamps == sorted(timestamps)
    services = {entry.service for entry in logs}
    assert "checkout" in services
    assert "payment" in services
    for entry in logs:
        assert entry.service
        assert entry.level
        assert entry.trace_id == FIXTURE_TRACE_ID
        assert "@" not in entry.message  # email would have been masked
        assert "4432801561520454" not in entry.message  # card number masked


def test_trace_client_builds_correct_span_tree():
    root = TraceClient().get_trace(FIXTURE_TRACE_ID)
    assert root is not None
    assert root.trace_id == FIXTURE_TRACE_ID
    assert root.duration_ms > 0

    def flatten(node):
        yield node
        for child in node.children:
            yield from flatten(child)

    services = {n.service for n in flatten(root)}
    for expected in ("frontend", "checkout", "payment", "shipping", "currency"):
        assert expected in services, f"{expected} missing from span tree services={services}"

    checkout_nodes = [n for n in flatten(root) if n.service == "checkout"]
    assert checkout_nodes
    checkout_children_services = {
        child.service for node in checkout_nodes for child in node.children
    }
    assert "payment" in checkout_children_services


def test_metric_client_returns_real_numbers():
    end = time.time()
    # Real checkout traffic in this env is sparse (~0.3-0.4 req/s, verified empirically) --
    # a 5 min window can land on zero checkout calls by chance, so use a wider one.
    start = end - 900
    client = MetricClient()

    p95 = client.get_latency_p95("checkout", start, end)
    assert isinstance(p95, list)
    assert len(p95) > 0
    assert all(v >= 0 for v in p95)

    error_rate = client.get_error_rate("payment", start, end)
    assert 0.0 <= error_rate <= 1.0

    request_rate = client.get_request_rate("checkout", start, end)
    assert request_rate >= 0


def test_resource_summary_returns_real_per_service_numbers():
    end = time.time()
    start = end - 900
    client = MetricClient()

    cpu = client.get_cpu_usage("ad", start, end)
    assert cpu["avg_pct"] is not None and cpu["avg_pct"] >= 0
    assert cpu["peak_pct"] >= cpu["avg_pct"]

    mem = client.get_memory_usage("ad", start, end)
    assert mem["avg_pct"] is not None and 0 <= mem["avg_pct"] <= 100
    assert mem["limit_bytes"] == 314572800  # `ad`'s configured 300MiB deploy.resources.limits.memory
    assert 0 < mem["used_bytes"] < mem["limit_bytes"]

    rows = client.get_resource_summary(start, end)
    assert len(rows) == len(RESOURCE_SERVICES)
    by_service = {r["service"]: r for r in rows}
    assert "payment" in by_service and "checkout" in by_service
    for row in rows:
        assert row["memory"]["avg_pct"] is not None, f"{row['service']} missing memory data"
        assert row["cpu"]["avg_pct"] is not None, f"{row['service']} missing cpu data"
