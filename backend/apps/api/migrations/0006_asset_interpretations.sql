CREATE TABLE asset_interpretations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id        UUID NOT NULL REFERENCES paper_assets(id) ON DELETE CASCADE,
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    interpretation  TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (asset_id, model, prompt_version)
);

CREATE INDEX idx_asset_interpretations_asset
    ON asset_interpretations(asset_id);
