# AutoCon5 workshop — operator docs

These docs are for the people who **maintain** the AutoCon5 workshop: the folks who'll extend a scenario, debug a stack on a venue laptop, hand the workshop off to a colleague, or fork it into a different conference.
They assume you've already followed the attendee [README](../README.md) at least once.

If you just want to run the workshop, you don't need anything in here.

## What's in here

- [`architecture.svg`](architecture.svg) — the visual the attendee README embeds.
  Useful as a standalone reference when you're tracing a path through compose.
- [`env-lifecycle.md`](env-lifecycle.md) — who creates `.env`, who reads it, why three different consumers all need a copy, and the one nuance (`infrahub-server` vs `localhost`) that bites operators on the host.
- [`repo-layout.md`](repo-layout.md) — what every directory under `workshops/autocon5/` contributes and which docs cover it.
- [`troubleshooting.md`](troubleshooting.md) — the recurring failure modes, why they happen, and the exact recovery commands.
- [`../infrahub/README.md`](../infrahub/README.md) — the source-of-truth schema walkthrough.
  Read this before extending the schema or adding new alert/automation logic that depends on intent.
  It's the gold standard for the depth this docs/ folder aims at.

## Conventions

- All operator docs link with **relative paths** from this folder, so they render correctly on GitHub and work offline.
- The attendee-facing README is intentionally thin.
  When you find yourself wanting to add operator detail to it, write a doc here and link from the README's "Going deeper" section instead.
- Architecture diagrams live alongside the docs that reference them (currently just `architecture.svg`).
