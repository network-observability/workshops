"""Loki HTTP client — query_range + annotate (via sonda /events)."""
from __future__ import annotations

import datetime as dt
import os

import requests

# Sonda's severity enum: trace|debug|info|warn|error|fatal. Loki / syslog
# vocab is broader; map the common spellings down so callers can pass the
# Loki-side label value (e.g. `level=warning`) and we do the right thing.
_SEVERITY_MAP = {
    "warning": "warn",
    "notice": "info",
    "critical": "error",
    "alert": "fatal",
    "emergency": "fatal",
}
_SEVERITY_VALID = {"trace", "debug", "info", "warn", "error", "fatal"}


def _to_sonda_severity(level: str) -> str:
    s = level.lower().strip()
    if s in _SEVERITY_VALID:
        return s
    return _SEVERITY_MAP.get(s, "info")


class LokiClient:
    def __init__(
        self,
        base_url: str,
        timeout: int = 10,
        sonda_url: str | None = None,
        sonda_api_key: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Default targets host-mapped sonda-server (workshop CLI runs on host).
        # In-container callers (Prefect flows) get the right value from
        # SONDA_SERVER_URL env, set explicitly in compose.
        self.sonda_url = (sonda_url or os.environ.get("SONDA_SERVER_URL", "http://localhost:8085")).rstrip("/")
        self.sonda_api_key = sonda_api_key or os.environ.get("SONDA_API_KEY") or None
        # `base_url` is the URL the *caller* uses to query Loki directly (host
        # or container). The URL sonda's /events handler uses to forward the
        # event is different — it's always sonda's container-network view of
        # Loki, which is `http://loki:3001` in this compose. Splitting the two
        # avoids the host-vs-container DNS mismatch.
        self.sonda_loki_sink_url = os.environ.get("SONDA_LOKI_SINK_URL", "http://loki:3001").rstrip("/")

    def query_range(self, query: str, minutes: int = 10, limit: int = 200) -> list[str]:
        end = dt.datetime.now(dt.UTC)
        start = end - dt.timedelta(minutes=minutes)
        r = requests.get(
            f"{self.base_url}/loki/api/v1/query_range",
            params={
                "query": query,
                "start": int(start.timestamp() * 1e9),
                "end": int(end.timestamp() * 1e9),
                "limit": limit,
                "direction": "BACKWARD",
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        out: list[str] = []
        for stream in r.json().get("data", {}).get("result", []):
            for _, line in stream.get("values", []):
                out.append(line)
        return out[:limit]

    def query_count(self, query: str, minutes: int = 5) -> int:
        return len(self.query_range(query, minutes=minutes, limit=1000))

    def annotate(self, labels: dict[str, str], message: str) -> None:
        # Routes through sonda's POST /events. Sonda forwards to the Loki sink
        # we point it at — same destination as the legacy direct push, but
        # observable + auth-gated at sonda's edge instead of going around it.
        headers = {"Authorization": f"Bearer {self.sonda_api_key}"} if self.sonda_api_key else {}
        payload = {
            "signal_type": "logs",
            "labels": labels,
            "log": {
                "severity": _to_sonda_severity(labels.get("level", "info")),
                "message": message,
                "fields": {},
            },
            "encoder": {"type": "json_lines"},
            "sink": {"type": "loki", "url": self.sonda_loki_sink_url},
        }
        r = requests.post(
            f"{self.sonda_url}/events", json=payload, headers=headers, timeout=self.timeout,
        )
        r.raise_for_status()
