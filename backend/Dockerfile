# One deployable API image: ingestion, embeddings, reranking, and the research
# diagnostics all run in this backend. There is no separate "DL project" to
# deploy or coordinate with.
FROM python:3.12-slim

WORKDIR /app
COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY apps/api /app/apps/api
COPY models /app/models
COPY scripts/migrate.py /app/scripts/migrate.py
ENV PYTHONPATH=/app/apps/api \
    RESEARCH_MODELS_DIR=/app/models/research \
    LOCAL_STORAGE_DIR=/data/storage
EXPOSE 8000
CMD ["sh", "-c", "python /app/scripts/migrate.py && uvicorn main:app --app-dir /app/apps/api --host 0.0.0.0 --port 8000"]
