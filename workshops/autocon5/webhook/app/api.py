"""Alertmanager webhook handler — forwards into the Prefect alert-receiver flow."""
from __future__ import annotations

import logging
from typing import Literal

import fastapi
from prefect.deployments import run_deployment
from pydantic import BaseModel


router = fastapi.APIRouter()
log = logging.getLogger("webhook")


class AlertmanagerAlert(BaseModel):
    status: str
    labels: dict
    annotations: dict
    startsAt: str
    endsAt: str
    generatorURL: str
    fingerprint: str


class AlertmanagerAlertGroup(BaseModel):
    version: str
    groupKey: str
    truncatedAlerts: int
    status: Literal["firing", "resolved"]
    receiver: str
    groupLabels: dict
    commonLabels: dict
    commonAnnotations: dict
    externalURL: str
    alerts: list[AlertmanagerAlert]


@router.post("/v1/api/webhook", status_code=204)
def process_webhook(alert_group: AlertmanagerAlertGroup):
    """Process an Alertmanager webhook, fan out to a Prefect deployment per
    affected (device, peer_address) pair."""
    log.info("Received alertmanager webhook: %s", alert_group.groupKey)

    error = ""
    try:
        status = alert_group.status
        alertname = alert_group.groupLabels.get("alertname", "unknown")

        # Collect a deduplicated set of (device, peer_address) pairs.
        # PeerInterfaceFlapping carries (device, interface) instead — we
        # treat the interface as the "peer" for routing purposes so the same
        # fan-out logic works.
        pairs = set()
        for a in alert_group.alerts:
            d = a.labels.get("device")
            p = a.labels.get("peer_address") or a.labels.get("interface")
            if d and p:
                pairs.add((d, p))

        log.info(
            "Fanning out %d device/target pairs for alert '%s' status='%s'",
            len(pairs), alertname, status,
        )

        for device, target in pairs:
            flow_run_name = f"alert | {alertname}:{status} | {device}:{target}"
            log.info("Submitting Prefect run: %s", flow_run_name)
            run_deployment(
                name="alert-receiver/alert-receiver",
                parameters={
                    "alertname": alertname,
                    "status": status,
                    "alert_group": alert_group.model_dump(mode="json"),
                },
                flow_run_name=flow_run_name,
                timeout=10,
            )

        log.info("Submitted %d flow run(s) for alert %s:%s", len(pairs), alertname, status)
    except Exception as e:  # noqa: BLE001 — broad catch is OK for webhook resilience
        log.error("Error running deployment: %s", e)
        error = str(e)

    return {"message": "Processed webhook"} if not error else {"error": error}
