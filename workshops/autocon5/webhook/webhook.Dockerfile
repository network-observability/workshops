ARG PYTHON_VER=3.10

FROM tiangolo/uvicorn-gunicorn-fastapi:python${PYTHON_VER}-slim AS webhook

RUN apt-get update && \
    apt-get upgrade -y && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y git && \
    apt-get autoremove -y && \
    apt-get clean all && \
    rm -rf /var/lib/apt/lists/* && \
    pip --no-cache-dir install --upgrade pip wheel

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY ./webhook/pyproject.toml /app/

RUN pip --no-cache-dir install .

# Project code last so we don't bust the dep cache on every edit.
COPY ./webhook/app/ /app/app/

WORKDIR /
