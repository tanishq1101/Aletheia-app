import hashlib
import re
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile, status

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_connection
from app.schemas.models import (
    PaperPage,
    PaperSection,
    PaperWithJob,
    ProcessingJob,
)
from app.services.ingestion import process_paper
from app.services.pdf_validation import UploadValidationError, validate_upload
from app.services.storage import StorageError, build_storage
from app.services.vector_store import VectorStoreError
from app.services.vector_store import delete_paper as delete_vectors_for_paper

router = APIRouter(tags=["papers"])
log = get_logger(__name__)

PAPER_COLUMNS = """
    id, project_id, title, filename, storage_path, sha256,
    page_count, status, created_at, processed_at
"""

JOB_COLUMNS = """
    id, paper_id, status, stage, progress, error,
    attempts, created_at, updated_at
"""


# Streamed in fixed blocks so peak memory is bounded by the limit, not by
# whatever the client chose to send.
_UPLOAD_CHUNK_BYTES = 1024 * 1024


async def _read_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read at most `max_bytes` + 1 bytes, so the caller can detect overflow."""
    buffer = bytearray()
    while len(buffer) <= max_bytes:
        block = await file.read(_UPLOAD_CHUNK_BYTES)
        if not block:
            break
        buffer.extend(block)
    return bytes(buffer)


def _project_exists(conn, project_id: UUID) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projects WHERE id = %s", (str(project_id),))
        return cur.fetchone() is not None


@router.post(
    "/projects/{project_id}/papers",
    response_model=PaperWithJob,
    status_code=status.HTTP_201_CREATED,
)
async def upload_paper(
    project_id: UUID,
    background: BackgroundTasks,
    file: UploadFile = File(...),
) -> PaperWithJob:
    """Accept a project source, store it, and queue extraction.

    Returns as soon as the records exist; extraction runs in the background
    (execution model decided in PROGRESS.md) so a long PDF cannot block the
    request. Poll the paper for status.
    """
    settings = get_settings()
    filename = file.filename or "upload"

    # Read with a hard ceiling rather than `await file.read()`. The size limit
    # was previously enforced only after the whole upload was already in
    # memory, so an oversized body cost the full allocation before being
    # rejected — the one request shape that could take the process down.
    # Reading one chunk past the limit is enough to know it is over.
    data = await _read_capped(file, settings.max_upload_bytes)
    try:
        validate_upload(
            filename=filename,
            content_type=file.content_type,
            data=data,
            max_bytes=settings.max_upload_bytes,
        )
    except UploadValidationError as exc:
        log.warning("Rejected upload %r for project %s: %s", filename, project_id, exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    sha256 = hashlib.sha256(data).hexdigest()

    with get_connection() as conn:
        if not _project_exists(conn, project_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No project {project_id}")

        # Duplicate detection is per-project (decision in PROGRESS.md): the
        # same PDF in another project is a legitimately separate paper.
        # Checked here for a clear 409; UNIQUE(project_id, sha256) is what
        # actually guarantees it under concurrent uploads.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, filename FROM papers WHERE project_id = %s AND sha256 = %s",
                (str(project_id), sha256),
            )
            existing = cur.fetchone()

    if existing is not None:
        log.info(
            "Duplicate upload %r rejected for project %s (matches paper %s)",
            filename,
            project_id,
            existing["id"],
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": (
                    f"This file is already in the project as "
                    f"{existing['filename']!r}."
                ),
                "existing_paper_id": str(existing["id"]),
            },
        )

    paper_id = uuid4()
    suffix = re.sub(r"[^a-zA-Z0-9]", "", filename.rsplit(".", 1)[-1]) if "." in filename else "bin"
    key = f"{project_id}/{paper_id}.{suffix[:16] or 'bin'}"
    storage = build_storage(settings)

    try:
        storage_path = storage.store(key=key, data=data)
    except StorageError as exc:
        log.error("Storage write failed for project %s: %s", project_id, exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"Could not store file: {exc}"
        ) from exc

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO papers
                        (id, project_id, filename, storage_path, sha256, status)
                    VALUES (%s, %s, %s, %s, %s, 'uploaded')
                    RETURNING {PAPER_COLUMNS}
                    """,
                    (str(paper_id), str(project_id), filename, storage_path, sha256),
                )
                paper_row = cur.fetchone()

                cur.execute(
                    f"""
                    INSERT INTO processing_jobs (paper_id, status, stage)
                    VALUES (%s, 'pending', 'queued')
                    RETURNING {JOB_COLUMNS}
                    """,
                    (str(paper_id),),
                )
                job_row = cur.fetchone()
            conn.commit()
    except Exception as exc:
        # The file is already on disk but has no record pointing at it. Say so
        # loudly rather than leaving a silent orphan.
        log.error(
            "Upload rolled back for project %s; orphaned stored file at %r: %s",
            project_id,
            key,
            exc,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Could not record the uploaded paper.",
        ) from exc

    log.info(
        "Stored paper %s (%r, %d bytes) in project %s; queued job %s",
        paper_id,
        filename,
        len(data),
        project_id,
        job_row["id"],
    )

    # Runs after the response is sent.
    background.add_task(process_paper, paper_id, job_row["id"])

    return PaperWithJob(**paper_row, job=ProcessingJob(**job_row))


