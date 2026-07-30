FROM ghcr.io/astral-sh/uv:0.10.4 AS uv

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/apps/browser_capture_worker/.venv/bin:$PATH \
    PYTHONPATH=/app/apps/browser_capture_worker:/app/packages/geo_core \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY packages/geo_core/pyproject.toml ./packages/geo_core/pyproject.toml
COPY apps/browser_capture_worker/pyproject.toml apps/browser_capture_worker/uv.lock \
  ./apps/browser_capture_worker/

RUN --mount=type=cache,id=geo-browser-capture-worker-uv,target=/root/.cache/uv \
    uv sync --project apps/browser_capture_worker --frozen --no-dev && \
    apps/browser_capture_worker/.venv/bin/playwright install --with-deps chromium && \
    addgroup --system --gid 10001 geo-browser && \
    adduser --system --uid 10001 --ingroup geo-browser \
      --home /nonexistent --no-create-home geo-browser && \
    chown -R geo-browser:geo-browser /app /ms-playwright

COPY --chown=10001:10001 packages/geo_core ./packages/geo_core
COPY --chown=10001:10001 apps/browser_capture_worker ./apps/browser_capture_worker

USER 10001:10001
CMD ["python", "-m", "geo_browser_capture_worker.entrypoint"]
