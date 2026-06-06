---
title: Part 3 — Alert response, Automation and AI
description: Late morning. A real alert lands and your senior narrates how the workflow handles it. Walk the four alert paths, toggle the AI RCA step.
---

<div class="autocon5-section-hero" markdown>

<span class="autocon5-section-hero__badge">Part 3 of 4 · Late morning</span>

<h1 class="autocon5-section-hero__title">Alert response, Automation and AI</h1>

<p class="autocon5-section-hero__subtitle">Observability is the feedback loop. Automation closes it.</p>

Parts 1 and 2 dropped you into **observability** — the feedback loop a network engineer reaches for when something looks wrong, the half of the picture made of metrics and logs streaming off the live system. Part 3 is the other half: **automation as the action that closes the loop**. A real `BgpSessionNotUp` alert lands. An **orchestrator** picks it up, asks the **source of truth** what *should* be true, holds it against the observability stream, and acts on the gap. SoT · observability · orchestrator — the trio every network automation framework names — wired here with [Infrahub](tour.md#infrahub-source-of-truth), [Prometheus](tour.md#prometheus-the-metrics-store) + Loki, and [Prefect](tour.md#prefect-workflows-deployments-runs).

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
%}

<nav class="autocon5-nav-footer" markdown>

<a href="../part-2/">
  <span class="autocon5-nav-footer__label">← Previous</span>
  <span class="autocon5-nav-footer__title">Part 2 — Dashboards and Alerts</span>
</a>

<a class="autocon5-nav-footer__next" href="../advanced/">
  <span class="autocon5-nav-footer__label">Next →</span>
  <span class="autocon5-nav-footer__title">Advanced — The 02:14 page</span>
</a>

</nav>
