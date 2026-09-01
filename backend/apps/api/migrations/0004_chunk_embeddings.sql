-- Sprint 3: chunking + embeddings.
--
-- Fixes the embedding vector to the chosen model's dimensionality and adds an
-- ANN index. Model choice and the reasoning behind it are in PROGRESS.md:
-- jinaai/jina-embeddings-v2-small-en, 512 dimensions, 8192-token context.

-- paper_chunks is empty at this point (nothing wrote to it in Sprints 1-2), so
-- constraining the column is safe and needs no backfill.
ALTER TABLE paper_chunks
    ALTER COLUMN embedding TYPE vector(512);

-- Record what produced each vector. Without this, swapping the embedding model
-- would silently mix incompatible vector spaces in one index and quietly
-- degrade retrieval instead of failing.
ALTER TABLE paper_chunks
    ADD COLUMN embedding_model TEXT,
    ADD COLUMN embedded_at     TIMESTAMPTZ;

-- The model emits L2-normalized vectors, so cosine is the right operator.
-- HNSW over IVFFlat: IVFFlat needs a populated table to build meaningful
-- lists, and this table starts empty.
CREATE INDEX idx_paper_chunks_embedding
    ON paper_chunks
    USING hnsw (embedding vector_cosine_ops);

CREATE INDEX idx_paper_chunks_paper_id ON paper_chunks (paper_id);

-- Retrieval is scoped to a project, which means joining chunks -> papers.
CREATE INDEX idx_papers_project_status ON papers (project_id, status);

-- Token counts are populated from Sprint 3 onward (Sprint 2 left them NULL by
-- design, pending the tokenizer choice that the embedding model now settles).
