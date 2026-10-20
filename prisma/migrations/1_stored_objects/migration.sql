-- Mirrors backend/apps/api/migrations/0012_stored_objects.sql. IF NOT EXISTS
-- because whichever of the two migrators reaches a database first creates it.
CREATE TABLE IF NOT EXISTS "public"."stored_objects" (
    "key" TEXT NOT NULL,
    "data" BYTEA NOT NULL,
    "size_bytes" INTEGER NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT now(),

    CONSTRAINT "stored_objects_pkey" PRIMARY KEY ("key")
);
