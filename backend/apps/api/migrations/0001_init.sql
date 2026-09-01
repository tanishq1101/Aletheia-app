-- Phase 1 schema (PRD Section 7).
-- Sprint 1 writes to: users, projects, papers, processing_jobs.
-- The remaining tables are created as shells so the schema is coherent, but
-- NOTHING in Sprint 1 reads or writes them. See PROGRESS.md.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- === Sprint 1: live tables ==================================================

CREATE TABLE users (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE projects (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL CHECK (length(trim(name)) > 0),
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_projects_user_id ON projects(user_id);

CREATE TABLE papers (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title        TEXT,
    filename     TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    sha256       TEXT,
    page_count   INTEGER,
    authors      TEXT[],
    abstract     TEXT,
    status       TEXT NOT NULL DEFAULT 'uploaded'
                 CHECK (status IN ('uploaded', 'processing', 'ready', 'failed')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ
);

CREATE INDEX idx_papers_project_id ON papers(project_id);
-- Not a uniqueness constraint: duplicate detection is a Sprint 2 deliverable.
-- This index only makes that future lookup cheap.
CREATE INDEX idx_papers_sha256 ON papers(sha256);

CREATE TABLE processing_jobs (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id   UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    status     TEXT NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    stage      TEXT,
    progress   REAL NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 1),
    error      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_processing_jobs_paper_id ON processing_jobs(paper_id);
CREATE INDEX idx_processing_jobs_status ON processing_jobs(status);

-- === Later-sprint shells: created, but unused in Sprint 1 ===================

CREATE TABLE paper_pages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id        UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    page_number     INTEGER NOT NULL,
    raw_text        TEXT,
    cleaned_text    TEXT,
    character_count INTEGER,
    token_count     INTEGER,
    UNIQUE (paper_id, page_number)
);

CREATE TABLE paper_chunks (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id     UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    page_id      UUID REFERENCES paper_pages(id) ON DELETE CASCADE,
    section      TEXT,
    chunk_index  INTEGER NOT NULL,
    content      TEXT NOT NULL,
    token_count  INTEGER,
    -- Dimensionality is deliberately left unspecified until the embedding
    -- provider is chosen in Sprint 3. No ANN index yet: building one over an
    -- empty table would be guesswork about a model we have not picked.
    embedding    vector,
    start_offset INTEGER,
    end_offset   INTEGER,
    metadata     JSONB,
    UNIQUE (paper_id, chunk_index)
);

CREATE TABLE conversations (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    paper_id   UUID REFERENCES papers(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE citations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id       UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    paper_id         UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    page_id          UUID REFERENCES paper_pages(id) ON DELETE SET NULL,
    chunk_id         UUID REFERENCES paper_chunks(id) ON DELETE SET NULL,
    citation_label   TEXT,
    support_metadata JSONB
);
