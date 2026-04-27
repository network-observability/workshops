"""`nobs autocon5 load-infrahub` - apply schema (via nobs) + seed lab_vars.yml."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from nobs._console import console, fail, ok, step, warn
from nobs.commands import schema as nobs_schema
from rich.panel import Panel
from rich.table import Table

# Default paths are anchored to the workshop directory (workshops/autocon5/).
_WORKSHOP_DIR = Path(__file__).resolve().parents[2]


def _detect_default(path: Path) -> Path:
    if path.is_absolute():
        return path
    if path.exists():
        return path.resolve()
    candidate = (_WORKSHOP_DIR / path).resolve()
    return candidate if candidate.exists() else path


def load_infrahub(
    schema: Annotated[
        Path, typer.Option("--schema", help="Path to the Infrahub schema YAML."),
    ] = Path("infrahub/schema.yml"),
    lab_vars: Annotated[
        Path, typer.Option("--lab-vars", help="Path to lab_vars.yml."),
    ] = Path("lab_vars.yml"),
    address: Annotated[
        str, typer.Option("--address", envvar="INFRAHUB_ADDRESS", help="Infrahub URL."),
    ] = "http://localhost:8000",
    token: Annotated[
        str, typer.Option("--token", envvar="INFRAHUB_API_TOKEN"),
    ] = "",
    skip_schema: Annotated[
        bool, typer.Option("--skip-schema", help="Skip the `infrahubctl schema load` step."),
    ] = False,
) -> None:
    """Apply the workshop schema and seed lab_vars.yml into Infrahub.

    Idempotent. Re-running updates existing nodes rather than duplicating.
    The schema apply step delegates to `nobs schema load`; the data upsert
    is workshop-specific (it knows the `WorkshopDevice` / `WorkshopInterface`
    / `WorkshopBgpSession` schema and the `lab_vars.yml` shape).
    """
    schema = _detect_default(schema)
    lab_vars = _detect_default(lab_vars)

    if not token:
        fail("INFRAHUB_API_TOKEN is required (set it in .env or pass --token).")
        raise typer.Exit(code=1)

    if not skip_schema:
        nobs_schema.load(path=schema, address=address, token=token)

    if not lab_vars.exists():
        fail(f"lab_vars file not found: {lab_vars}")
        raise typer.Exit(code=1)

    step(f"Loading [label]{lab_vars}[/] into Infrahub at [label]{address}[/]")
    summary = _seed_lab_vars(address=address, token=token, lab_vars=lab_vars)
    _print_summary(summary)


# ---------------------------------------------------------------------------
# Workshop-specific data loading
# ---------------------------------------------------------------------------


def _seed_lab_vars(address: str, token: str, lab_vars: Path) -> dict[str, dict[str, int]]:
    try:
        from infrahub_sdk import Config, InfrahubClientSync
    except ImportError:
        fail("infrahub-sdk is not installed. Run `nobs setup` first.")
        sys.exit(1)

    counts: dict[str, dict[str, int]] = {
        "WorkshopDevice": {"created": 0, "updated": 0},
        "WorkshopInterface": {"created": 0, "updated": 0},
        "WorkshopBgpSession": {"created": 0, "updated": 0},
    }

    with lab_vars.open() as fh:
        lab = yaml.safe_load(fh)

    nodes = lab.get("nodes") or {}
    intent_bgp = ((lab.get("observability_intent") or {}).get("bgp") or {})
    afi_safi = intent_bgp.get("afi_safi", "ipv4-unicast")
    intended_peers = intent_bgp.get("intended_peers") or {}

    client = InfrahubClientSync(address=address, config=Config(api_token=token))

    for device_name, node_def in nodes.items():
        device, was_created = _upsert_device(client, device_name, node_def)
        counts["WorkshopDevice"]["created" if was_created else "updated"] += 1
        ok(f"device [label]{device_name}[/] {'created' if was_created else 'updated'}")

        for intf in node_def.get("interfaces", []) or []:
            was_created = _upsert_interface(client, device, intf)
            counts["WorkshopInterface"]["created" if was_created else "updated"] += 1

        for session in intended_peers.get(device_name, []) or []:
            was_created = _upsert_bgp_session(client, device, session, afi_safi=afi_safi)
            counts["WorkshopBgpSession"]["created" if was_created else "updated"] += 1

    return counts


def _upsert_device(client: Any, name: str, node: dict[str, Any]) -> tuple[Any, bool]:
    existing = client.filters(kind="WorkshopDevice", name__value=name)
    if existing:
        device = existing[0]
        device.asn.value = node.get("asn")
        device.maintenance.value = bool(node.get("maintenance", False))
        device.site_name.value = node.get("site", "lab")
        device.role.value = node.get("role", "edge")
        device.save()
        return device, False
    device = client.create(
        kind="WorkshopDevice",
        name=name,
        asn=node.get("asn"),
        maintenance=bool(node.get("maintenance", False)),
        site_name=node.get("site", "lab"),
        role=node.get("role", "edge"),
    )
    device.save()
    return device, True


def _upsert_interface(client: Any, device: Any, intf: dict[str, Any]) -> bool:
    name = intf["name"]
    existing = client.filters(kind="WorkshopInterface", name__value=name, device__ids=[device.id])
    payload = {
        "name": name,
        "role": intf.get("role", "peer"),
        "ip_address": intf.get("ip"),
        "expected_state": intf.get("expected_state", "up"),
        "device": device.id,
    }
    if existing:
        node = existing[0]
        for key, value in payload.items():
            if key == "device":
                continue
            getattr(node, key).value = value
        node.save()
        return False
    node = client.create(kind="WorkshopInterface", **payload)
    node.save()
    return True


def _upsert_bgp_session(client: Any, device: Any, session: dict[str, Any], afi_safi: str) -> bool:
    peer_address = session["peer_ip"]
    existing = client.filters(
        kind="WorkshopBgpSession",
        peer_address__value=peer_address,
        device__ids=[device.id],
    )
    payload = {
        "peer_address": peer_address,
        "remote_as": session.get("remote_as"),
        "afi_safi": afi_safi,
        "expected_state": session.get("expected_state", "established"),
        "expected_prefixes_received": session.get("expected_prefixes_received"),
        "reason": session.get("reason"),
        "device": device.id,
    }
    if existing:
        node = existing[0]
        for key, value in payload.items():
            if key == "device":
                continue
            getattr(node, key).value = value
        node.save()
        return False
    node = client.create(kind="WorkshopBgpSession", **payload)
    node.save()
    return True


# ---------------------------------------------------------------------------
# Pretty summary
# ---------------------------------------------------------------------------


def _print_summary(counts: dict[str, dict[str, int]]) -> None:
    table = Table(title="Infrahub seed result", show_lines=False, header_style="label")
    table.add_column("Node type", no_wrap=True)
    table.add_column("Created", justify="right", style="ok")
    table.add_column("Updated", justify="right", style="info")
    table.add_column("Total", justify="right")

    grand = 0
    for kind, c in counts.items():
        total = c["created"] + c["updated"]
        grand += total
        table.add_row(kind, str(c["created"]), str(c["updated"]), str(total))

    console.print()
    console.print(table)
    console.print()
    console.print(
        Panel.fit(
            f"[ok]Done.[/] {grand} node(s) processed across {len(counts)} types.\n"
            f"Open the Infrahub UI at [label]http://localhost:8000[/] to browse.",
            border_style="green",
        )
    )
    if not counts["WorkshopDevice"]["created"] and not counts["WorkshopDevice"]["updated"]:
        warn("No devices found in lab_vars.yml - did you point --lab-vars at the right file?")
