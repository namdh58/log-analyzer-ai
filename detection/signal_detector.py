"""Pure Python signal detection over retrieval-layer data. No LLM calls here."""
import re
from pathlib import Path

import yaml
from pydantic import BaseModel

from retrieval.log_client import LogClient
from retrieval.metric_client import RESOURCE_SERVICES, MetricClient
from retrieval.trace_client import TraceClient

_DIR = Path(__file__).parent
_ACCESS_LOG_RE = re.compile(r'"(?:GET|POST|PUT|DELETE|PATCH) (\S+) HTTP/[\d.]+" (\d{3})')


class Signal(BaseModel):
    signal_type: str  # latency_spike | error_rate_spike | span_gap | queue_anomaly | throughput_drop | cpu_high | memory_high
    confidence: float
    affected_services: list[str]
    affected_trace_ids: list[str] = []
    metric_values: dict = {}
    window: tuple[float, float]


def _flatten(node):
    yield node
    for child in node.children:
        yield from _flatten(child)


class SignalDetector:
    def __init__(
        self,
        config_path: Path = _DIR / "config.yaml",
        service_map_path: Path = _DIR / "service_map.yaml",
        metric_client: MetricClient | None = None,
        trace_client: TraceClient | None = None,
    ):
        self.config = yaml.safe_load(Path(config_path).read_text())
        self.service_map = yaml.safe_load(Path(service_map_path).read_text())
        self.metrics = metric_client or MetricClient()
        self.traces = trace_client or TraceClient()
        self.logs = LogClient()

    def detect(self, start: float, end: float) -> list[Signal]:
        signals = []
        signals += self._check_latency_spike(start, end)
        signals += self._check_error_rate_spike(start, end)
        signals += self._check_checkout_http_error_rate(start, end)
        signals += self._check_span_gap(start, end)
        signals += self._check_queue_anomaly(start, end)
        signals += self._check_throughput_drop(start, end)
        signals += self._check_cpu_high(start, end)
        signals += self._check_memory_high(start, end)
        return signals

    def _example_traces(self, start, end, service):
        try:
            return self.traces.search_traces(start, end, service=service, limit=5)
        except Exception:
            return []

    def _check_latency_spike(self, start, end) -> list[Signal]:
        threshold = self.config["latency_spike"]["baseline_multiplier"]
        signals = []
        for service in self.config["services"]:
            baseline = self.metrics.get_baseline(service, "get_latency_p95", before=start)
            current_values = self.metrics.get_latency_p95(service, start, end)
            # Require >=2 samples so a single noisy 15s histogram_quantile bucket (common
            # on low-traffic services like `ad`/`shipping`) can't fire alone -- a real
            # overload scenario stays elevated for its whole duration, not one sample.
            if baseline <= 0 or len(current_values) < 2:
                continue
            current = sum(current_values) / len(current_values)
            if current < self.config["latency_spike"]["min_absolute_ms"]:
                continue
            if current > baseline * threshold:
                signals.append(
                    Signal(
                        signal_type="latency_spike",
                        confidence=min(1.0, current / (baseline * threshold)),
                        affected_services=[service],
                        affected_trace_ids=self._example_traces(start, end, service),
                        metric_values={"current_p95_ms": current, "baseline_p95_ms": baseline},
                        window=(start, end),
                    )
                )
        return signals

    def _check_error_rate_spike(self, start, end) -> list[Signal]:
        cfg = self.config["error_rate_spike"]
        signals = []
        for service in self.config["services"]:
            current = self.metrics.get_error_rate(service, start, end)
            baseline = self.metrics.get_baseline(service, "get_error_rate", before=start)
            fires_absolute = current > cfg["absolute_floor"]
            fires_relative = baseline > 0 and current > baseline * cfg["baseline_multiplier"]
            if fires_absolute or fires_relative:
                floor = max(cfg["absolute_floor"], baseline * cfg["baseline_multiplier"])
                signals.append(
                    Signal(
                        signal_type="error_rate_spike",
                        confidence=min(1.0, current / floor) if floor else 1.0,
                        affected_services=[service],
                        affected_trace_ids=self._example_traces(start, end, service),
                        metric_values={"current_error_rate": current, "baseline_error_rate": baseline},
                        window=(start, end),
                    )
                )
        return signals

    def _check_checkout_http_error_rate(self, start, end) -> list[Signal]:
        """payment_failure / payment_outage: the payment span itself stays STATUS_CODE_OK
        (verified in Phase 1), so the only place the failure is visible is the HTTP 5xx
        frontend-proxy returns for /api/checkout. Parsed from the envoy access log line
        (see PROGRESS.md verified fact on frontend-proxy log format).
        """
        cfg = self.config["error_rate_spike"]
        entries = self.logs.get_logs_by_time_range(start, end, service="frontend-proxy")
        total = errors = 0
        for entry in entries:
            match = _ACCESS_LOG_RE.search(entry.message)
            if not match or match.group(1) != "/api/checkout":
                continue
            total += 1
            if int(match.group(2)) >= 500:
                errors += 1
        if total == 0:
            return []
        error_rate = errors / total
        if error_rate <= cfg["absolute_floor"]:
            return []
        return [
            Signal(
                signal_type="error_rate_spike",
                confidence=min(1.0, error_rate / cfg["absolute_floor"]),
                affected_services=["payment"],
                affected_trace_ids=self._example_traces(start, end, "payment"),
                metric_values={
                    "checkout_http_error_rate": error_rate,
                    "checkout_http_requests": total,
                    "checkout_http_5xx": errors,
                },
                window=(start, end),
            )
        ]

    def _check_throughput_drop(self, start, end) -> list[Signal]:
        cfg = self.config["throughput_drop"]
        ratio_threshold = cfg["baseline_ratio"]
        signals = []
        for service in self.config["services"]:
            baseline = self.metrics.get_baseline(service, "get_request_rate", before=start)
            current = self.metrics.get_request_rate(service, start, end)
            if baseline < cfg["min_absolute_baseline_rate"]:
                continue
            ratio = current / baseline
            if ratio < ratio_threshold:
                signals.append(
                    Signal(
                        signal_type="throughput_drop",
                        confidence=min(1.0, (1 - ratio) / (1 - ratio_threshold)),
                        affected_services=[service],
                        affected_trace_ids=self._example_traces(start, end, service),
                        metric_values={"current_rate": current, "baseline_rate": baseline},
                        window=(start, end),
                    )
                )
        return signals

    def _check_queue_anomaly(self, start, end) -> list[Signal]:
        cfg = self.config["queue_anomaly"]
        publish = self.metrics.get_kafka_publish_rate(start, end)
        consume = self.metrics.get_kafka_consume_rate(start, end)
        baseline_publish = self.metrics.get_baseline(None, "get_kafka_publish_rate", before=start)

        if not (baseline_publish > 0 and publish > baseline_publish * cfg["publish_baseline_multiplier"]):
            return []
        denom = baseline_publish * cfg["publish_baseline_multiplier"]
        return [
            Signal(
                signal_type="queue_anomaly",
                confidence=min(1.0, publish / denom),
                affected_services=["checkout", "kafka"],
                affected_trace_ids=self._example_traces(start, end, "checkout"),
                metric_values={
                    "publish_rate": publish,
                    "consume_rate": consume,
                    "baseline_publish_rate": baseline_publish,
                },
                window=(start, end),
            )
        ]

    def _check_cpu_high(self, start, end) -> list[Signal]:
        threshold = self.config["cpu_high"]["threshold_pct"]
        signals = []
        for service in RESOURCE_SERVICES:
            usage = self.metrics.get_cpu_usage(service, start, end)
            avg = usage["avg_pct"]
            if avg is None or avg <= threshold:
                continue
            signals.append(
                Signal(
                    signal_type="cpu_high",
                    confidence=min(1.0, avg / threshold),
                    affected_services=[service],
                    affected_trace_ids=self._example_traces(start, end, service),
                    metric_values={"avg_cpu_pct": avg, "peak_cpu_pct": usage["peak_pct"]},
                    window=(start, end),
                )
            )
        return signals

    def _check_memory_high(self, start, end) -> list[Signal]:
        threshold = self.config["memory_high"]["threshold_pct"]
        signals = []
        for service in RESOURCE_SERVICES:
            usage = self.metrics.get_memory_usage(service, start, end)
            avg = usage["avg_pct"]
            if avg is None or avg <= threshold:
                continue
            signals.append(
                Signal(
                    signal_type="memory_high",
                    confidence=min(1.0, avg / threshold),
                    affected_services=[service],
                    affected_trace_ids=self._example_traces(start, end, service),
                    metric_values={
                        "avg_memory_pct": avg,
                        "peak_memory_pct": usage["peak_pct"],
                        "used_bytes": usage["used_bytes"],
                        "limit_bytes": usage["limit_bytes"],
                    },
                    window=(start, end),
                )
            )
        return signals

    def _check_span_gap(self, start, end) -> list[Signal]:
        signals = []
        for parent, children in self.service_map.items():
            trace_ids = self._example_traces(start, end, parent)
            gapped_trace_ids = []
            missing_overall = set()
            for trace_id in trace_ids:
                root = self.traces.get_trace(trace_id)
                if root is None:
                    continue
                nodes = list(_flatten(root))
                present_services = {n.service for n in nodes}
                present_ops = " ".join(n.operation.lower() for n in nodes)
                missing = []
                for child in children:
                    if child == "kafka":
                        if "publish" not in present_ops:
                            missing.append(child)
                    elif child not in present_services:
                        missing.append(child)
                if missing:
                    gapped_trace_ids.append(trace_id)
                    missing_overall.update(missing)
            if gapped_trace_ids:
                signals.append(
                    Signal(
                        signal_type="span_gap",
                        confidence=0.9,
                        affected_services=[parent, *sorted(missing_overall)],
                        affected_trace_ids=gapped_trace_ids[:5],
                        metric_values={"missing_children": sorted(missing_overall)},
                        window=(start, end),
                    )
                )
        return signals
