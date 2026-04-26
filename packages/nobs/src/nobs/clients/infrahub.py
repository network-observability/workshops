"""Tiny Infrahub GraphQL client.

Generic on purpose — workshops layer their schema-specific queries on top
of `query()`. The token is read from `INFRAHUB_API_TOKEN` if not passed
explicitly, which lines up with the rest of the workshop tooling.
"""
from __future__ import annotations

import os
from typing import Any

import requests


class InfrahubClient:
    def __init__(self, base_url: str, token: str | None = None, timeout: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token = token or os.environ.get("INFRAHUB_API_TOKEN", "")

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        r = requests.post(
            f"{self.base_url}/graphql",
            json={"query": query, "variables": variables or {}},
            headers={"Content-Type": "application/json", "X-INFRAHUB-KEY": self._token},
            timeout=self.timeout,
        )
        r.raise_for_status()
        payload = r.json()
        if "errors" in payload:
            raise RuntimeError(f"Infrahub GraphQL error: {payload['errors']}")
        return payload.get("data") or {}
