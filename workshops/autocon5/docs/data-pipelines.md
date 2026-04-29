# Data pipelines: direct vs shipper

The workshop runs the **same telemetry through two parallel pipelines** for both metrics and logs.
`srl1` emits already-canonical data direct to Prometheus / Loki.
`srl2` emits a vendor-shaped raw stream that flows through a shipper (Telegraf for metrics, Vector for logs) which normalizes it into the canonical schema before it lands in storage.

Both paths converge on **identical labels and metric names** in storage, distinguishable only by a `pipeline=` label.
Open Grafana → Explore and toggle the selector to see the same data via two valid topologies side-by-side.

## TL;DR

```
                              srl1 (direct)            srl2 (shipper)
                              ──────────────           ─────────────────────────────
metrics  sonda emits          canonical names    →     raw `srl_*` names + `source`
                              + `device` tag           tag (sonda-server scrape)
         shipper                  —                    telegraf-02 (rename + enrich)
         lands in                 Prometheus           Prometheus
         label                    pipeline="direct"    pipeline="telegraf"

logs     sonda emits          canonical labels   →     RFC 5424 syslog (UDP)
                              (loki sink)              to vector:1514
         shipper                  —                    vector (decode + enrich)
         lands in                 Loki                 Loki
         label                    pipeline="direct"    pipeline="vector"
```

