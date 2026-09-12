-- Baseline: the schema as it stood before Prisma took over migrations.
--
-- Generated with `prisma migrate diff --from-empty --to-config-datasource`,
-- then corrected. Prisma's output is NOT a faithful copy of this database: it
-- omits every CHECK constraint, rewrites the HNSW vector index as a btree
-- (which pgvector cannot build at all), and strips the WHERE clause off the
-- partial sha256 index. Those objects are appended below, dumped straight from
-- the catalog by backend/scripts/dump_raw_objects.py.
--
-- Applied to an existing database with `prisma migrate resolve --applied 0_init`.

-- CreateSchema
CREATE SCHEMA IF NOT EXISTS "public";

-- CreateExtension
CREATE EXTENSION IF NOT EXISTS "pgcrypto" WITH SCHEMA "public" VERSION "1.3";

-- CreateExtension
CREATE EXTENSION IF NOT EXISTS "plpgsql" WITH SCHEMA "pg_catalog" VERSION "1.0";

-- CreateExtension
CREATE EXTENSION IF NOT EXISTS "vector" WITH SCHEMA "public" VERSION "0.8.6";

-- CreateTable
CREATE TABLE "public"."app_settings" (
    "id" BOOLEAN NOT NULL DEFAULT true,
    "search_top_k" INTEGER,
    "rerank_top_k" INTEGER,
    "context_max_tokens" INTEGER,
    "llm_model" TEXT,
    "updated_at" TIMESTAMPTZ(6) NOT NULL DEFAULT now(),

    CONSTRAINT "app_settings_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."asset_interpretations" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "asset_id" UUID NOT NULL,
    "model" TEXT NOT NULL,
    "prompt_version" TEXT NOT NULL,
    "interpretation" TEXT NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT now(),

    CONSTRAINT "asset_interpretations_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."citations" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "message_id" UUID NOT NULL,
    "paper_id" UUID NOT NULL,
    "page_id" UUID,
    "chunk_id" UUID,
    "citation_label" TEXT,
    "support_metadata" JSONB,

    CONSTRAINT "citations_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."claim_verifications" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "claim_id" UUID NOT NULL,
    "paper_id" UUID,
    "verdict" TEXT NOT NULL,
    "confidence" REAL,
    "rationale" TEXT NOT NULL,
    "citations" JSONB NOT NULL DEFAULT '[]',
    "evidence_count" INTEGER NOT NULL DEFAULT 0,
    "model" TEXT,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT now(),

    CONSTRAINT "claim_verifications_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."claims" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "project_id" UUID NOT NULL,
    "paper_id" UUID,
    "text" TEXT NOT NULL,
    "source" TEXT NOT NULL DEFAULT 'extracted',
    "claim_index" INTEGER NOT NULL DEFAULT 0,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT now(),

    CONSTRAINT "claims_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."conversations" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "project_id" UUID NOT NULL,
    "paper_id" UUID,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT now(),

    CONSTRAINT "conversations_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."messages" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "conversation_id" UUID NOT NULL,
    "role" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT now(),
    "metadata" JSONB,

    CONSTRAINT "messages_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."paper_assets" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "paper_id" UUID NOT NULL,
    "page_id" UUID NOT NULL,
    "kind" TEXT NOT NULL,
    "asset_index" INTEGER NOT NULL,
    "caption" TEXT,
    "content_text" TEXT,
    "storage_path" TEXT,
    "bbox" JSONB NOT NULL,
    "metadata" JSONB NOT NULL DEFAULT '{}',
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT now(),
    "label" TEXT,
    "page_number" INTEGER,

    CONSTRAINT "paper_assets_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."paper_chunks" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "paper_id" UUID NOT NULL,
    "page_id" UUID,
    "section" TEXT,
    "chunk_index" INTEGER NOT NULL,
    "content" TEXT NOT NULL,
    "token_count" INTEGER,
    "embedding" vector(512),
    "start_offset" INTEGER,
    "end_offset" INTEGER,
    "metadata" JSONB,
    "embedding_model" TEXT,
    "embedded_at" TIMESTAMPTZ(6),

    CONSTRAINT "paper_chunks_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."paper_pages" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "paper_id" UUID NOT NULL,
    "page_number" INTEGER NOT NULL,
    "raw_text" TEXT,
    "cleaned_text" TEXT,
    "character_count" INTEGER,
    "token_count" INTEGER,

    CONSTRAINT "paper_pages_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."paper_sections" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "paper_id" UUID NOT NULL,
    "title" TEXT NOT NULL,
    "level" INTEGER NOT NULL DEFAULT 1,
    "section_index" INTEGER NOT NULL,
    "start_page" INTEGER NOT NULL,
    "start_offset" INTEGER,

    CONSTRAINT "paper_sections_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."papers" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "project_id" UUID NOT NULL,
    "title" TEXT,
    "filename" TEXT NOT NULL,
    "storage_path" TEXT NOT NULL,
    "sha256" TEXT,
    "page_count" INTEGER,
    "authors" TEXT[],
    "abstract" TEXT,
    "status" TEXT NOT NULL DEFAULT 'uploaded',
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT now(),
    "processed_at" TIMESTAMPTZ(6),

    CONSTRAINT "papers_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."processing_jobs" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "paper_id" UUID NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'pending',
    "stage" TEXT,
    "progress" REAL NOT NULL DEFAULT 0,
    "error" TEXT,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ(6) NOT NULL DEFAULT now(),
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "started_at" TIMESTAMPTZ(6),
    "finished_at" TIMESTAMPTZ(6),

    CONSTRAINT "processing_jobs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."projects" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT now(),

    CONSTRAINT "projects_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."reproducibility_checks" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "report_id" UUID NOT NULL,
    "dimension" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "rationale" TEXT NOT NULL,
    "citations" JSONB NOT NULL DEFAULT '[]',
    "check_index" INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT "reproducibility_checks_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."reproducibility_reports" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "paper_id" UUID NOT NULL,
    "score" REAL NOT NULL,
    "repo_metadata" JSONB,
    "links" JSONB NOT NULL DEFAULT '[]',
    "model" TEXT,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT now(),

    CONSTRAINT "reproducibility_reports_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."schema_migrations" (
    "version" TEXT NOT NULL,
    "applied_at" TIMESTAMPTZ(6) NOT NULL DEFAULT now(),

    CONSTRAINT "schema_migrations_pkey" PRIMARY KEY ("version")
);

