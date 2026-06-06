---
title: Part 2 — Dashboards and Alerts
description: Mid-morning. A post-mortem email lands — last night's page lost ten minutes because a flap-rate panel didn't exist. Build it now, with thresholds matching the alert rule.
---

<div class="autocon5-section-hero" markdown>

<span class="autocon5-section-hero__badge">Part 2 of 4 · Mid-morning</span>

<h1 class="autocon5-section-hero__title">Dashboards and Alerts</h1>

<p class="autocon5-section-hero__subtitle">Build the panel last night's post-mortem said you needed.</p>

A post-mortem email lands. Last night's page lost ten minutes because a flap-rate panel didn't exist yet. You build it now — thresholds matching the actual alert rule, while the team is still in the room and your senior is at your shoulder. Dashboards and alerts are two faces of the same operational decision: the threshold you set on this panel is the same one Part 3's alert rule fires on.

<p class="autocon5-section-hero__meta">
  <span>~75 minutes</span>
  <span>Grafana panels with intent</span>
  <span>Alert thresholds aligned with the rule</span>
</p>

</div>

<figure class="section-preview" markdown>

![Interface Operational Status — what you augment in Part 2](../assets/screenshots/workshop-lab-interface-oper-light.png#only-light){ .screenshot loading=lazy }
![Interface Operational Status — what you augment in Part 2](../assets/screenshots/workshop-lab-interface-oper-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption>The Interface Operational Status panel from the Workshop Lab dashboard. The flap-rate panel you build in Part 2 lands right next to this one — same time range, same device variable, thresholds aligned with the alert rule.</figcaption>

</figure>

{%
  include-markdown "../../workshops/autocon5/guides/part-2-dashboards.md"
  start="## What you'll do here"
%}

<nav class="autocon5-nav-footer" markdown>

<a href="../part-1/">
  <span class="autocon5-nav-footer__label">← Previous</span>
  <span class="autocon5-nav-footer__title">Part 1 — Telemetry and queries</span>
</a>

<a class="autocon5-nav-footer__next" href="../part-3/">
  <span class="autocon5-nav-footer__label">Next →</span>
  <span class="autocon5-nav-footer__title">Part 3 — Alert response, Automation and AI</span>
</a>

</nav>
