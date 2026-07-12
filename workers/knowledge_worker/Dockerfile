FROM python:3.12-slim

WORKDIR /app

COPY apps/api/knowledge-worker-requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY packages/geno_core ./packages/geno_core
COPY apps/api ./apps/api
COPY workers ./workers
COPY scripts ./scripts

ENV PYTHONPATH=/app:/app/packages/geno_core:/app/apps/api

CMD ["python", "workers/knowledge_worker/run_knowledge_pipeline.py", "--loop-once"]
