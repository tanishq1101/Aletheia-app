# One deployable API image: ingestion, embeddings, reranking, and the research
# diagnostics all run in this backend. There is no separate "DL project" to
# deploy or coordinate with.
FROM python:3.12-slim

WORKDIR /app
COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Bake the two local ONNX models into the image.
#
# fastembed downloads the embedding model and the cross-encoder reranker
# (~150MB together) on first use and caches them to disk. Where the disk
# survives a restart that is a one-off cost paid by the first request after a
# deploy. On a host with an ephemeral filesystem — Cloudflare Containers hand a
# woken instance a fresh disk — it would be paid again on *every* cold start,
# inside the request path, on top of the ~25s the embedding model already takes
# to load. Baking them into an image layer turns that download into a local
# read. FASTEMBED_CACHE_PATH is set before the fetch so the runtime looks in
# the same place the build wrote to.
ENV FASTEMBED_CACHE_PATH=/opt/fastembed-cache
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('jinaai/jina-embeddings-v2-small-en')" \
 && python -c "from fastembed.rerank.cross_encoder import TextCrossEncoder; TextCrossEncoder('jinaai/jina-reranker-v1-turbo-en')"

COPY apps/api /app/apps/api
COPY models /app/models
COPY scripts/migrate.py /app/scripts/migrate.py
ENV PYTHONPATH=/app/apps/api \
    RESEARCH_MODELS_DIR=/app/models/research \
    LOCAL_STORAGE_DIR=/data/storage
EXPOSE 8000
# $PORT with a fallback, not a hardcoded 8000: every managed host (Render, Fly,
# Railway, Cloud Run) assigns the port and expects the process to bind it, and
# one that ignores it is marked unhealthy and killed with no useful error. The
# default keeps docker-compose and `docker run -p 8000:8000` unchanged.
CMD ["sh", "-c", "python /app/scripts/migrate.py && uvicorn main:app --app-dir /app/apps/api --host 0.0.0.0 --port ${PORT:-8000}"]
