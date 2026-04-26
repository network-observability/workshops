"""Tiny Alertmanager HTTP client — silences + active alerts."""
from __future__ import annotations

import datetime as dt
from typing import Any

import requests


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _rfc3339(ts: dt.datetime) -> str:
    return ts.isoformat(timespec="seconds").replace("+00:00", "Z")


class AlertmanagerClient:
    def __init__(self, base_url: str, timeout: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def alerts(self, active: bool = True, silenced: bool = True, inhibited: bool = True) -> list[dict]:
        """Return AM /api/v2/alerts (richer than Prom's /api/v1/alerts)."""
        r = requests.get(
            f"{self.base_url}/api/v2/alerts",
            params={
                "active": str(active).lower(),
                "silenced": str(silenced).lower(),
                "inhibited": str(inhibited).lower(),
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    def create_silence(
        self,
        matchers: list[dict[str, Any]],
        minutes: int = 20,
        created_by: str = "nobs",
        comment: str = "Quarantine via nobs",
    ) -> str:
        starts = _now_utc()
        ends = starts + dt.timedelta(minutes=minutes)
        r = requests.post(
            f"{self.base_url}/api/v2/silences",
            json={
                "matchers": matchers,
                "startsAt": _rfc3339(starts),
                "endsAt": _rfc3339(ends),
                "createdBy": created_by,
                "comment": comment,
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json().get("silenceID", "")
