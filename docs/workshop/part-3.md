---
title: Part 3 — Alerts, automation, AI
description: Late morning. A real alert lands and your senior narrates how the workflow handles it. Walk the four canonical paths, toggle the AI RCA step.
---

<div class="autocon5-section-hero" markdown>

<span class="autocon5-section-hero__badge">Part 3 of 4 · Late morning</span>

<h1 class="autocon5-section-hero__title">Alerts, automation, AI</h1>

<p class="autocon5-section-hero__subtitle">Watch a real alert flow through Alertmanager → Prefect → Infrahub.</p>

A real alert lands while your senior narrates. Walk the four canonical paths the workflow handles, toggle the AI RCA step, and decide which paths you'd trust the LLM narrative on at 02:14. Your senior signs off as the lunch break lands — you're ready to take primary on the rotation tomorrow.

<p class="autocon5-section-hero__meta">
  <span>~75 minutes</span>
  <span>Four canonical paths walked end-to-end</span>
  <span>Optional AI-assisted RCA toggle</span>
</p>

</div>

<figure class="section-preview" markdown>

![Currently firing alerts — Alertmanager state during a cascade](../assets/screenshots/workshop-home-firing-alerts-light.png#only-light){ .screenshot loading=lazy }
![Currently firing alerts — Alertmanager state during a cascade](../assets/screenshots/workshop-home-firing-alerts-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption>What lands in Alertmanager when the cascade kicks off — severity, device, peer, interface, the canonical labels. This table is the input the Prefect automation reasons over in each of the four paths you walk in Part 3.</figcaption>

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
