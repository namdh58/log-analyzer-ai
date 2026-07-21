"""Loki HTTP API client."""
import os
import time

import requests

from retrieval.masking import mask_log_entry
from retrieval.models import LogEntry

LOKI_URL = os.environ.get("LOKI_URL", "http://localhost:3100")


class LogClient:
    def __init__(self, base_url: str = LOKI_URL):
        self.base_url = base_url

    def _query_range(self, query: str, start: float, end: float, limit: int = 1000) -> list[LogEntry]:
        params = {
            "query": query,
            "start": int(start * 1e9),
            "end": int(end * 1e9),
            "limit": limit,
            "direction": "forward",
        }
        resp = requests.get(f"{self.base_url}/loki/api/v1/query_range", params=params, timeout=10)
        resp.raise_for_status()
        entries = []
        for stream in resp.json()["data"]["result"]:
            labels = stream["stream"]
            service = labels.get("service_name", "")
            level = labels.get("detected_level") or labels.get("severity_text") or "unknown"
            for ts, line in stream["values"]:
                entry = LogEntry(
                    timestamp=int(ts),
                    service=service,
                    level=level,
                    message=line,
                    trace_id=labels.get("trace_id", ""),
                    span_id=labels.get("span_id", ""),
                    raw=line,
                )
                entries.append(mask_log_entry(entry))
        entries.sort(key=lambda e: e.timestamp)
        return entries

    def get_logs_by_trace_id(self, trace_id: str) -> list[LogEntry]:
        now = time.time()
        return self._query_range(f'{{service_name=~".+"}} | trace_id="{trace_id}"', now - 86400, now)

    def get_logs_by_time_range(
        self, start: float, end: float, service: str | None = None, levels: list[str] | None = None
    ) -> list[LogEntry]:
        query = f'{{service_name="{service}"}}' if service else '{service_name=~".+"}'
        entries = self._query_range(query, start, end)
        if levels:
            wanted = {level.lower() for level in levels}
            entries = [e for e in entries if e.level.lower() in wanted]
        return entries
