"""Tiny Prometheus HTTP client — instant + range queries, alerts list."""
from __future__ import annotations

import datetime as dt

import requests


class PromClient:
    def __init__(self, base_url: str, timeout: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def instant(self, query: str) -> list[dict]:
        r = requests.get(
            f"{self.base_url}/api/v1/query",
            params={"query": query},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json().get("data", {}).get("result", [])

    def alerts(self) -> list[dict]:
        r = requests.get(f"{self.base_url}/api/v1/alerts", timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("data", {}).get("alerts", [])

    def range(self, query: str, minutes: int = 10, step_seconds: int = 30) -> list[dict]:
        end = dt.datetime.now(dt.timezone.utc)
        start = end - dt.timedelta(minutes=minutes)
        r = requests.get(
            f"{self.base_url}/api/v1/query_range",
            params={
                "query": query,
                "start": start.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "end": end.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "step": str(step_seconds),
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json().get("data", {}).get("result", [])
