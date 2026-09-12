-- Runtime-tunable settings.
--
-- Retrieval knobs are the difference between an answer built on 6 evidence
-- blocks and one built on 12, and the PRD commits to benchmarking them. They
-- were env-only, so changing one meant restarting the API. These override the
-- environment defaults at request time; anything NULL falls back to .env.
--
-- Secrets are deliberately absent: API keys stay in the environment, and the
-- settings endpoint reports only whether one is configured.

CREATE TABLE app_settings (
    -- One row, enforced. Settings are global while there is no auth.
    id                 BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
    search_top_k       INTEGER CHECK (search_top_k BETWEEN 1 AND 100),
    rerank_top_k       INTEGER CHECK (rerank_top_k BETWEEN 1 AND 20),
    context_max_tokens INTEGER CHECK (context_max_tokens BETWEEN 500 AND 32000),
    llm_model          TEXT,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO app_settings (id) VALUES (TRUE);
