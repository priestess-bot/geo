FROM python:3.12-slim

WORKDIR /app

COPY apps/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY packages/geo_core ./packages/geo_core
COPY apps/api ./apps/api
COPY workers ./workers
COPY scripts ./scripts

ENV PYTHONPATH=/app:/app/packages/geo_core:/app/apps/api

CMD ["uvicorn", "geo_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
