from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import get_current_user_id
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_connection
from app.services.storage import StorageError, build_storage
from app.services.vector_store import VectorStoreError
from app.services.vector_store import delete_paper as delete_vectors_for_paper
from app.schemas.models import Project, ProjectCreate

router = APIRouter(prefix="/projects", tags=["projects"])
log = get_logger(__name__)

# Name given to the project created for a brand-new, empty workspace.
DEFAULT_PROJECT_NAME = "My Library"


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    user_id: str = Depends(get_current_user_id),
) -> Project:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (user_id, name, description)
            VALUES (%s, %s, %s)
            RETURNING id, user_id, name, description, created_at
            """,
            (user_id, payload.name.strip(), payload.description),
        )
        row = cur.fetchone()
    log.info("Created project %s (%s)", row["id"], row["name"])
    return Project(**row)


@router.post("/default", response_model=Project)
def ensure_default_project(
    user_id: str = Depends(get_current_user_id),
) -> Project:
    """Return the user's default project, creating it only if none exists.

    Idempotent by design. The UI needs somewhere for a first upload to land, but
    a plain "list, and create if empty" is two round trips with a gap in the
    middle: React's development double-mount, two open tabs, or a refresh
    mid-flight all fall into that gap and each create their own "My Library".
    The duplicate is not cosmetic — the UI then selects one of them, and papers
    uploaded under the other simply stop appearing.

    The advisory lock closes the gap: it is held to the end of the transaction,
    so a concurrent caller waits and then observes the committed row instead of
    inserting a second one. Scoped to the user, so it never serialises anything
    but this one decision. No unique constraint on the name, because two
    projects deliberately named the same thing is a legitimate thing to want.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"default-project:{user_id}",),
            )
            # Oldest first: the original project keeps its role as the default
            # even if others were added later.
            cur.execute(
                """
                SELECT id, user_id, name, description, created_at
                FROM projects WHERE user_id = %s
                ORDER BY created_at ASC LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    """
                    INSERT INTO projects (user_id, name, description)
                    VALUES (%s, %s, NULL)
                    RETURNING id, user_id, name, description, created_at
                    """,
                    (user_id, DEFAULT_PROJECT_NAME),
                )
                row = cur.fetchone()
                log.info("Created default project %s", row["id"])
        conn.commit()
    return Project(**row)


@router.get("", response_model=list[Project])
def list_projects(user_id: str = Depends(get_current_user_id)) -> list[Project]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, name, description, created_at
            FROM projects
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        return [Project(**row) for row in cur.fetchall()]


@router.get("/{project_id}", response_model=Project)
def get_project(project_id: UUID) -> Project:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, name, description, created_at
            FROM projects WHERE id = %s
            """,
            (str(project_id),),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No project {project_id}")
    return Project(**row)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: UUID) -> None:
    """Delete a project and everything derived from it.

    Postgres cascades to papers, chunks, jobs and assets. Chroma and local
    storage have no foreign keys, so each paper's vectors and stored bytes are
    removed explicitly, before the cascade takes the rows that name them.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM projects WHERE id = %s", (str(project_id),))
            if cur.fetchone() is None:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, f"No project {project_id}"
                )
            # Read these first: after the cascade there is nothing left to say
            # which vectors and files belonged to this project.
            cur.execute(
                "SELECT id, storage_path FROM papers WHERE project_id = %s",
                (str(project_id),),
            )
            papers = cur.fetchall()

        with conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (str(project_id),))
        conn.commit()

    storage = build_storage(get_settings())
    for paper in papers:
        try:
            delete_vectors_for_paper(paper["id"])
        except VectorStoreError as exc:
            log.warning(
                "Deleted project %s but could not remove vectors for paper %s: "
                "%s. Run scripts/backfill_chroma.py --rebuild to reconcile.",
                project_id,
                paper["id"],
                exc,
            )
        if not paper["storage_path"]:
            continue
        try:
            storage.delete(key=paper["storage_path"])
        except StorageError as exc:
            log.warning(
                "Deleted project %s but could not remove stored bytes for "
                "paper %s: %s",
                project_id,
                paper["id"],
                exc,
            )
    log.info("Deleted project %s and %d source(s)", project_id, len(papers))
