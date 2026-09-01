from uuid import uuid4

from app.db.session import get_connection


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
