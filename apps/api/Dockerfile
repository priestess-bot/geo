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
COPY benchmarks/f019/selection.json ./benchmarks/f019/selection.json
COPY benchmarks/f019/reports/2026-07-19/project-native.json ./benchmarks/f019/reports/2026-07-19/project-native.json
COPY prompt ./prompt
COPY infra/db/alembic ./infra/db/alembic
COPY scripts/provision_dev_database.py scripts/provision_initial_owner.py \
     scripts/bootstrap_workflow_c_artifact_keyring.py \
     scripts/bootstrap_deepseek_prompt_runtime.py \
     scripts/bootstrap_prompt_workspace_flows.py \
     scripts/manage_dify_workflows.py \
     scripts/render_dify_workflow_dsls.py \
     scripts/staging_alert_smtp_sink.py scripts/staging_alert_webhook_sink.py ./scripts/

RUN --mount=type=cache,id=geo-api-uv,target=/root/.cache/uv \
    uv sync --frozen --no-dev && \
    addgroup --system --gid 10001 geo && \
    adduser --system --uid 10001 --ingroup geo --home /nonexistent --no-create-home geo && \
    chown -R geo:geo /app

USER 10001:10001

EXPOSE 8000
CMD ["uvicorn", "geo_api.internal_app:app", "--host", "0.0.0.0", "--port", "8000"]
