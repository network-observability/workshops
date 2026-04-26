"""Tiny Loki HTTP client — query_range + push (annotations)."""
from __future__ import annotations

import datetime as dt
import time

import requests


class LokiClient:
    def __init__(self, base_url: str, timeout: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def query_range(self, query: str, minutes: int = 10, limit: int = 200) -> list[str]:
        end = dt.datetime.now(dt.timezone.utc)
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
        ts = str(time.time_ns())
        r = requests.post(
            f"{self.base_url}/loki/api/v1/push",
            json={"streams": [{"stream": labels, "values": [[ts, message]]}]},
            timeout=self.timeout,
        )
        r.raise_for_status()
