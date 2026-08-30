# Phase 2 cloud image: intentionally excludes Daily Report, WeChat, local STT,
# CUDA/RTX and all runtime data. Build context is the repository root.
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    MIRU_PROFILE=cloud \
    MIRU_SERVER_CONFIG=/app/config/settings.cloud.example.yaml

WORKDIR /app

RUN groupadd --system --gid 10001 miru \
    && useradd --system --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin miru \
    && mkdir -p /app/config/persona /app/data \
    && chown -R miru:miru /app

COPY deploy/requirements-cloud.txt /tmp/requirements-cloud.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-cloud.txt \
    && rm -f /tmp/requirements-cloud.txt

# Copy only portable application code and non-secret templates. Do not copy
# server/data, settings.yaml, .env, model files, WeChat snapshots, or the
# Flutter/Daily Report trees.
COPY products/mobile-assistant/server/miru_server /app/miru_server
COPY products/mobile-assistant/server/config/pricing.yaml /app/config/pricing.yaml
COPY products/mobile-assistant/server/config/persona.example.yaml /app/config/persona/miru.yaml
COPY deploy/settings.cloud.example.yaml /app/config/settings.cloud.example.yaml

RUN chown -R miru:miru /app
USER miru

EXPOSE 8765
STOPSIGNAL SIGTERM

CMD ["python", "-m", "miru_server", "--profile", "cloud", "--host", "0.0.0.0", "--port", "8765"]
