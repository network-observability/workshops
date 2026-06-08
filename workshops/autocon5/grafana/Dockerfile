# Custom Grafana image with the workshop's plugins baked in.
#
# Why this exists: vanilla Grafana installs plugins from grafana.com at startup
# (via GF_INSTALL_PLUGINS), which requires reliable internet on the host running
# the lab. Conference / workshop venues often have flaky wifi — and so does a
# plane seat at 35,000 ft. Baking the plugins into the image at build time
# moves the "needs internet" step to `docker compose build`, which the student
# runs once at home (or CI runs once and publishes the image), after which the
# lab boots fully offline.

FROM grafana/grafana:13.0.1-security-01

# Only the Infinity datasource is actually referenced by the provisioned
# workshop dashboards (device-health.json uses it for Infrahub GraphQL).
# The previously-listed `volkovlabs-echarts-panel` and `natel-discrete-panel`
# never appeared in any dashboard (verified via git history) — and
# natel-discrete-panel is Angular-based, which Grafana 13 has disabled.
# Trimming to just what's used keeps the build small, fast, and offline-safe.
RUN /usr/share/grafana/bin/grafana cli plugins install yesoreyeram-infinity-datasource
