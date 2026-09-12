-- Reproducibility scoring (PRD Section 3.2: "a reproducibility score based on
-- whether dataset, hyperparameters, seeds, and code are actually disclosed").
--
-- The report is about disclosure, which is a property of the paper's text and
-- is checkable. It is not a claim that the results were reproduced — nothing
-- here runs any code, and the UI says so.

CREATE TABLE reproducibility_reports (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id      UUID NOT NULL UNIQUE REFERENCES papers(id) ON DELETE CASCADE,
    -- 0-1, computed from the per-dimension checks below, not model-reported.
    score         REAL NOT NULL,
    -- Links found in the paper's own text (github/gitlab/doi/dataset), plus
    -- whatever the GitHub API returned for the first repo. NULL when the paper
    -- links no code, which is itself a finding.
    repo_metadata JSONB,
    links         JSONB NOT NULL DEFAULT '[]'::jsonb,
    model         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE reproducibility_checks (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id  UUID NOT NULL REFERENCES reproducibility_reports(id)
               ON DELETE CASCADE,
    dimension  TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('disclosed', 'partial', 'missing')),
    rationale  TEXT NOT NULL,
    -- Resolved from evidence IDs the backend issued, exactly as elsewhere: a
    -- checklist item without its evidence is an opinion.
    citations  JSONB NOT NULL DEFAULT '[]'::jsonb,
    check_index INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX reproducibility_checks_report_idx
    ON reproducibility_checks (report_id, check_index);
