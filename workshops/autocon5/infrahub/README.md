# Infrahub schema for the AutoCon5 workshop

[Infrahub][infrahub] is the workshop's source of truth (SoT). It holds the
**intent** for the lab: which devices exist, which interfaces are peers
versus management, which BGP peers each device should hold, and whether a
device is currently in maintenance. The Prefect alert-receiver flow,
Grafana dashboards, and the workshop SDK all read this data via GraphQL to
turn raw alerts into **decisions** ("this peer is intentionally down — skip"
versus "this peer should be up — quarantine").

This doc walks through the schema, why it looks the way it does, how it
maps to what the upstream `network-observability-lab` had in Nautobot, and
how to query and extend it.

[infrahub]: https://docs.infrahub.app

## TL;DR

Three node types live under a custom `Workshop` namespace:

```
WorkshopDevice ──── 1:N ──── WorkshopInterface
       │
       └────────── 1:N ──── WorkshopBgpSession
```

Apply with:

```bash
# Prereqs (one-time, from the repo root):
task setup                 # uv sync — installs autocon5 + nobs CLIs
task autocon5:up           # bring the stack online; wait ~60s for first boot

# Then:
task autocon5:load-infrahub
```

`autocon5 load-infrahub` (the Typer command behind that task) calls
`nobs schema load infrahub/schema.yml` to apply the schema, then walks
`lab_vars.yml` and idempotently upserts devices, interfaces, and BGP
sessions. Both halves of the work print Rich-styled summary tables.

## The model

### `WorkshopDevice`

A network device. Source of identity for everything else in the workshop.

| Attribute | Kind | Why it's here |
|-----------|------|----------------|
| `name` | `Text`, unique | Joins to the `device` label sonda emits. Everything pivots on this. |
| `asn` | `Number` | BGP autonomous system number (used by RCA prompts and dashboards). |
| `maintenance` | `Boolean`, default `false` | The maintenance gate. Toggled by `task autocon5:set-maintenance`; the policy in `automation/workshop_sdk.py` skips action when this is true. |
| `site_name` | `Text`, optional | Cosmetic — surfaced in evidence bundles and RCA prompts. |
| `role` | `Text`, optional | Same — cosmetic enrichment. |

Relationships:
- `interfaces` → many `WorkshopInterface` (component)
- `bgp_sessions` → many `WorkshopBgpSession` (component)

### `WorkshopInterface`

An interface on a device. Currently only its `role` is consumed by the
alert rules (`intf_role="peer"` filter), but the full attribute set is
loaded so dashboards and future alerts have something to draw on.

| Attribute | Kind | Why it's here |
|-----------|------|----------------|
| `name` | `Text` | Joins to the `name` label sonda emits (e.g. `ethernet-1/1`). |
| `role` | `Dropdown` (`peer` / `mgmt` / `loopback`), default `peer` | Drives the `intf_role` enrichment in `telegraf-02.conf.toml`. |
| `ip_address` | `Text`, optional | For the dashboard, and for future intent-vs-reality checks. |
| `expected_state` | `Dropdown` (`up` / `down`), default `up` | Lets the lab encode "this link is supposed to be down" so an interface alert on it can be filtered out. |

Parent relationship: `device` → `WorkshopDevice` (required).

### `WorkshopBgpSession`

A BGP peer the device is configured to maintain — this is what the
`BgpSessionNotUp` alert is checked against.

| Attribute | Kind | Why it's here |
|-----------|------|----------------|
| `peer_address` | `Text` | Joins to the `peer_address` label sonda emits. |
| `remote_as` | `Number` | Used in the RCA prompt and surfaced in dashboards. |
| `afi_safi` | `Text`, default `ipv4-unicast` | Joins to the `afi_safi_name` label. |
| `expected_state` | `Dropdown` (`established` / `down` / `disabled`), default `established` | The intent gate. The decision policy treats `down` / `disabled` as "this peer is supposed to be off — skip the alert." |
| `expected_prefixes_received` | `Number`, optional | Future-use — would let an alert fire on "session up but route count below intent." |
| `reason` | `Text`, optional | Free-text rationale (e.g. `"ip-mismatch-demo"`), surfaced into evidence bundles so the human reading the audit trail knows *why* the SoT looks the way it does. |

Parent relationship: `device` → `WorkshopDevice` (required).

## Design rationale

A few choices that aren't obvious from the YAML:

**Custom `Workshop` namespace, not `Dcim`.** Infrahub ships with a built-in
`Dcim` namespace (Device, Interface, etc.) that's much richer than what we
need. Reusing it would tangle the workshop schema with Infrahub's evolving
built-ins, and force attendees to wade through fields they don't care
about. A self-contained namespace keeps the schema lean and makes the
GraphQL queries readable.