-- CreateTable
CREATE TABLE "public"."users" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT now(),

    CONSTRAINT "users_pkey" PRIMARY KEY ("id")
);

-- AddUniqueConstraint
ALTER TABLE "public"."asset_interpretations" ADD CONSTRAINT "asset_interpretations_asset_id_model_prompt_version_key" UNIQUE ("asset_id", "model", "prompt_version");

-- CreateIndex
CREATE INDEX "idx_asset_interpretations_asset" ON "public"."asset_interpretations"("asset_id" ASC);

-- CreateIndex
CREATE INDEX "citations_message_idx" ON "public"."citations"("message_id" ASC);

-- CreateIndex
CREATE INDEX "claims_paper_idx" ON "public"."claims"("paper_id" ASC, "claim_index" ASC);

-- CreateIndex
CREATE INDEX "claims_project_idx" ON "public"."claims"("project_id" ASC, "created_at" DESC);

-- CreateIndex
CREATE INDEX "conversations_project_created_idx" ON "public"."conversations"("project_id" ASC, "created_at" DESC);

-- CreateIndex
CREATE INDEX "messages_conversation_created_idx" ON "public"."messages"("conversation_id" ASC, "created_at" ASC);

-- CreateIndex
CREATE INDEX "idx_paper_assets_kind" ON "public"."paper_assets"("paper_id" ASC, "kind" ASC);

-- CreateIndex
CREATE INDEX "idx_paper_assets_paper_page" ON "public"."paper_assets"("paper_id" ASC, "page_id" ASC);

-- AddUniqueConstraint
ALTER TABLE "public"."paper_assets" ADD CONSTRAINT "paper_assets_paper_id_kind_asset_index_key" UNIQUE ("paper_id", "kind", "asset_index");

