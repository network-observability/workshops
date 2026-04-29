"""Three-layer preflight regression check for the autocon5 workshop.

Exposed via `nobs autocon5 preflight`. Layer A waits for both pipelines
to populate, Layer B validates every panel via Grafana's /api/ds/query,
Layer C captures per-panel screenshots through headless Chromium.
"""
