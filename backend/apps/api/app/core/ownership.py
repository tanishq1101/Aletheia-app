"""Resource ownership, enforced once for every route rather than route by route.

With a single seeded user, "does this project belong to the caller" had one
answer and nothing asked it. Real accounts turn that into an authorisation
question, and the honest state of the code before this file was that only
`GET /projects` filtered by user at all: `GET /projects/{id}`,
`DELETE /projects/{id}` and every paper, claim, conversation and asset route
took an id from the URL and trusted it. Any signed-in user could have read or
deleted another's library by guessing a UUID.

Enforcing that per handler means thirty edits and one forgotten route. This is
a router-level dependency instead: FastAPI resolves dependencies *after* route
matching, so `request.path_params` is populated and one function can look at
whichever resource id the matched route declares. A new endpoint that takes a
`paper_id` is covered the day it is written, without its author remembering.

Not-found and not-yours both return 404. A 403 on someone else's id confirms
that the id exists, which is a membership oracle for anyone with a UUID list.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.core.auth import get_current_user_id
from app.core.logging import get_logger
from app.db.session import get_connection

log = get_logger(__name__)

# Path parameter -> the query proving the caller owns that row. Each is a
# single indexed lookup joined back to `projects.user_id`, which is the only
# column that says who owns anything.
OWNERSHIP_QUERIES: dict[str, str] = {
    "project_id": """
        SELECT 1 FROM projects WHERE id = %(id)s AND user_id = %(user)s
    """,
    "paper_id": """
        SELECT 1 FROM papers p
        JOIN projects pr ON pr.id = p.project_id
        WHERE p.id = %(id)s AND pr.user_id = %(user)s
    """,
    "asset_id": """
        SELECT 1 FROM paper_assets a
        JOIN papers p   ON p.id  = a.paper_id
        JOIN projects pr ON pr.id = p.project_id
        WHERE a.id = %(id)s AND pr.user_id = %(user)s
    """,
    "claim_id": """
        SELECT 1 FROM claims c
        JOIN projects pr ON pr.id = c.project_id
        WHERE c.id = %(id)s AND pr.user_id = %(user)s
    """,
    "conversation_id": """
        SELECT 1 FROM conversations c
        JOIN projects pr ON pr.id = c.project_id
        WHERE c.id = %(id)s AND pr.user_id = %(user)s
    """,
}


def enforce_ownership(
    request: Request,
    user_id: str = Depends(get_current_user_id),
) -> None:
    """Reject any request naming a resource the caller does not own.

    Every id in the path is checked, not just the first: a route carrying both
    a project and a paper must have them agree, or a caller could pair their
    own project id with someone else's paper id.
    """
    checks = [
        (name, value)
        for name, value in request.path_params.items()
        if name in OWNERSHIP_QUERIES and value
    ]
    if not checks:
        return

    with get_connection() as conn, conn.cursor() as cur:
        for name, value in checks:
            try:
                cur.execute(
                    OWNERSHIP_QUERIES[name], {"id": str(value), "user": user_id}
                )
            except Exception:
                # A malformed UUID reaches here before FastAPI's own path
                # validation on some routes. It cannot belong to anyone.
                conn.rollback()
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, f"No such {name.removesuffix('_id')}"
                ) from None
            if cur.fetchone() is None:
                log.info(
                    "Refused %s %s — %s=%s is not owned by user %s",
                    request.method,
                    request.url.path,
                    name,
                    value,
                    user_id,
                )
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    f"No such {name.removesuffix('_id')}",
                )