-- CreateIndex
CREATE INDEX "paper_assets_paper_kind_idx" ON "public"."paper_assets"("paper_id" ASC, "kind" ASC, "asset_index" ASC);


-- CreateIndex
CREATE INDEX "idx_paper_chunks_paper_id" ON "public"."paper_chunks"("paper_id" ASC);

-- AddUniqueConstraint
ALTER TABLE "public"."paper_chunks" ADD CONSTRAINT "paper_chunks_paper_id_chunk_index_key" UNIQUE ("paper_id", "chunk_index");

-- AddUniqueConstraint
ALTER TABLE "public"."paper_pages" ADD CONSTRAINT "paper_pages_paper_id_page_number_key" UNIQUE ("paper_id", "page_number");

-- CreateIndex
CREATE INDEX "idx_paper_sections_paper_id" ON "public"."paper_sections"("paper_id" ASC);

-- AddUniqueConstraint
ALTER TABLE "public"."paper_sections" ADD CONSTRAINT "paper_sections_paper_id_section_index_key" UNIQUE ("paper_id", "section_index");

-- CreateIndex
CREATE INDEX "idx_papers_project_id" ON "public"."papers"("project_id" ASC);


-- CreateIndex
CREATE INDEX "idx_papers_project_status" ON "public"."papers"("project_id" ASC, "status" ASC);

-- CreateIndex
CREATE INDEX "idx_processing_jobs_paper_created" ON "public"."processing_jobs"("paper_id" ASC, "created_at" DESC);

-- CreateIndex
CREATE INDEX "idx_processing_jobs_paper_id" ON "public"."processing_jobs"("paper_id" ASC);

-- CreateIndex
CREATE INDEX "idx_processing_jobs_status" ON "public"."processing_jobs"("status" ASC);

-- CreateIndex
CREATE INDEX "idx_projects_user_id" ON "public"."projects"("user_id" ASC);

-- CreateIndex
CREATE INDEX "reproducibility_checks_report_idx" ON "public"."reproducibility_checks"("report_id" ASC, "check_index" ASC);

-- AddUniqueConstraint
ALTER TABLE "public"."reproducibility_reports" ADD CONSTRAINT "reproducibility_reports_paper_id_key" UNIQUE ("paper_id");

-- AddForeignKey
ALTER TABLE "public"."asset_interpretations" ADD CONSTRAINT "asset_interpretations_asset_id_fkey" FOREIGN KEY ("asset_id") REFERENCES "public"."paper_assets"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."citations" ADD CONSTRAINT "citations_chunk_id_fkey" FOREIGN KEY ("chunk_id") REFERENCES "public"."paper_chunks"("id") ON DELETE SET NULL ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."citations" ADD CONSTRAINT "citations_message_id_fkey" FOREIGN KEY ("message_id") REFERENCES "public"."messages"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."citations" ADD CONSTRAINT "citations_page_id_fkey" FOREIGN KEY ("page_id") REFERENCES "public"."paper_pages"("id") ON DELETE SET NULL ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."citations" ADD CONSTRAINT "citations_paper_id_fkey" FOREIGN KEY ("paper_id") REFERENCES "public"."papers"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."claim_verifications" ADD CONSTRAINT "claim_verifications_claim_id_fkey" FOREIGN KEY ("claim_id") REFERENCES "public"."claims"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."claim_verifications" ADD CONSTRAINT "claim_verifications_paper_id_fkey" FOREIGN KEY ("paper_id") REFERENCES "public"."papers"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."claims" ADD CONSTRAINT "claims_paper_id_fkey" FOREIGN KEY ("paper_id") REFERENCES "public"."papers"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."claims" ADD CONSTRAINT "claims_project_id_fkey" FOREIGN KEY ("project_id") REFERENCES "public"."projects"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."conversations" ADD CONSTRAINT "conversations_paper_id_fkey" FOREIGN KEY ("paper_id") REFERENCES "public"."papers"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."conversations" ADD CONSTRAINT "conversations_project_id_fkey" FOREIGN KEY ("project_id") REFERENCES "public"."projects"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."messages" ADD CONSTRAINT "messages_conversation_id_fkey" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."paper_assets" ADD CONSTRAINT "paper_assets_page_id_fkey" FOREIGN KEY ("page_id") REFERENCES "public"."paper_pages"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."paper_assets" ADD CONSTRAINT "paper_assets_paper_id_fkey" FOREIGN KEY ("paper_id") REFERENCES "public"."papers"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."paper_chunks" ADD CONSTRAINT "paper_chunks_page_id_fkey" FOREIGN KEY ("page_id") REFERENCES "public"."paper_pages"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."paper_chunks" ADD CONSTRAINT "paper_chunks_paper_id_fkey" FOREIGN KEY ("paper_id") REFERENCES "public"."papers"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."paper_pages" ADD CONSTRAINT "paper_pages_paper_id_fkey" FOREIGN KEY ("paper_id") REFERENCES "public"."papers"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."paper_sections" ADD CONSTRAINT "paper_sections_paper_id_fkey" FOREIGN KEY ("paper_id") REFERENCES "public"."papers"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."papers" ADD CONSTRAINT "papers_project_id_fkey" FOREIGN KEY ("project_id") REFERENCES "public"."projects"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."processing_jobs" ADD CONSTRAINT "processing_jobs_paper_id_fkey" FOREIGN KEY ("paper_id") REFERENCES "public"."papers"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."projects" ADD CONSTRAINT "projects_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."reproducibility_checks" ADD CONSTRAINT "reproducibility_checks_report_id_fkey" FOREIGN KEY ("report_id") REFERENCES "public"."reproducibility_reports"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "public"."reproducibility_reports" ADD CONSTRAINT "reproducibility_reports_paper_id_fkey" FOREIGN KEY ("paper_id") REFERENCES "public"."papers"("id") ON DELETE CASCADE ON UPDATE NO ACTION;



