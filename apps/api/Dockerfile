FROM ghcr.io/astral-sh/uv:0.10.4 AS uv

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app:/app/packages/geo_core:/app/apps/api

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock alembic.ini ./
COPY packages/geo_core ./packages/geo_core
COPY apps/api ./apps/api
COPY infra/db/alembic ./infra/db/alembic
COPY workers ./workers
COPY scripts ./scripts

RUN uv sync --frozen --no-dev && \
    addgroup --system --gid 10001 geo && \
    adduser --system --uid 10001 --ingroup geo --home /nonexistent --no-create-home geo && \
    chown -R geo:geo /app

USER 10001:10001

EXPOSE 8000
CMD ["uvicorn", "geo_api.internal_app:app", "--host", "0.0.0.0", "--port", "8000"]
