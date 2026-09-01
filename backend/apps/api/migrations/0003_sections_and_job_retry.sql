-- Sprint 2: PDF processing.
--
-- Adds section storage, per-project duplicate enforcement, and the columns a
-- retryable job needs.

-- === Duplicate detection ====================================================
-- Decision (PROGRESS.md): duplicates are per-project, not global. The same PDF
-- in a different project is legitimately a separate paper record.
--
-- Partial index so rows with a NULL sha256 (none today, but the column is
-- nullable) do not collide with each other.
DROP INDEX IF EXISTS idx_papers_sha256;

CREATE UNIQUE INDEX idx_papers_project_sha256
    ON papers (project_id, sha256)
    WHERE sha256 IS NOT NULL;

-- === Section storage ========================================================
-- Not in PRD Section 7 — see the flagged gap in PROGRESS.md. Section 12
-- requires "basic section info retained", and the only existing `section`
-- field lives on paper_chunks, which is a Sprint 3 entity.
--
-- Sections span pages, so this hangs off the paper and records where the
-- section starts rather than belonging to one page.
CREATE TABLE paper_sections (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id      UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    -- Nesting depth: 1 = "3 Methods", 2 = "3.1 Training setup".
    level         INTEGER NOT NULL DEFAULT 1 CHECK (level >= 1),
    -- Order within the paper, so sections can be listed as they appear.
    section_index INTEGER NOT NULL,
    -- 1-based page the heading was found on.
    start_page    INTEGER NOT NULL CHECK (start_page >= 1),
    -- Character offset of the heading within that page's cleaned_text, so
    -- Sprint 3 can map chunks back to the section they came from.
    start_offset  INTEGER,
    UNIQUE (paper_id, section_index)
);

CREATE INDEX idx_paper_sections_paper_id ON paper_sections(paper_id);

-- === Retryable jobs =========================================================
-- PRD Section 12 requires failed jobs to be diagnosable AND retryable.
ALTER TABLE processing_jobs
    ADD COLUMN attempts     INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    ADD COLUMN started_at   TIMESTAMPTZ,
    ADD COLUMN finished_at  TIMESTAMPTZ;

-- Jobs are looked up by paper to find the most recent attempt.
CREATE INDEX idx_processing_jobs_paper_created
    ON processing_jobs (paper_id, created_at DESC);

-- === Page text ==============================================================
-- paper_pages already exists from 0001. Guard the ordering assumption the
-- extractor relies on: page numbers are 1-based and contiguous per paper.
ALTER TABLE paper_pages
    ADD CONSTRAINT paper_pages_page_number_positive CHECK (page_number >= 1);
