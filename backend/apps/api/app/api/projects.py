from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_connection
from app.schemas.models import Project, ProjectCreate

router = APIRouter(prefix="/projects", tags=["projects"])
log = get_logger(__name__)


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate) -> Project:
    # Sprint 1 has no auth; every project belongs to the seeded dev user.
    user_id = get_settings().dev_user_id
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


@router.get("", response_model=list[Project])
def list_projects() -> list[Project]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, name, description, created_at
            FROM projects
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (get_settings().dev_user_id,),
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