**`maintenance` as a boolean on `WorkshopDevice`, not a separate "state"
node.** A real SoT might model maintenance windows with start/end times,
calendars, RBAC. For a 4-hour workshop the boolean is enough, and it makes
the four canonical paths in Part 3 (quarantine / skip / maintenance-skip /
audit) demoable in one `task autocon5:set-maintenance` call.

**`expected_state` on `WorkshopBgpSession` is a `Dropdown`, not a
boolean.** The original Nautobot model used a string like `"established"`
or `"down"` so the policy code could pattern-match on it. Mirroring that
shape keeps the policy in `workshop_sdk.py:DecisionPolicy.evaluate()`
identical to the one shipped in
`chapters/sonda-integration/netobs_workshop_sdk.py`, which makes the
upstream → workshop diff easier to teach.

**No `Site` or `Role` nodes.** They'd be nice to have but pull in
relationships that wouldn't earn their keep at this scale. `site_name`
and `role` are flat strings on `WorkshopDevice` — that's enough to
populate the RCA prompt and dashboard variables.

**`reason` on `WorkshopBgpSession`.** This one is workshop-specific and
worth highlighting. The lab deliberately ships two broken peers
(`srl1 → 10.1.99.2`, `srl2 → 10.1.11.1`) tagged with
`reason: ip-mismatch-demo`. When the alert fires and the policy fetches
the SoT gate, that string travels into the evidence bundle and into the
LLM RCA prompt — the human (or the AI) can see *why* this was set up to
break. In a real environment the `reason` field would carry change-ticket
references or "scheduled cutover" notes.

## Nautobot → Infrahub mapping

The upstream lab encoded the same intent in Nautobot. The shape changed
because Nautobot's data model is large and the workshop's needs are
small. This is the explicit mapping:

| What the workshop needs | Nautobot in `network-observability-lab` | Here in Infrahub |
|--------------------------|------------------------------------------|------------------|
| Device existence | `dcim.Device` filtered by `name` | `WorkshopDevice` filtered by `name__value` |
| Maintenance flag | `device.custom_fields.maintenance` (bool) | `WorkshopDevice.maintenance` |
| Site label | `device.site.name` | `WorkshopDevice.site_name` |
| Role label | `device.device_role.name` | `WorkshopDevice.role` |
| BGP peer intent | `device.local_config_context_data.observability_intent.bgp.intended_peers[]` | `WorkshopDevice.bgp_sessions` (component relationship) |
| Per-peer expected state | `intended_peers[].expected_state` | `WorkshopBgpSession.expected_state` |
| Per-peer remote AS | `intended_peers[].remote_as` | `WorkshopBgpSession.remote_as` |
| Per-peer rationale | `intended_peers[].reason` | `WorkshopBgpSession.reason` |
| Interfaces | `dcim.Interface` filtered by device | `WorkshopInterface` (parent: device) |

The two material simplifications:

1. **Config contexts** in Nautobot let you nest arbitrary JSON under a
   device. We flattened `observability_intent.bgp.intended_peers` into
   first-class `WorkshopBgpSession` nodes. That trades flexibility for
   queryability — Grafana can graph "BGP intent vs reality" with a
   single GraphQL field instead of unpacking nested JSON.
2. **Custom fields** in Nautobot become regular attributes here. There's
   no metadata layer separating "core" from "custom" because at this
   scale that distinction doesn't earn its keep.

The `chapters/sonda-integration` scenario in
`network-observability-lab` populated Nautobot from `lab_vars.yml`. The
workshop's loader (`scripts/load_infrahub.py`) reads the same
`lab_vars.yml`, so the two stay in sync if you ever want to compare
behaviour.

## Querying

### From Grafana

The provisioned `infrahub` datasource in
[`grafana/datasources.yml`](../grafana/datasources.yml) talks to
`http://infrahub-server:8000/graphql` with the `X-INFRAHUB-KEY` header.
Build dashboards with the `fifemon-graphql-datasource` plugin and feed
queries like this one:

```graphql
query {
  WorkshopBgpSession {
    edges {
      node {
        peer_address { value }
        expected_state { value }
        reason { value }
        device {
          node { name { value } }
        }
      }
    }
  }
}
```

For a per-device variable:

```graphql
query {
  WorkshopDevice {
    edges {
      node {
        name { value }
        maintenance { value }
      }
    }
  }
}
```

Map `node.name.value` to the variable's value and you can reuse the
variable across panels.

### From the Prefect SDK

The `WorkshopSDK` in
[`automation/workshop_sdk.py`](../automation/workshop_sdk.py) wraps an
`InfrahubClient` that fires a single GraphQL query
(`InfrahubClient.QUERY`) per device lookup:

```python
from workshop_sdk import WorkshopSDK

sdk = WorkshopSDK()
gate = sdk.bgp_gate(device="srl1", peer_address="10.1.99.2", afi_safi="ipv4-unicast")
# {
#   "found": True,
#   "maintenance": False,
#   "intended_peer": True,
#   "expected_state": "established",
#   "session": {...},
#   "device": "srl1",
#   "site": "lab",
#   "role": "edge",
#   "reason": "ip-mismatch-demo",
# }
```

