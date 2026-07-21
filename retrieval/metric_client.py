"""Prometheus HTTP API client."""
import os
import statistics
import time

import requests

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")

# The collector's spanmetrics/kafka export cycle pushes fresh values roughly every 60s
# (verified empirically -- NOT the ~15s originally assumed). A rate() lookback close to
# that cadence frequently contains <2 real samples depending on query alignment and
# silently returns *no data point at all* (not a zero) -- seen intermittently on
# traces_span_metrics_* and reliably on kafka_message_count_total. Windows are widened
# well past 60s so there are always >=2 real samples regardless of alignment.
_RATE_WINDOW = "2m"  # lookback used inside rate(); independent of the caller's [start,end]
_STEP = 15  # seconds between samples in a range query
# kafka_message_count_total needs the same >=60s margin as above; "1m" still returned zero
# samples empirically (verified), and "5m" over-dilutes a real short flood burst down to
# near-baseline. "2m" is the minimum that reliably has data without washing out a spike.
_KAFKA_RATE_WINDOW = "2m"

# App/business containers (excludes observability + infra plumbing: prometheus, grafana,
# tempo, loki, otel-collector, jaeger, flagd, flagd-ui, kafka, postgresql, valkey-cart,
# load-generator, llm). Verified against `docker compose config --services` + real
# container_name labels on container_cpu_utilization_ratio/container_memory_percent_ratio.
RESOURCE_SERVICES = [
    "frontend", "frontend-proxy", "cart", "checkout", "payment", "shipping",
    "currency", "recommendation", "ad", "product-catalog", "accounting",
    "fraud-detection", "email", "quote", "image-provider", "product-reviews",
]


class MetricClient:
    def __init__(self, base_url: str = PROMETHEUS_URL):
        self.base_url = base_url

    def _range_values(self, promql: str, start: float, end: float) -> list[float]:
        # Prometheus range_query needs start < end; widen a same-instant window slightly.
        if end <= start:
            end = start + 1
        resp = requests.get(
            f"{self.base_url}/api/v1/query_range",
            params={"query": promql, "start": start, "end": end, "step": _STEP},
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()["data"]["result"]
        values = []
        for series in result:
            for _, value in series["values"]:
                if value != "NaN":
                    values.append(float(value))
        return values

    def get_latency_p95(self, service: str, start: float, end: float) -> list[float]:
        promql = (
            f'histogram_quantile(0.95, sum by (le) ('
            f'rate(traces_span_metrics_duration_milliseconds_bucket{{service_name="{service}"}}[{_RATE_WINDOW}])))'
        )
        return self._range_values(promql, start, end)

    def get_error_rate(self, service: str, start: float, end: float) -> float:
        total = self._range_values(
            f'sum(rate(traces_span_metrics_calls_total{{service_name="{service}"}}[{_RATE_WINDOW}]))',
            start,
            end,
        )
        if not total or sum(total) == 0:
            return 0.0
        errors = self._range_values(
            f'sum(rate(traces_span_metrics_calls_total'
            f'{{service_name="{service}",status_code="STATUS_CODE_ERROR"}}[{_RATE_WINDOW}]))',
            start,
            end,
        )
        return (sum(errors) / len(errors) if errors else 0.0) / (sum(total) / len(total))

    def get_request_rate(self, service: str, start: float, end: float) -> float:
        values = self._range_values(
            f'sum(rate(traces_span_metrics_calls_total{{service_name="{service}"}}[{_RATE_WINDOW}]))',
            start,
            end,
        )
        return sum(values) / len(values) if values else 0.0

    def get_kafka_publish_rate(self, start: float, end: float) -> float:
        values = self._range_values(f"sum(rate(kafka_message_count_total[{_KAFKA_RATE_WINDOW}]))", start, end)
        return sum(values) / len(values) if values else 0.0

    def get_kafka_consume_rate(self, start: float, end: float) -> float:
        values = self._range_values("sum(kafka_consumer_records_consumed_rate)", start, end)
        return sum(values) / len(values) if values else 0.0

    def get_cpu_usage(self, service: str, start: float, end: float) -> dict:
        # ponytail: no container in this compose has a real CPU quota (verified via
        # `docker inspect` -- NanoCpus=0 on every service), so "% of limit" has no literal
        # meaning for CPU here (unlike memory, which has real deploy.resources.limits).
        # container_cpu_utilization_ratio is % of one host core and can exceed 100 on a
        # multi-core host (verified: `ad` hits ~374% during the adHighCpu scenario). We
        # treat 100 (one core) as a nominal budget so avg_pct/peak_pct stay comparable to
        # memory's real vs-limit numbers. Upgrade: if the compose ever sets real `cpus:`
        # limits, switch this to actual %-of-quota.
        values = self._range_values(f'container_cpu_utilization_ratio{{container_name="{service}"}}', start, end)
        if not values:
            return {"avg_pct": None, "peak_pct": None}
        return {"avg_pct": sum(values) / len(values), "peak_pct": max(values)}

    def get_memory_usage(self, service: str, start: float, end: float) -> dict:
        pct = self._range_values(f'container_memory_percent_ratio{{container_name="{service}"}}', start, end)
        if not pct:
            return {"avg_pct": None, "peak_pct": None, "used_bytes": None, "limit_bytes": None}
        used = self._range_values(f'container_memory_usage_total_bytes{{container_name="{service}"}}', start, end)
        limit = self._range_values(f'container_memory_usage_limit_bytes{{container_name="{service}"}}', start, end)
        return {
            "avg_pct": sum(pct) / len(pct),
            "peak_pct": max(pct),
            "used_bytes": used[-1] if used else None,
            "limit_bytes": limit[-1] if limit else None,
        }

    def get_resource_summary(self, start: float, end: float) -> list[dict]:
        """One row per RESOURCE_SERVICES entry: cpu%, mem%, request_rate, p95 latency,
        error_rate. Never raises -- a missing/unavailable metric for one service degrades
        to None on that field rather than failing the whole summary."""
        rows = []
        for service in RESOURCE_SERVICES:
            row = {"service": service}
            try:
                row["cpu"] = self.get_cpu_usage(service, start, end)
            except Exception:
                row["cpu"] = {"avg_pct": None, "peak_pct": None}
            try:
                row["memory"] = self.get_memory_usage(service, start, end)
            except Exception:
                row["memory"] = {"avg_pct": None, "peak_pct": None, "used_bytes": None, "limit_bytes": None}
            try:
                row["request_rate"] = self.get_request_rate(service, start, end)
            except Exception:
                row["request_rate"] = None
            try:
                p95 = self.get_latency_p95(service, start, end)
                row["p95_latency_ms"] = sum(p95) / len(p95) if p95 else None
            except Exception:
                row["p95_latency_ms"] = None
            try:
                row["error_rate"] = self.get_error_rate(service, start, end)
            except Exception:
                row["error_rate"] = None
            rows.append(row)
        return rows

    def get_baseline(self, service: str, metric: str, before: float | None = None) -> float:
        """Median of `metric` (a getter name on this class) over the 30 min preceding `before`
        (default: now). Median, not mean -- some services (e.g. `ad`) have real periodic
        multi-second GC-pause latency blips every ~10 min (verified: container memory pinned
        at its limit) that would otherwise drag a mean baseline high enough to mask a real
        chaos-induced spike sitting well above the service's *typical* latency.
        """
        before = before if before is not None else time.time()
        start = before - 1800
        getter = getattr(self, metric)
        values = getter(service, start, before) if service else getter(start, before)
        if isinstance(values, list):
            return statistics.median(values) if values else 0.0
        return values
