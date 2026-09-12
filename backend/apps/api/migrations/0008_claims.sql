-- Claim-level verification (PRD Section 4: "the system doesn't just cite a
-- source, it checks whether the claim is actually supported by that source").
--
-- A claim is stored separately from its verdict because the same claim is
-- checked against several papers in the cross-paper matrix: one claim, many
-- verdicts, each with its own evidence.

CREATE TABLE claims (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    -- The paper the claim was extracted from. NULL for a claim the user typed.
    paper_id    UUID REFERENCES papers(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'extracted'
                CHECK (source IN ('extracted', 'manual')),
    claim_index INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX claims_project_idx ON claims (project_id, created_at DESC);
CREATE INDEX claims_paper_idx ON claims (paper_id, claim_index);

CREATE TABLE claim_verifications (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id       UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    -- Whose evidence was used. NULL means the whole project's.
    paper_id       UUID REFERENCES papers(id) ON DELETE CASCADE,
    verdict        TEXT NOT NULL
                   CHECK (verdict IN ('supported', 'contradicted', 'insufficient')),
    -- Model-reported, 0-1. NOT a calibrated probability, and labelled as such
    -- wherever it is shown (PRD Section 9: never fake a metric).
    confidence     REAL,
    rationale      TEXT NOT NULL,
    -- Citations resolved from evidence IDs the backend issued, same as
    -- messages. Stored inline: a verdict's evidence is only ever read with it.
    citations      JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    model          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One current verdict per claim per paper. NULLs are distinct in a plain
-- UNIQUE constraint, which would let project-wide verdicts pile up, so the
-- key is built over a coalesced paper_id instead.
CREATE UNIQUE INDEX claim_verifications_unique_scope_idx
    ON claim_verifications (
        claim_id,
        COALESCE(paper_id, '00000000-0000-0000-0000-000000000000'::uuid)
    );
