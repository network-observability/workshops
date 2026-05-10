---
title: Quickstart
---

{%
  include-markdown "../README.md"
  start="## Quickstart"
  end="## Available workshops"
  heading-offset=-1
%}

## What you should see

After `nobs autocon5 up` finishes, run `nobs autocon5 status` until every row reads `ok`. First boot pulls 3–5 GB of images, so the first run can take 5–10 minutes; subsequent restarts are seconds.

```text
Service              State   Health
─────────────────────────────────────
sonda-server         up      ok
sonda-srl1           up      ok
telegraf-srl1        up      ok
telegraf-srl2        up      ok
prometheus           up      ok
loki                 up      ok
grafana              up      ok
alertmanager         up      ok
infrahub-server      up      ok
prefect-server       up      ok
…
```

If any row is yellow or red after a couple of minutes, check the [troubleshooting page](https://github.com/network-observability/workshops/blob/main/workshops/autocon5/docs/troubleshooting.md) — common cases (Infrahub still seeding, OrbStack proxy, slow image pull) all have one-line fixes.

---

Once everything is `ok`, head to the [workshop overview](workshop/index.md) for the four-hour walkthrough.
