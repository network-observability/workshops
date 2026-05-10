---
title: Part 1 — Telemetry and queries
description: Morning of your first deep day on the rotation. Walk the lab's metrics and logs with your senior buddy. Find the broken peer. Bridge a metric anomaly to the log line that explains it.
---

<div class="autocon5-section-hero" markdown>

<span class="autocon5-section-hero__badge">Part 1 of 4 · Morning</span>

<h1 class="autocon5-section-hero__title">Telemetry and queries</h1>

<p class="autocon5-section-hero__subtitle">Find the broken peer. Bridge metric → log. Build the baseline.</p>

Your senior buddy walks you through the lab's telemetry shape — what *normal* looks like, where the broken things hide, how to bridge a metric anomaly to the log line that explains it. By the end you have a baseline you can compare every future triage against.

<p class="autocon5-section-hero__meta">
  <span>~75 minutes</span>
  <span>PromQL + LogQL from first principles</span>
  <span>Live data, real-shape telemetry</span>
</p>

</div>

<figure class="section-preview" markdown>

[![Device Health for srl1 — the dashboard you query in Part 1](../assets/screenshots/device-health-srl1.png){ .screenshot loading=lazy }](../assets/screenshots/device-health-srl1.png)

<figcaption>Device Health for srl1 — the dashboard you'll query against. The interface state matrix and BGP-peer panels are where the broken peer lives. Click for full size.</figcaption>

</figure>

{%
  include-markdown "../../workshops/autocon5/guides/part-1-telemetry-and-queries.md"
  start="## What you'll do here"
%}

<nav class="autocon5-nav-footer" markdown>

<div class="autocon5-nav-footer__placeholder" aria-hidden="true"></div>

<a class="autocon5-nav-footer__next" href="../part-2/">
  <span class="autocon5-nav-footer__label">Next →</span>
  <span class="autocon5-nav-footer__title">Part 2 — Dashboards</span>
</a>

</nav>
