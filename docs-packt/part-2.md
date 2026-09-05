---
title: Part 2 — Dashboards and alerts (demo)
description: A guided demo. A post-mortem email lands — we build the flap-rate panel with thresholds matching the alert rule, then walk the same alert from firing to silenced.
---

<div class="packt-section-hero" markdown>

<span class="packt-section-hero__badge">Part 2 of 3 · ~20 min · guided demo</span>

<h1 class="packt-section-hero__title">Dashboards and alerts</h1>

<p class="packt-section-hero__subtitle">We drive; you watch. Nothing here is required for Part 3.</p>

A post-mortem email lands: last night's page lost ten minutes because a flap-rate panel didn't exist yet. We build it on screen — thresholds matching the actual alert rule — then follow the same alert from panel to firing to silenced. Follow along on your own Grafana if you like, but if your stack is slow or you'd simply rather watch, that's the intended way to take this block.

<p class="packt-section-hero__meta">
  <span>No hands-on</span>
  <span>Thresholds aligned with the alert rule</span>
  <span>Full ten-step build on the take-home page</span>
</p>

</div>

<figure class="section-preview" markdown>

![Flap rate panel during a flap](assets/screenshots/flap-rate-flapping-light.png#only-light){ .screenshot loading=lazy }
![Flap rate panel during a flap](assets/screenshots/flap-rate-flapping-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption>The panel we build, mid-flap. Orange line at 2 is the early heads-up; red at 3 is the exact condition the <code>PeerInterfaceFlapping</code> alert rule fires on.</figcaption>

</figure>

{%
  include-markdown "../workshops/packt/guides/part-2-dashboards.md"
  start="## What you'll do here"
%}

<nav class="packt-nav-footer" markdown>

<a href="../part-1/">
  <span class="packt-nav-footer__label">← Previous</span>
  <span class="packt-nav-footer__title">Part 1 — Telemetry and queries</span>
</a>

<a class="packt-nav-footer__next" href="../part-3/">
  <span class="packt-nav-footer__label">Next →</span>
  <span class="packt-nav-footer__title">Part 3 — Alerts, automation and AI</span>
</a>

</nav>
