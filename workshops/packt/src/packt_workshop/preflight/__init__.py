"""Three-layer preflight regression check for the packt workshop.

Exposed via `nobs packt preflight`. Layer A waits for both pipelines
to populate, Layer B validates every panel via Grafana's /api/ds/query,
Layer C captures per-panel screenshots through headless Chromium.
"""