@router.get("/projects/{project_id}/papers", response_model=list[PaperWithJob])
def list_papers(project_id: UUID) -> list[PaperWithJob]:
    with get_connection() as conn:
        if not _project_exists(conn, project_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No project {project_id}")

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {PAPER_COLUMNS}
                FROM papers WHERE project_id = %s
                ORDER BY created_at DESC
                """,
                (str(project_id),),
            )
            papers = cur.fetchall()

            if not papers:
                return []

            # Latest job per paper.
            cur.execute(
                """
                SELECT DISTINCT ON (paper_id)
                    id, paper_id, status, stage, progress, error,
                    attempts, created_at, updated_at
                FROM processing_jobs
                WHERE paper_id = ANY(%s)
                ORDER BY paper_id, created_at DESC
                """,
                ([str(p["id"]) for p in papers],),
            )
            jobs = {str(row["paper_id"]): ProcessingJob(**row) for row in cur.fetchall()}

    return [PaperWithJob(**p, job=jobs.get(str(p["id"]))) for p in papers]


@router.get("/papers/{paper_id}", response_model=PaperWithJob)
def get_paper(paper_id: UUID) -> PaperWithJob:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {PAPER_COLUMNS} FROM papers WHERE id = %s", (str(paper_id),)
        )
        paper = cur.fetchone()
        if paper is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No paper {paper_id}")

        cur.execute(
            f"""
            SELECT {JOB_COLUMNS}
            FROM processing_jobs
            WHERE paper_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(paper_id),),
        )
        job_row = cur.fetchone()

    return PaperWithJob(**paper, job=ProcessingJob(**job_row) if job_row else None)


@router.delete("/papers/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(paper_id: UUID) -> None:
    """Delete a source and all derived text, vectors, jobs, and assets."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT storage_path FROM papers WHERE id = %s", (str(paper_id),))
            paper = cur.fetchone()
        if paper is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No paper {paper_id}")

        with conn.cursor() as cur:
            cur.execute("DELETE FROM papers WHERE id = %s", (str(paper_id),))
        conn.commit()

    # Postgres cascades to chunks; Chroma has no foreign keys, so its vectors
    # have to be removed explicitly. Retrieval skips a vector whose chunk is
    # gone, so leaving them never produces a wrong citation — but they still
    # occupy candidate slots in every future search, quietly returning fewer
    # real results than the caller asked for. Best-effort: the record is
    # already gone, and `scripts/backfill_chroma.py --rebuild` is the
    # documented repair if this fails.
    try:
        delete_vectors_for_paper(paper_id)
    except VectorStoreError as exc:
        log.warning(
            "Deleted source %s but could not remove its vectors: %s. "
            "Run scripts/backfill_chroma.py --rebuild to reconcile.",
            paper_id,
            exc,
        )

    try:
        build_storage(get_settings()).delete(key=paper["storage_path"])
    except StorageError as exc:
        log.warning("Deleted source record %s but could not remove stored bytes: %s", paper_id, exc)


def _require_paper(conn, paper_id: UUID) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM papers WHERE id = %s", (str(paper_id),))
        if cur.fetchone() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No paper {paper_id}")


@router.get("/papers/{paper_id}/pages", response_model=list[PaperPage])
def get_paper_pages(paper_id: UUID) -> list[PaperPage]:
    """Extracted page text, in page order."""
    with get_connection() as conn:
        _require_paper(conn, paper_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, paper_id, page_number, cleaned_text, character_count
                FROM paper_pages
                WHERE paper_id = %s
                ORDER BY page_number
                """,
                (str(paper_id),),
            )
            return [PaperPage(**row) for row in cur.fetchall()]


@router.get("/papers/{paper_id}/sections", response_model=list[PaperSection])
def get_paper_sections(paper_id: UUID) -> list[PaperSection]:
    """Detected sections, in document order."""
    with get_connection() as conn:
        _require_paper(conn, paper_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, paper_id, title, level, section_index,
                       start_page, start_offset
                FROM paper_sections
                WHERE paper_id = %s
                ORDER BY section_index
                """,
                (str(paper_id),),
            )
            return [PaperSection(**row) for row in cur.fetchall()]


@router.post("/papers/{paper_id}/reprocess", response_model=PaperWithJob)
def reprocess_paper(paper_id: UUID, background: BackgroundTasks) -> PaperWithJob:
    """Retry extraction for a paper (PRD Section 12: failed jobs are retryable).

    Opens a new job rather than reusing the old one, so the failure history
    stays diagnosable.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {PAPER_COLUMNS} FROM papers WHERE id = %s", (str(paper_id),)
            )
            paper_row = cur.fetchone()
            if paper_row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"No paper {paper_id}")

            cur.execute(
                "SELECT status FROM processing_jobs WHERE paper_id = %s"
                " ORDER BY created_at DESC LIMIT 1",
                (str(paper_id),),
            )
            current = cur.fetchone()
            if current and current["status"] == "running":
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "This paper is already being processed.",
                )

            cur.execute(
                f"""
                INSERT INTO processing_jobs (paper_id, status, stage)
                VALUES (%s, 'pending', 'queued')
                RETURNING {JOB_COLUMNS}
                """,
                (str(paper_id),),
            )
            job_row = cur.fetchone()

            cur.execute(
                "UPDATE papers SET status = 'uploaded', processed_at = NULL"
                " WHERE id = %s",
                (str(paper_id),),
            )
        conn.commit()

    log.info("Reprocess requested for paper %s; queued job %s", paper_id, job_row["id"])
    background.add_task(process_paper, paper_id, job_row["id"])

    paper_row["status"] = "uploaded"
    paper_row["processed_at"] = None
    return PaperWithJob(**paper_row, job=ProcessingJob(**job_row))
