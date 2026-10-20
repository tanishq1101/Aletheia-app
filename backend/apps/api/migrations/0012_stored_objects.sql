-- Object storage inside Postgres, for STORAGE_BACKEND=postgres.
--
-- A serverless deployment has no disk that outlives a request, and asking for
-- an R2 account just to hold a demo library's PDFs is a second service to
-- provision before anything works. This table lets the database the app
-- already needs hold the bytes too. It is the right trade for a small library
-- and the wrong one for a large one: every stored file counts against the
-- database's size quota. Move to R2 (scripts/backfill_r2.py) when it matters.

CREATE TABLE IF NOT EXISTS stored_objects (
    key         TEXT PRIMARY KEY,
    data        BYTEA NOT NULL,
    size_bytes  INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