-- Objects Prisma cannot express. Generated by backend/scripts/dump_raw_objects.py — do not hand-edit.
--
-- `prisma migrate diff` drops every CHECK constraint and rewrites HNSW,
-- partial and expression indexes into plain btrees. Without this file a
-- database created from the Prisma baseline would accept invalid enum
-- values and would answer vector search with a sequential scan.

-- === Indexes =============================================================

DROP INDEX IF EXISTS public.claim_verifications_unique_scope_idx;
CREATE UNIQUE INDEX claim_verifications_unique_scope_idx ON public.claim_verifications USING btree (claim_id, COALESCE(paper_id, '00000000-0000-0000-0000-000000000000'::uuid));

DROP INDEX IF EXISTS public.idx_paper_chunks_embedding;
CREATE INDEX idx_paper_chunks_embedding ON public.paper_chunks USING hnsw (embedding vector_cosine_ops);

DROP INDEX IF EXISTS public.idx_papers_project_sha256;
CREATE UNIQUE INDEX idx_papers_project_sha256 ON public.papers USING btree (project_id, sha256) WHERE (sha256 IS NOT NULL);

-- === CHECK constraints ===================================================
-- Enum-like columns (status, role, verdict, kind…) and range bounds. The
-- Prisma schema documents these in comments; the database enforces them.

ALTER TABLE public.app_settings DROP CONSTRAINT IF EXISTS "app_settings_context_max_tokens_check";
ALTER TABLE public.app_settings ADD CONSTRAINT "app_settings_context_max_tokens_check" CHECK (((context_max_tokens >= 500) AND (context_max_tokens <= 32000)));

ALTER TABLE public.app_settings DROP CONSTRAINT IF EXISTS "app_settings_id_check";
ALTER TABLE public.app_settings ADD CONSTRAINT "app_settings_id_check" CHECK (id);

ALTER TABLE public.app_settings DROP CONSTRAINT IF EXISTS "app_settings_rerank_top_k_check";
ALTER TABLE public.app_settings ADD CONSTRAINT "app_settings_rerank_top_k_check" CHECK (((rerank_top_k >= 1) AND (rerank_top_k <= 20)));

ALTER TABLE public.app_settings DROP CONSTRAINT IF EXISTS "app_settings_search_top_k_check";
ALTER TABLE public.app_settings ADD CONSTRAINT "app_settings_search_top_k_check" CHECK (((search_top_k >= 1) AND (search_top_k <= 100)));

