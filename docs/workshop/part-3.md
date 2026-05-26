---
title: Part 3 — Alerts, automation, AI
description: Late morning. A real alert lands and your senior narrates how the workflow handles it. Walk the four alert paths, toggle the AI RCA step.
---

<div class="autocon5-section-hero" markdown>

<span class="autocon5-section-hero__badge">Part 3 of 4 · Late morning</span>

<h1 class="autocon5-section-hero__title">Alerts, automation, AI</h1>

<p class="autocon5-section-hero__subtitle">An alert lands. Three tools decide together what to do with it.</p>

Part 3 puts three building blocks in the same room and watches them collaborate on a single alert payload. You won't be jumping between unrelated UIs — every step in the next hour is a move inside one of these three:

- **[Alertmanager](tour.md#alertmanager-the-alert-router-and-silence-store)** is the alert plane. It receives `BgpSessionNotUp` from Prometheus, dispatches it to the webhook, and stores the silence the flow asks it to create once the decision lands. You watch state cycle here — `firing` to `suppressed` and back.
- **[Prefect](tour.md#prefect-workflows-deployments-runs)** is the workflow orchestrator and the decision point. The webhook hands every alert payload to a Python flow (`quarantine_bgp_flow`) that walks a deterministic decision tree, picks one of four outcomes, writes an audit annotation, and — for the `proceed` outcome — asks Alertmanager to silence the alert for 20 minutes.
- **[Infrahub](tour.md#infrahub-source-of-truth)** is the source of truth the flow consults at decision time. "Is this peer expected to be up? Is this device in a maintenance window?" The answer to those two questions decides which of the four paths the flow takes — before metrics ever come into the picture.

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
