# syntax=docker/dockerfile:1.10

# Immutable upstream inputs reviewed on 2026-07-27. The Python build image and
# the Wolfi runtime root are pinned independently so both supply-chain inputs
# remain auditable while the final image stays package-manager free.
ARG NODE_BASE=node:22-alpine3.22@sha256:cd7807368cf24826297cbad5dca1a44972ccfd770647db52a8c7589eb4599ac8
ARG PYTHON_BUILD_BASE=cgr.dev/chainguard/python:latest-dev@sha256:7a568bcee42666f73f041645a41c913ce1d442f4c24cf6019bc543a90820e531
ARG WOLFI_BASE=cgr.dev/chainguard/wolfi-base:latest@sha256:003627df3c1e1bba0c4116afcddb314aca9594ee2328c7e876a8081a6c988b2e

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
FROM ${PYTHON_BUILD_BASE} AS python-deps

USER root
ARG UV_VERSION
ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/sbin:/bin \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN set -eux; \
    python --version | grep -F 'Python 3.14.6'; \
    uv --version | grep -F "uv ${UV_VERSION}"; \
    apk add --no-cache \
      libpq-18=18.4-r7 \
      libxml2-dev=2.15.3-r3 \
      libxslt=1.1.45-r3 \
      libxslt-dev=1.1.45-r3 \
      postgresql-18-dev=18.4-r7 \
      zlib-dev=1.3.2-r3; \
    python -m venv --without-pip "$VIRTUAL_ENV"

COPY backend/requirements-production.lock /tmp/requirements-production.lock
RUN set -eux; \
    uv pip install \
      --python "$VIRTUAL_ENV/bin/python" \
      --requirement /tmp/requirements-production.lock \
      --require-hashes \
      --no-deps \
      --no-cache; \
    "$VIRTUAL_ENV/bin/python" -c "import sys; import aiohttp, black, fastapi, huggingface_hub, orjson, pgvector, psycopg, pydantic, sqlalchemy, typer; from lxml import etree; assert sys.version_info[:3] == (3, 14, 6); assert sys.prefix == '/opt/venv'; assert psycopg.pq.__impl__ == 'c'"; \
    rm -f /tmp/requirements-production.lock

######## Minimal runtime assembly ############################################
FROM ${WOLFI_BASE} AS runtime-assembly

USER root
ARG UID
ARG GID
ARG USE_PERMISSION_HARDENING

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/sbin:/bin

RUN set -eux; \
    test "$UID" -ne 0; \
    test "$GID" -ne 0; \
    apk add --no-cache \
      bash=5.3-r12 \
      libpq-18=18.4-r7 \
      libxml2-16=2.15.3-r3 \
      libxslt=1.1.45-r3 \
      python-3.14=3.14.6-r4; \
    apk del wolfi-base wolfi-keys apk-tools; \
    ! command -v apk; \
    install -d -o "$UID" -g "$GID" -m 0750 /app/backend/data; \
    install -d -o "$UID" -g "$GID" -m 0750 /home/app/.cache; \
    rm -rf /var/cache/apk/*

COPY --from=python-deps /opt/venv /opt/venv
COPY --chown=$UID:$GID --from=frontend-build /app/build /app/build
COPY --chown=$UID:$GID --from=frontend-build /app/CHANGELOG.md /app/CHANGELOG.md
COPY --chown=$UID:$GID --from=frontend-build /app/package.json /app/package.json
COPY --chown=$UID:$GID backend/ /app/backend/

RUN set -eux; \
    install -d -o "$UID" -g "$GID" -m 0750 /app/backend/data; \
    if [ "$USE_PERMISSION_HARDENING" = "true" ]; then \
      chgrp -R 0 /app /home/app; \
      chmod -R g+rwX /app /home/app; \
      find /app /home/app -type d -exec chmod g+s {} +; \
    fi; \
    ! command -v git; \
    ! command -v curl; \
    ! command -v jq; \
    ! command -v ffmpeg; \
    ! command -v gcc; \
    ! command -v make; \
    ! command -v cargo; \
    ! command -v rustc; \
    ! command -v apk; \
    ! "$VIRTUAL_ENV/bin/python" -m pip --version; \
    "$VIRTUAL_ENV/bin/python" -c "import sys; import aiohttp, black, fastapi, huggingface_hub, orjson, pgvector, psycopg, pydantic, sqlalchemy, typer; from lxml import etree; assert sys.version_info[:3] == (3, 14, 6); assert sys.prefix == '/opt/venv'; assert psycopg.pq.__impl__ == 'c'"

######## Final package-manager-free image ####################################
FROM scratch AS runtime

ARG BUILD_HASH
ARG PYTHON_BUILD_BASE
ARG WOLFI_BASE
ARG UID
ARG GID

LABEL org.opencontainers.image.base.name="cgr.dev/chainguard/wolfi-base:latest" \
      org.opencontainers.image.base.digest="sha256:003627df3c1e1bba0c4116afcddb314aca9594ee2328c7e876a8081a6c988b2e" \
      io.ai4s.material-graph.python-build-base="${PYTHON_BUILD_BASE}" \
      io.ai4s.material-graph.runtime-base="${WOLFI_BASE}"

ENV ENV=prod \
    PORT=8080 \
    HOME=/home/app \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/sbin:/bin \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
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
COPY --from=runtime-assembly / /

EXPOSE 8080
VOLUME ["/app/backend/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import json, os, urllib.request; response = urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8080\")}/health', timeout=4); assert json.load(response).get('status') is True"]

USER $UID:$GID
CMD ["bash", "start.sh"]