Workshop CLI annotations (flap-interface, maintenance, Prefect decisions) take a third path: they `POST /events` to **sonda-server**, which forwards to Loki. Documented in the [Workshop CLI annotations](#workshop-cli-annotations) section below.

## Metrics

### Pipeline diagram

```
srl1 metrics (direct)
┌──────────────────────────┐    remote_write
│ sonda-srl1 (CLI)         │  ───────────────►  Prometheus
│ srlinux_gnmi_bgp,        │
│ srlinux_gnmi_interface   │
└──────────────────────────┘

srl2 metrics (shipper / "raw → normalized")
┌──────────────────────────┐  HTTP scrape  ┌─────────────────────────┐  scrape  ┌────────────┐
│ sonda-server             │  /scenarios/  │ telegraf-02             │   :9005  │ Prometheus │
│ srlinux_gnmi_bgp_raw,    │  /<id>/       │ - field_rename srl_* -> │  ───────►│            │
│ srlinux_gnmi_interface_  │  metrics      │ - tag rename source ->  │          │            │
│ raw                      │  (every 10s)  │   device                │          │            │
│                          │  ────────────►│ - regex enrich          │          │            │
│ Emits raw shape:         │               │   intf_role             │          │            │
│   srl_bgp_oper_state{    │               │ - static pipeline=      │          │            │
│     source="srl2", ...}  │               │   telegraf              │          │            │
└──────────────────────────┘               └─────────────────────────┘          └────────────┘
```

### Inspect the raw shape (pre-Telegraf)

`sonda-server` exposes a Prometheus-text endpoint per scenario.

```bash
# List all scenarios sonda-server is running
curl -s localhost:8085/scenarios | jq -r '.scenarios[] | "\(.id)\t\(.name)"'

# Pick the first srl_bgp_oper_state scenario and pull its raw output
SID=$(curl -s localhost:8085/scenarios \
  | jq -r '[.scenarios[] | select(.name=="srl_bgp_oper_state")][0].id')
curl -s localhost:8085/scenarios/$SID/metrics
```

You'll see the vendor-prefixed names + `source` tag:

```
srl_bgp_oper_state{afi_safi_name="ipv4-unicast",collection_type="gnmi",
  name="default",neighbor_asn="65101",peer_address="10.1.2.1",
  source="srl2"} 1 1777367964476
```

### Inspect the normalized shape (post-Telegraf)

Telegraf publishes its output on `:9005`.

```bash
docker exec telegraf-02 wget -qO- 127.0.0.1:9005/metrics \
  | grep '^bgp_oper_state' | head
```

```
bgp_oper_state{afi_safi_name="ipv4-unicast",collection_type="gnmi",
  device="srl2",host="telegraf-02",name="default",neighbor_asn="65101",
  peer_address="10.1.2.1",pipeline="telegraf"} 1
```

`srl_` prefix gone, `source` renamed to `device`, `pipeline=telegraf` added.

### Compare both paths in Prometheus

Open Grafana → Explore → `prometheus` datasource:

```promql
# Both paths, same metric, side-by-side
bgp_oper_state{pipeline=~".+"}

# Just the direct path (srl1)
bgp_oper_state{pipeline="direct"}

# Just the shipper path (srl2)
bgp_oper_state{pipeline="telegraf"}

# Series count per pipeline (sanity check)
count by (pipeline) (bgp_oper_state)
```

Alert rules and dashboards stay agnostic of `pipeline=` — they query `bgp_oper_state{...}` and match both paths.

## Logs

### Pipeline diagram

```
srl1 logs (direct)
┌──────────────────────────┐    loki sink (HTTP push)
│ sonda-logs (srl1 streams)│  ─────────────────────────►  Loki
│ - srl1_system_logs       │
│ - srl1_updown_logs       │
│ - srl1_bgp_logs          │
│ stream label:            │
│   pipeline="direct"      │
└──────────────────────────┘

srl2 logs (shipper / "RFC 5424 syslog → Vector → Loki")
┌──────────────────────────┐  syslog UDP   ┌──────────────────────────┐  HTTP   ┌──────┐
│ sonda-logs (srl2 streams)│  vector:1514  │ vector                   │  push   │      │
│ - srl2_system_logs       │  ────────────►│ - socket source          │ ───────►│ Loki │
│ - srl2_updown_logs       │   RFC 5424    │   (codec=syslog)         │         │      │
│ - srl2_bgp_logs          │   syslog      │ - VRL: lift `.sonda.*`   │         │      │
│ encoder: syslog          │   text        │   SD payload to labels   │         │      │
│ sink: udp(vector:1514)   │               │ - static pipeline=vector │         │      │
└──────────────────────────┘               │ - encode JSON for Loki   │         │      │
                                            └──────────────────────────┘         └──────┘
```

### Inspect the raw payload (sonda → Vector)

`tcpdump` inside the Vector container shows the wire bytes:

```bash
docker exec vector tcpdump -nn -A -i any -s 0 udp port 1514 -c 2 2>&1
```

You'll see RFC 5424 frames like:

```
<14>1 2026-04-28T08:30:10.648Z srl2 srlinux - - [sonda device="srl2"
  netpanda="bethepacket" peer="10.1.11.1" type="srlinux"
  vendor_facility="srlinux" vendor_facility_process="BGP"]
  BGP neighbor 10.1.11.1: state changed to idle
```

### Inspect the decoded shape (post-Vector)

Vector exposes its events via the Loki sink — query Loki itself:

```bash
# srl2 streams (only path that goes through Vector)
curl -sG 'http://localhost:3001/loki/api/v1/series' \
  --data-urlencode 'match[]={device="srl2", pipeline="vector"}' \
  | jq '.data[] | keys'
```

The label set should include `device`, `pipeline=vector`, `vendor_facility`, `vendor_facility_process`, `interface`, `interface_status`, `peer`, `level` — same labels srl1 emits, just lifted by Vector from RFC 5424 structured-data.

### Compare both paths in Loki

Grafana → Explore → `loki` datasource:

```logql
# Both paths
{vendor_facility_process="UPDOWN", pipeline=~".+"}

# Just direct (srl1)
{device="srl1", pipeline="direct"}

# Just Vector (srl2)
{device="srl2", pipeline="vector"}

# Per-pipeline rates (sanity check — both should be ≈ 0.05/s = 6 per 2 min)
sum by (pipeline) (rate({vendor_facility_process="UPDOWN"}[2m]))
```

The line content shape differs slightly:

- **Direct path (srl1)** — sonda's `json_lines` default: `{"timestamp":..., "severity":..., "message":..., "labels":{...}}`
- **Vector path (srl2)** — Vector's JSON encoding after `enrich` transform: `{"appname":..., "device":..., "hostname":..., "level":..., "message":..., ...}`

Existing line-filter regexes (`|~ "down|up|admin-state"` in `workshop-lab-1`'s Interface Logs panel) match both because the JSON in either shape contains the relevant tokens.

## Workshop CLI annotations

Three workshop sites emit one-shot annotations alongside the curriculum data flows: `nobs autocon5 flap-interface` (UPDOWN events), `nobs autocon5 maintenance` (config-push events), and Prefect flows (decision/skip/resolved audit trail). All three route through **sonda-server's `POST /events`** instead of pushing to Loki directly.

### Pipeline diagram

```
Workshop CLI (host machine)                       Prefect flows (in-container)
   ┌──────────────────────────┐                      ┌──────────────────────────┐
   │ nobs autocon5            │                      │ WorkshopSDK.annotate*()  │
   │   flap-interface         │                      │ workshop_sdk.LokiClient  │
   │   maintenance            │                      │   .annotate()            │
   │ LokiClient.annotate()    │                      │                          │
   └──────────┬───────────────┘                      └──────────┬───────────────┘
              │ POST /events                                    │ POST /events
              │ via SONDA_SERVER_URL                            │ via SONDA_SERVER_URL
              │ (host-mapped:                                   │ (container DNS:
              │  http://localhost:8085)                         │  http://sonda-server:8080)
              ▼                                                  ▼
              ┌──────────────────────────────────────────────────┐
              │ sonda-server v1.3.0                              │
              │  POST /events handler                            │
              │   • validates payload                            │
              │   • forwards to sink config inline               │
              │   • returns {sent, signal_type, latency_ms}      │
              └──────────────┬───────────────────────────────────┘
                             │ sink={type:loki, url:SONDA_LOKI_SINK_URL}
                             ▼
                          Loki (http://loki:3001)
```

### Why route through /events

- **Single edge for observability**: every workshop-emitted annotation is auditable at the sonda layer (latency, sink result, error mapping).
- **Auth-gated when needed**: setting `SONDA_API_KEY` enables Bearer auth on `/events` *and* `/scenarios` simultaneously.
- **Sink-agnostic at the call site**: callers describe their event in semantic terms (signal_type + labels + log body); the sink config is inline so we can swap Loki for stdout / OTLP / Kafka without changing CLI code.

### Three env vars to know

| Variable | Default | Used by | Purpose |
|---|---|---|---|
| `SONDA_SERVER_URL` | `http://localhost:8085` (host) / `http://sonda-server:8080` (container) | flap, maintenance, Prefect | Where to POST `/events`. Host CLI uses the host-mapped port; in-container callers use container DNS. |
| `SONDA_API_KEY` | (empty) | all callers | Bearer token. Empty = sonda is public. Set to a value in `.env` to require auth. |
| `SONDA_LOKI_SINK_URL` | `http://loki:3001` | inside the `/events` payload | The URL **sonda** uses to reach Loki, distinct from the host-side `LOKI_URL` the CLI uses for direct queries. They're different addresses for the same service because of the host-vs-container network split. |

### Severity vocab translation

Sonda's `log.severity` enum is `trace | debug | info | warn | error | fatal`. Loki / syslog dashboards filter on `level=warning|notice|critical|...`. The `LokiClient.annotate()` facade maps the broader vocab down to sonda's enum (`warning` → `warn`, `notice` → `info`, `critical` → `error`, `alert` / `emergency` → `fatal`). The `level` label in the labels dict keeps the Loki spelling, so `{level="warning"}` filters in dashboards continue to match.

### Inspect the `/events` flow

```bash
# Health probe + a synthetic test event
curl -s http://localhost:8085/health
curl -s -X POST http://localhost:8085/events \
  -H 'Content-Type: application/json' \
  -d '{
    "signal_type": "logs",
    "labels": {"device": "srl1", "source": "preflight", "level": "info"},
    "log": {"severity": "info", "message": "test event", "fields": {}},
    "encoder": {"type": "json_lines"},
    "sink": {"type": "loki", "url": "http://loki:3001"}
  }' | jq .
# Expected: {"sent": true, "signal_type": "logs", "latency_ms": <small>}

# Confirm it landed in Loki
curl -sG http://localhost:3001/loki/api/v1/query_range \
  --data-urlencode 'query={source="preflight"}' --data-urlencode 'limit=3'
```

### Curriculum point

The same annotation appears in Loki regardless of which path produced it — but the `pipeline=` label distinguishes them:

```logql
# Direct sonda-emitted log scenarios (srl1)
{pipeline="direct"}

# Vector-shipped syslog (srl2)
{pipeline="vector"}

# CLI / Prefect annotations via /events
{source=~"workshop-trigger|prefect"}
```

## Maintainer cheatsheet

After any change touching scenarios, packs, Telegraf config, or Vector config:

```bash
# 1. Convergence check — both pipelines visible in Prometheus
curl -sG localhost:9090/api/v1/query \
  --data-urlencode 'query=count by (pipeline) (bgp_oper_state)'
# Expect: pipeline="direct" + pipeline="telegraf", each with the same count.

# 2. Convergence check — both pipelines visible in Loki
curl -sG localhost:3001/loki/api/v1/series \
  --data-urlencode 'match[]={vendor_facility_process="UPDOWN"}' \
  | jq -r '.data[].pipeline' | sort -u
# Expect: "direct" and "vector".

# 3. Alerts still fire on both devices
nobs autocon5 alerts

# 4. End-to-end Part 3 paths
nobs autocon5 try-it --auto

# 5. Sonda /events plumbing (annotations)
curl -s http://localhost:8085/health
# Expect: {"status":"ok"}
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1 --count 2
nobs autocon5 maintenance --device srl1 --state
# Expect: both succeed; Loki has matching streams under
#   {source="workshop-trigger"}.
```

If any of these regress, the most likely cause is a `docker compose restart` race between sonda-server and sonda-setup — sonda-server is in-memory only, so a restart drops its scenarios.
Re-kick sonda-setup explicitly if that happens:

```bash
docker compose --project-name autocon5 restart sonda-setup
```

## Why two pipelines

The pattern shows up in real networks:

- Some exporters / vendors emit ready-to-store telemetry directly (srl1's path).
- Others emit raw vendor-specific shapes that need a shipper to harmonize (srl2's path).

A modern observability stack typically has both, and the curriculum hour spent on Telegraf processors and Vector VRL is justified by walking attendees through what each shipper actually does.
The `pipeline` label is the lever for comparing them in one query.

## Cross-references

- [`telegraf/telegraf-02.conf.toml`](../telegraf/telegraf-02.conf.toml) — the Telegraf processor chain (field rename, tag rename, regex enrich).
- [`vector/vector.yaml`](../vector/vector.yaml) — the Vector VRL transform (severity remap, SD payload promotion).
- [`sonda/packs/`](../sonda/packs/) — both canonical and `*_raw` packs.
- [`sonda/scenarios/`](../sonda/scenarios/) — `srl1-metrics.yaml` (direct), `srl2-metrics.yaml` (raw → Telegraf), `all-logs.yaml` (mixed direct + syslog→Vector).
- [`packages/nobs/src/nobs/clients/loki.py`](../../../packages/nobs/src/nobs/clients/loki.py) — the `LokiClient.annotate()` facade that routes annotations through `POST /events`.
- [`docs/preflight.md`](preflight.md) — `nobs autocon5 preflight` regression check.
