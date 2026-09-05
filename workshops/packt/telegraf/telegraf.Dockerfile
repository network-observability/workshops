ARG TELEGRAF_IMAGE=docker.io/telegraf:1.31

FROM $TELEGRAF_IMAGE

RUN apt-get update && apt-get install -y \
    curl \
    jq \
    python3 \
    python3-yaml \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
