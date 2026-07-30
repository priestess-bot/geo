FROM ghcr.io/astral-sh/uv:0.10.4 AS uv

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/apps/connector_worker/.venv/bin:$PATH \
    PYTHONPATH=/app/apps/connector_worker:/app/packages/geo_core

WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY packages/geo_core/pyproject.toml ./packages/geo_core/pyproject.toml
COPY apps/connector_worker/pyproject.toml apps/connector_worker/uv.lock \
  ./apps/connector_worker/

RUN --mount=type=cache,id=geo-connector-worker-uv,target=/root/.cache/uv \
    uv sync --project apps/connector_worker --frozen --no-dev && \
    addgroup --system --gid 10001 geo && \
    adduser --system --uid 10001 --ingroup geo --home /nonexistent --no-create-home geo && \
    chown -R geo:geo /app

COPY --chown=10001:10001 packages/geo_core ./packages/geo_core
COPY --chown=10001:10001 apps/connector_worker ./apps/connector_worker

USER 10001:10001
CMD ["python", "-m", "geo_connector_worker.entrypoint"]
