"""Tempo HTTP API client."""
import base64
import os

import requests

from retrieval.models import SpanNode

TEMPO_URL = os.environ.get("TEMPO_URL", "http://localhost:3200")


def _b64_to_hex(value: str) -> str:
    if not value:
        return ""
    return base64.b64decode(value).hex()


class TraceClient:
    def __init__(self, base_url: str = TEMPO_URL):
        self.base_url = base_url

    def get_trace(self, trace_id: str) -> SpanNode | None:
        resp = requests.get(f"{self.base_url}/api/traces/{trace_id}", timeout=10)
        resp.raise_for_status()
        data = resp.json()

        nodes: dict[str, SpanNode] = {}
        parent_of: dict[str, str] = {}
        for batch in data.get("batches", []):
            service = ""
            for attr in batch.get("resource", {}).get("attributes", []):
                if attr["key"] == "service.name":
                    service = attr["value"].get("stringValue", "")
            for scope_span in batch.get("scopeSpans", []):
                for span in scope_span.get("spans", []):
                    span_id = _b64_to_hex(span["spanId"])
                    parent_span_id = _b64_to_hex(span.get("parentSpanId", ""))
                    start = int(span["startTimeUnixNano"])
                    end = int(span["endTimeUnixNano"])
                    nodes[span_id] = SpanNode(
                        trace_id=trace_id,
                        span_id=span_id,
                        parent_span_id=parent_span_id,
                        service=service,
                        operation=span["name"],
                        start=start,
                        duration_ms=(end - start) / 1e6,
                        status=span.get("status", {}).get("code", "STATUS_CODE_UNSET"),
                    )
                    if parent_span_id:
                        parent_of[span_id] = parent_span_id

        root = None
        for span_id, node in nodes.items():
            parent_id = parent_of.get(span_id, "")
            if parent_id and parent_id in nodes:
                nodes[parent_id].children.append(node)
            elif not parent_id:
                root = node
        return root

    def search_traces(self, start: int, end: int, service: str | None = None, limit: int = 20) -> list[str]:
        params = {"start": int(start), "end": int(end), "limit": limit}
        if service:
            params["tags"] = f"service.name={service}"
        resp = requests.get(f"{self.base_url}/api/search", params=params, timeout=10)
        resp.raise_for_status()
        return [t["traceID"] for t in resp.json().get("traces", [])]