ALTER TABLE public.claim_verifications DROP CONSTRAINT IF EXISTS "claim_verifications_verdict_check";
ALTER TABLE public.claim_verifications ADD CONSTRAINT "claim_verifications_verdict_check" CHECK ((verdict = ANY (ARRAY['supported'::text, 'contradicted'::text, 'insufficient'::text])));

ALTER TABLE public.claims DROP CONSTRAINT IF EXISTS "claims_source_check";
ALTER TABLE public.claims ADD CONSTRAINT "claims_source_check" CHECK ((source = ANY (ARRAY['extracted'::text, 'manual'::text])));

ALTER TABLE public.messages DROP CONSTRAINT IF EXISTS "messages_role_check";
ALTER TABLE public.messages ADD CONSTRAINT "messages_role_check" CHECK ((role = ANY (ARRAY['user'::text, 'assistant'::text, 'system'::text])));

ALTER TABLE public.paper_assets DROP CONSTRAINT IF EXISTS "paper_assets_asset_index_check";
ALTER TABLE public.paper_assets ADD CONSTRAINT "paper_assets_asset_index_check" CHECK ((asset_index >= 0));

ALTER TABLE public.paper_assets DROP CONSTRAINT IF EXISTS "paper_assets_kind_check";
ALTER TABLE public.paper_assets ADD CONSTRAINT "paper_assets_kind_check" CHECK ((kind = ANY (ARRAY['figure'::text, 'table'::text, 'equation'::text, 'reference'::text])));

ALTER TABLE public.paper_pages DROP CONSTRAINT IF EXISTS "paper_pages_page_number_positive";
ALTER TABLE public.paper_pages ADD CONSTRAINT "paper_pages_page_number_positive" CHECK ((page_number >= 1));

ALTER TABLE public.paper_sections DROP CONSTRAINT IF EXISTS "paper_sections_level_check";
ALTER TABLE public.paper_sections ADD CONSTRAINT "paper_sections_level_check" CHECK ((level >= 1));

ALTER TABLE public.paper_sections DROP CONSTRAINT IF EXISTS "paper_sections_start_page_check";
ALTER TABLE public.paper_sections ADD CONSTRAINT "paper_sections_start_page_check" CHECK ((start_page >= 1));

ALTER TABLE public.papers DROP CONSTRAINT IF EXISTS "papers_status_check";
ALTER TABLE public.papers ADD CONSTRAINT "papers_status_check" CHECK ((status = ANY (ARRAY['uploaded'::text, 'processing'::text, 'ready'::text, 'failed'::text])));

ALTER TABLE public.processing_jobs DROP CONSTRAINT IF EXISTS "processing_jobs_attempts_check";
ALTER TABLE public.processing_jobs ADD CONSTRAINT "processing_jobs_attempts_check" CHECK ((attempts >= 0));

ALTER TABLE public.processing_jobs DROP CONSTRAINT IF EXISTS "processing_jobs_progress_check";
ALTER TABLE public.processing_jobs ADD CONSTRAINT "processing_jobs_progress_check" CHECK (((progress >= (0)::double precision) AND (progress <= (1)::double precision)));

ALTER TABLE public.processing_jobs DROP CONSTRAINT IF EXISTS "processing_jobs_status_check";
ALTER TABLE public.processing_jobs ADD CONSTRAINT "processing_jobs_status_check" CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'succeeded'::text, 'failed'::text])));

ALTER TABLE public.projects DROP CONSTRAINT IF EXISTS "projects_name_check";
ALTER TABLE public.projects ADD CONSTRAINT "projects_name_check" CHECK ((length(TRIM(BOTH FROM name)) > 0));

ALTER TABLE public.reproducibility_checks DROP CONSTRAINT IF EXISTS "reproducibility_checks_status_check";
ALTER TABLE public.reproducibility_checks ADD CONSTRAINT "reproducibility_checks_status_check" CHECK ((status = ANY (ARRAY['disclosed'::text, 'partial'::text, 'missing'::text])));

