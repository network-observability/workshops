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

# The same three plugins the workshop dashboards depend on:
#   - volkovlabs-echarts-panel       (eCharts visualisations)
#   - natel-discrete-panel           (Interface Operational Status timeline)
#   - yesoreyeram-infinity-datasource (Infrahub GraphQL queries from Grafana)
RUN grafana-cli plugins install volkovlabs-echarts-panel \
 && grafana-cli plugins install natel-discrete-panel \
 && grafana-cli plugins install yesoreyeram-infinity-datasource
