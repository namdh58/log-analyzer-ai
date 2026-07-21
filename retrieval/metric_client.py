"""Prometheus HTTP API client."""
import os
import time

import requests

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")

_RATE_WINDOW = "1m"  # lookback used inside rate(); independent of the caller's [start,end]
_STEP = 15  # seconds between samples in a range query


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
        values = self._range_values(f"sum(rate(kafka_message_count_total[{_RATE_WINDOW}]))", start, end)
        return sum(values) / len(values) if values else 0.0

    def get_kafka_consume_rate(self, start: float, end: float) -> float:
        values = self._range_values("sum(kafka_consumer_records_consumed_rate)", start, end)
        return sum(values) / len(values) if values else 0.0

    def get_baseline(self, service: str, metric: str, before: float | None = None) -> float:
        """Mean of `metric` (a getter name on this class) over the 30 min preceding `before` (default: now)."""
        before = before if before is not None else time.time()
        start = before - 1800
        getter = getattr(self, metric)
        values = getter(service, start, before) if service else getter(start, before)
        if isinstance(values, list):
            return sum(values) / len(values) if values else 0.0
        return values
