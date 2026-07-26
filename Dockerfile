# syntax=docker/dockerfile:1.10

# Immutable upstream inputs reviewed on 2026-07-27. The Python image is built
# from Debian Trixie; its upstream Debian root is recorded separately so both
# layers of the base-image chain remain auditable.
ARG NODE_BASE=node:22-alpine3.22@sha256:cd7807368cf24826297cbad5dca1a44972ccfd770647db52a8c7589eb4599ac8
ARG PYTHON_BASE=python:3.15.0b4-slim-trixie@sha256:876977512a3f291014c1ffcc48cd6a05dcee034df0ebb9cd84f066355f575d44
ARG DEBIAN_BASE=debian:trixie-slim@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd

ARG BUILD_HASH=dev-build
ARG UID=10001
ARG GID=10001
ARG UV_VERSION=0.11.32
ARG USE_PERMISSION_HARDENING=false

######## Frontend builder ####################################################
FROM --platform=$BUILDPLATFORM ${NODE_BASE} AS frontend-build

ARG BUILD_HASH
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --force

COPY . .
ENV APP_BUILD_HASH=${BUILD_HASH}
RUN npm run build

######## Python dependency builder ##########################################
FROM ${PYTHON_BASE} AS python-deps

ARG UV_VERSION
ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      build-essential \
      cargo \
      libpq-dev \
      libxml2-dev \
      libxslt1-dev \
      pkg-config \
      rustc; \
    python -m pip install --no-cache-dir "uv==${UV_VERSION}"; \
    python -m venv --without-pip "$VIRTUAL_ENV"; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

COPY backend/requirements-production.lock /tmp/requirements-production.lock
RUN set -eux; \
    uv pip install \
      --python "$VIRTUAL_ENV/bin/python" \
      --requirement /tmp/requirements-production.lock \
      --require-hashes \
      --no-deps \
      --no-cache; \
    "$VIRTUAL_ENV/bin/python" -c "import aiohttp, fastapi, pgvector, psycopg, pydantic, sqlalchemy; from lxml import etree; assert psycopg.pq.__impl__ == 'c'"; \
    rm -f /tmp/requirements-production.lock

######## Minimal runtime #####################################################
FROM ${PYTHON_BASE} AS runtime

ARG BUILD_HASH
ARG DEBIAN_BASE
ARG UID
ARG GID
ARG USE_PERMISSION_HARDENING

LABEL org.opencontainers.image.base.name="docker.io/library/python:3.15.0b4-slim-trixie" \
      io.ai4s.material-graph.debian-base="${DEBIAN_BASE}"

ENV ENV=prod \
    PORT=8080 \
    HOME=/home/app \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOCKER=true \
    USE_SLIM_DOCKER=true \
    VECTOR_DB=pgvector \
    BYPASS_PYDUB_PREPROCESSING=true \
    OLLAMA_BASE_URL=/ollama \
    OPENAI_API_BASE_URL="" \
    OPENAI_API_KEY="" \
    WEBUI_SECRET_KEY="" \
    WEBUI_SECRET_KEY_FILE=/app/backend/data/.webui_secret_key \
    SCARF_NO_ANALYTICS=true \
    DO_NOT_TRACK=true \
    ANONYMIZED_TELEMETRY=false \
    WEBUI_BUILD_VERSION=${BUILD_HASH}

WORKDIR /app/backend

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends libpq5 libxml2 libxslt1.1; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*; \
    test "$UID" -ne 0; \
    test "$GID" -ne 0; \
    addgroup --gid "$GID" app; \
    adduser --uid "$UID" --gid "$GID" --home "$HOME" --disabled-password --gecos "" app; \
    install -d -o "$UID" -g "$GID" -m 0750 /app/backend/data; \
    install -d -o "$UID" -g "$GID" -m 0750 "$HOME/.cache"; \
    rm -rf \
      /usr/local/bin/pip \
      /usr/local/bin/pip3 \
      /usr/local/bin/pip3.15 \
      /usr/local/lib/python3.15/site-packages/pip* \
      /usr/local/lib/python3.15/site-packages/setuptools* \
      /usr/local/lib/python3.15/site-packages/wheel*

COPY --from=python-deps /opt/venv /opt/venv
COPY --chown=$UID:$GID --from=frontend-build /app/build /app/build
COPY --chown=$UID:$GID --from=frontend-build /app/CHANGELOG.md /app/CHANGELOG.md
COPY --chown=$UID:$GID --from=frontend-build /app/package.json /app/package.json
COPY --chown=$UID:$GID backend/ /app/backend/

RUN set -eux; \
    install -d -o "$UID" -g "$GID" -m 0750 /app/backend/data; \
    if [ "$USE_PERMISSION_HARDENING" = "true" ]; then \
      chgrp -R 0 /app "$HOME"; \
      chmod -R g+rwX /app "$HOME"; \
      find /app "$HOME" -type d -exec chmod g+s {} +; \
    fi; \
    ! command -v git; \
    ! command -v curl; \
    ! command -v jq; \
    ! command -v ffmpeg; \
    ! command -v gcc; \
    ! command -v make; \
    ! command -v cargo; \
    ! command -v rustc; \
    "$VIRTUAL_ENV/bin/python" -c "import aiohttp, fastapi, pgvector, psycopg, pydantic, sqlalchemy; from lxml import etree; assert psycopg.pq.__impl__ == 'c'"

EXPOSE 8080
VOLUME ["/app/backend/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import json, os, urllib.request; response = urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8080\")}/health', timeout=4); assert json.load(response).get('status') is True"]

USER $UID:$GID
CMD ["bash", "start.sh"]
