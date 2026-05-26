---
title: Part 3 — Alerts, automation, AI
description: Late morning. A real alert lands and your senior narrates how the workflow handles it. Walk the four alert paths, toggle the AI RCA step.
---

<div class="autocon5-section-hero" markdown>

<span class="autocon5-section-hero__badge">Part 3 of 4 · Late morning</span>

<h1 class="autocon5-section-hero__title">Alerts, automation, AI</h1>

<p class="autocon5-section-hero__subtitle">An alert lands. The loop between what should be true and what is true closes — and a workflow bridges the gap.</p>

Parts 1 and 2 only saw one half of the picture: the metrics and logs streaming out of the live system — *reality*. Part 3 is where the other half walks in. Every operational decision in production rides on the gap between two pieces of context: what the network is *supposed* to be doing (intent) and what it's *actually* doing (reality). When those two disagree, someone — or something — has to decide whether the gap is expected (a maintenance window, a decommissioned link, an intentional state) or actionable (page the on-call). Part 3 is where that decision happens, automatically, on every alert.

Three operational concepts close the loop:

- **Source of truth — what should be true.** The database where intent lives: configured peers, maintenance windows, ownership. The flow asks this *first*, before it ever looks at metrics. In this workshop the SoT is **[Infrahub](tour.md#infrahub-source-of-truth)**, but the loop is the same with any inventory or CMDB.
- **Observability — what is true.** The metrics and logs the live system is emitting right now. You already used this in Parts 1 and 2: **[Prometheus](tour.md#prometheus-the-metrics-store)** for metrics, Loki for logs, **[Grafana](tour.md#grafana-dashboards-and-explore)** as the unified UI.
- **Workflow orchestration — the bridge.** The deterministic decision engine that compares intent against reality and picks one of four outcomes per alert: proceed (page someone), skip (this gap is expected), resolved (it's already fixed itself), or stop (we can't tell — bail safely). In this workshop the bridge is **[Alertmanager](tour.md#alertmanager-the-alert-router-and-silence-store)** routing the alert and **[Prefect](tour.md#prefect-workflows-deployments-runs)** running the decision logic.

The loop is two-way. Operations push intent *into* the SoT (flipping a `maintenance` flag before a planned change); the workflow reads intent *out* of the SoT at every alert. Reality flows the same way: the workflow records its decisions back as audit annotations that future runs (and future humans) can read. Part 3 closes the loop that Parts 1 and 2 only walked the metrics half of.

A real alert lands while your senior narrates. Walk the four paths the workflow handles, toggle the AI RCA step, and decide which paths you'd trust the LLM narrative on at 02:14. Your senior signs off as the lunch break lands — you're ready to take primary on the rotation tomorrow.

<p class="autocon5-section-hero__meta">
  <span>~75 minutes</span>
  <span>Four paths walked end-to-end</span>
  <span>Optional AI-assisted RCA toggle</span>
</p>

</div>

<figure class="section-preview" markdown>

![Currently firing alerts — Alertmanager state during a cascade](../assets/screenshots/workshop-home-firing-alerts-light.png#only-light){ .screenshot loading=lazy }
![Currently firing alerts — Alertmanager state during a cascade](../assets/screenshots/workshop-home-firing-alerts-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption>What lands in Alertmanager when the cascade kicks off — severity, device, peer, interface, the standard labels. This table is the input the Prefect automation reasons over in each of the four paths you walk in Part 3.</figcaption>

</figure>

<figure class="section-preview" markdown>

![Prefect flow run detail — quarantine_bgp task graph](../assets/screenshots/prefect-flow-run-detail-light.png#only-light){ .screenshot loading=lazy }
![Prefect flow run detail — quarantine_bgp task graph](../assets/screenshots/prefect-flow-run-detail-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption>What the flow looks like once it runs: the `quarantine_bgp` task graph (collect_evidence → evaluate_policy → annotate_decision → ai_rca → quarantine → annotate_action) plus the per-task log feed. You'll open this during the Prefect UI tour at the end of Step 2.</figcaption>

</figure>

{%
  include-markdown "../../workshops/autocon5/guides/part-3-alerts-automation-ai.md"
  start="## What you'll do here"
  end="## Stretch goals"
%}

??? tip "Stretch goals — pick one if you have time before lunch"

    {%
      include-markdown "../../workshops/autocon5/guides/part-3-alerts-automation-ai.md"
      start="## Stretch goals"
      end="## What you took away"
      heading-offset=1
    %}

## What you took away

{%
  include-markdown "../../workshops/autocon5/guides/part-3-alerts-automation-ai.md"
  start="## What you took away"
%}

<nav class="autocon5-nav-footer" markdown>

<a href="../part-2/">
  <span class="autocon5-nav-footer__label">← Previous</span>
  <span class="autocon5-nav-footer__title">Part 2 — Dashboards</span>
</a>

<a class="autocon5-nav-footer__next" href="../advanced/">
  <span class="autocon5-nav-footer__label">Next →</span>
  <span class="autocon5-nav-footer__title">Advanced — The 02:14 page</span>
</a>

</nav>