The `gate` dict is exactly what `DecisionPolicy.evaluate()` consumes to
emit a `Decision` (`stop` / `skip` / `proceed`).

### From the CLI

```bash
INFRAHUB_API_TOKEN=$(grep ^INFRAHUB_API_TOKEN .env | cut -d= -f2)
curl -sS http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -H "X-INFRAHUB-KEY: $INFRAHUB_API_TOKEN" \
  -d '{"query":"{ WorkshopDevice { edges { node { name { value } maintenance { value } } } } }"}' \
  | python3 -m json.tool
```

## Extending the schema

### Add an attribute

Edit [`infrahub/schema.yml`](schema.yml), append the attribute under the
right node, then re-apply:

```yaml
# under WorkshopBgpSession.attributes
- name: hold_time_seconds
  kind: Number
  optional: true
  description: BGP hold-time (intent).
```

```bash
task autocon5:load-infrahub
```

Schema reloads are non-destructive — Infrahub diffs the new schema
against the live one and migrates in place.

If the new attribute should be populated from `lab_vars.yml`, also extend
[`scripts/load_infrahub.py`](../scripts/load_infrahub.py) — find the
relevant `_upsert_*` function and add the field to the payload dict.

### Add a node type

Same flow — add a new entry under `nodes:` in `schema.yml`, declare its
relationships back to `WorkshopDevice`, then re-apply. A trivial
example for an OSPF intent block would be:

```yaml
- name: OspfArea
  namespace: Workshop
  attributes:
    - name: area_id
      kind: Text
    - name: expected_neighbor_count
      kind: Number
      optional: true
  relationships:
    - name: device
      peer: WorkshopDevice
      kind: Parent
      cardinality: one
      optional: false
```

Then add an `_upsert_ospf_area` helper in `load_infrahub.py` and call it
from `main()` for each device.

### Add a new dropdown choice

Dropdowns are part of the schema, not a free-form list. To add (e.g.) a
new interface role, edit the `choices:` list under that attribute and
re-apply. Existing nodes keep their old values; new nodes can use the
new option.

## Auth + token

- The token in `.env` is **`INFRAHUB_API_TOKEN`**.
- It's seeded into the running server via
  **`INFRAHUB_INITIAL_ADMIN_TOKEN`** (see the `infrahub-server` service
  in `docker-compose.yml`). That env var is only honoured on the *first*
  boot of `infrahub-server`. If you change the token after the first
  boot, run `task autocon5:destroy && task autocon5:up`.
- All HTTP requests pass the token in the **`X-INFRAHUB-KEY`** header,
  not `Authorization`. Both the Grafana datasource and the
  `InfrahubClient` in the SDK use this header.

## Where things live

| File | Purpose |
|------|---------|
| `infrahub/schema.yml` | The source of truth for the schema. |
| `lab_vars.yml` | The data fed into the schema (devices, interfaces, BGP intent). |
| `scripts/load-infrahub.sh` | Thin shell wrapper: waits for Infrahub to be reachable, then invokes `autocon5 load-infrahub`. |
| `src/autocon5_cli/load.py` | Workshop loader. Idempotent upsert from `lab_vars.yml`. The schema apply step delegates to `nobs schema load`. |
| `src/autocon5_cli/evidence.py` | `autocon5 evidence DEVICE PEER` — Rich panels of the SoT gate, metrics snapshot, log lines, and policy hint for a (device, peer) pair. |
| `../../packages/nobs/src/nobs/clients/infrahub.py` | Generic Infrahub GraphQL client used by the workshop CLI and by future workshops. |
| `../../packages/nobs/src/nobs/commands/schema.py` | `nobs schema load PATH` — generic schema apply (wraps `infrahubctl`). |
| `../../packages/nobs/src/nobs/commands/maintenance.py` | `nobs maintenance` (re-exported as `autocon5 maintenance`) — generic over `--kind`, defaults to `WorkshopDevice`. |
| `automation/workshop_sdk.py` | `InfrahubClient` + policy gate inside the Prefect container (kept standalone so the Prefect image stays small). |
| `grafana/datasources.yml` | Provisioned `infrahub` GraphQL datasource for dashboards. |

## See also

- Infrahub docs — [Schema][schema-docs], [Schema reference][schema-ref],
  [API tokens][token-docs], [GraphQL][gql-docs].
- The `WorkshopSDK` and `InfrahubClient` source in
  `../automation/workshop_sdk.py` — the GraphQL query the workshop
  actually runs at runtime is one constant: `InfrahubClient.QUERY`.

[schema-docs]: https://docs.infrahub.app/topics/schema
[schema-ref]: https://docs.infrahub.app/reference/schema
[token-docs]: https://docs.infrahub.app/reference/api-tokens
[gql-docs]: https://docs.infrahub.app/topics/graphql
