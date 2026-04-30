## Workshop UX Roadmap

Tracker for student-facing UX improvements identified during the live polish review.
Items are ordered by **impact-to-effort**, not priority. Cross items off as PRs land.

### Status legend

- [x] **Done** — shipped to `main`.
- [ ] **Open** — agreed direction, not yet implemented.
- [?] **Considering** — needs design discussion before action.

---

### Done

- [x] **Workshop Home dashboard** — curated landing page replaces Grafana's empty default. Health summary tiles, navigation tiles, recent events feed, firing alerts table.

### Open

- [ ] **Health summary row on every dashboard** — `Devices · Interfaces · Firing alerts · Log lines (5m)` strip at the top of `device-health` and `workshop-lab`. Same data as the home dashboard's health row, but follows students into the per-device views so situational awareness travels with them.

- [ ] **Recent Events panel on `device-health`** — Loki query `{vendor_facility_process="UPDOWN"} or {source="workshop-trigger"}` rendered as a logs panel near the top. Annotation markers are subtle; a feed is impossible to miss when something just happened.

- [ ] **Cross-dashboard navigation links** — populate the dashboard `links` array (top-right) on `device-health` and `workshop-lab` with: `Workshop Home`, `srl1 Health`, `srl2 Health`, `Workshop Lab`, `Runbook`. Reduces dependency on the sidebar.

- [ ] **Explore preset queries** — saved Grafana queries that students can pick from a dropdown rather than write LogQL/PromQL from scratch. Suggested presets:
  - `All UPDOWN events for $device` (Loki)
  - `BGP session state changes` (Loki + Prometheus)
  - `Pipeline=vector logs only` (Loki)
  - `count by (pipeline)(bgp_oper_state)` (Prometheus)

- [ ] **Pipeline color consistency** — same colour for `direct` / `telegraf` / `vector` across every panel that has the pipeline label, not only on the Signal Pipelines row. Currently green/blue/orange on the Pipelines row but other panels render in their own palette. Reinforces the curriculum visually everywhere.

- [ ] **Curriculum progress indicator** — small markdown panel on the Workshop Home listing `Part 1: Hybrid pipelines · Part 2: Alerts · Part 3: Automation` with each section linked to the corresponding README anchor. Tells students where they are in the workshop arc.

- [ ] **Pre-set time range buttons** — `Live (5m) · Lab (15m) · Demo (1h)` quick toggles. Less hunting in the time picker for the canonical ranges the workshop demos around.

### Considering

- [?] **First-boot empty-state copy** — when Prometheus has <30s of data, panels render blank and look broken. A markdown banner that says "stack just booted; give it 30 seconds for the first scrape" would reduce anxiety. Lower priority because the workshop facilitator covers it verbally during the intro.
