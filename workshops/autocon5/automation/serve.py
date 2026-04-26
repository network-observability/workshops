"""
Serve the alert-receiver Prefect deployment.

This is the entrypoint for the `prefect-flows` container. It registers
`alert_receiver` as a Prefect deployment named `alert-receiver` and keeps the
process alive to serve flow runs that the webhook submits via
`run_deployment("alert-receiver/alert-receiver", …)`.
"""

from __future__ import annotations

from flows import alert_receiver


if __name__ == "__main__":
    alert_receiver.serve(name="alert-receiver")
