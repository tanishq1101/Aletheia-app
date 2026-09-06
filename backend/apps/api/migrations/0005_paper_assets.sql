-- Multimodal PDF sprint: structured figures, tables, and equation candidates.

CREATE TABLE paper_assets (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id     UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    page_id      UUID NOT NULL REFERENCES paper_pages(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL CHECK (kind IN ('figure', 'table', 'equation')),
    asset_index  INTEGER NOT NULL CHECK (asset_index >= 0),
    caption      TEXT,
    content_text TEXT,
    storage_path TEXT,
    bbox         JSONB NOT NULL,
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (paper_id, kind, asset_index)
);

CREATE INDEX idx_paper_assets_paper_page
    ON paper_assets (paper_id, page_id);

CREATE INDEX idx_paper_assets_kind
    ON paper_assets (paper_id, kind);
