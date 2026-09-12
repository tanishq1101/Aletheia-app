from uuid import uuid4

from app.db.session import get_connection

from .fixtures import build_single_page_pdf


def test_create_and_fetch_project(client):
    created = client.post(
        "/projects", json={"name": "Retrieval Survey", "description": "reading list"}
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Retrieval Survey"

    fetched = client.get(f"/projects/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM projects WHERE id = %s", (body["id"],))
        conn.commit()


def test_project_appears_in_list(client, project):
    response = client.get("/projects")

    assert response.status_code == 200
    assert project["id"] in [p["id"] for p in response.json()]


def test_blank_project_name_is_rejected(client):
    assert client.post("/projects", json={"name": ""}).status_code == 422


def test_unknown_project_is_404(client):
    assert client.get(f"/projects/{uuid4()}").status_code == 404


# --- The default project ------------------------------------------------------
# "List, and create one if the list is empty" is two round trips with a gap in
# the middle. A development double-mount, a second tab, or a refresh mid-flight
# all land in that gap and each create their own library — and because the UI
# then selects one of them, every paper uploaded under the other disappears
# from view. The decision belongs to the server, where it can be made once.


def _delete_projects(ids):
    with get_connection() as conn, conn.cursor() as cur:
        for project_id in ids:
            cur.execute("DELETE FROM projects WHERE id = %s", (str(project_id),))
        conn.commit()


def test_ensure_default_creates_one_project_when_none_exist(client):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects")
        pre_existing = [row["id"] for row in cur.fetchall()]

    response = client.post("/projects/default")
    assert response.status_code == 200, response.text
    created = response.json()

    if not pre_existing:
        assert created["name"] == "My Library"
    _delete_projects([created["id"]] if not pre_existing else [])


def test_ensure_default_is_idempotent(client, project):
    """Repeated calls must return the same project, never a second one."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM projects")
        before = cur.fetchone()["n"]

    first = client.post("/projects/default").json()
    second = client.post("/projects/default").json()

    assert first["id"] == second["id"]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM projects")
        assert cur.fetchone()["n"] == before, "ensure-default must not insert"


def test_ensure_default_returns_the_oldest_project(client, project):
    """The default is stable: adding projects later must not move it."""
    newer = client.post("/projects", json={"name": "Added later"}).json()
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM projects ORDER BY created_at ASC LIMIT 1"
            )
            oldest = str(cur.fetchone()["id"])

        assert client.post("/projects/default").json()["id"] == oldest
        assert newer["id"] != oldest, "the newly added project must not become the default"
    finally:
        _delete_projects([newer["id"]])


# --- Deletion -----------------------------------------------------------------
# The settings screen has always offered this; the route did not exist, so the
# button returned 405.


def test_delete_project_removes_it(client):
    created = client.post("/projects", json={"name": "Disposable"}).json()

    assert client.delete(f"/projects/{created['id']}").status_code == 204
    assert client.get(f"/projects/{created['id']}").status_code == 404


def test_delete_unknown_project_is_404(client):
    assert client.delete(f"/projects/{uuid4()}").status_code == 404


def test_delete_project_removes_its_papers(client, project):
    """The cascade is what stops a delete leaving orphaned sources behind."""
    upload = client.post(
        f"/projects/{project['id']}/papers",
        files={"file": ("doomed.pdf", build_single_page_pdf(), "application/pdf")},
    )
    assert upload.status_code == 201, upload.text

    assert client.delete(f"/projects/{project['id']}").status_code == 204

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM papers WHERE project_id = %s",
            (project["id"],),
        )
        assert cur.fetchone()["n"] == 0
