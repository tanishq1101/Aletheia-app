import hashlib
from uuid import uuid4

import pytest

from app.db.session import get_connection
from tests.conftest import MINIMAL_PDF


def upload(client, project_id, *, filename="paper.pdf", data=MINIMAL_PDF,
           content_type="application/pdf"):
    return client.post(
        f"/projects/{project_id}/papers",
        files={"file": (filename, data, content_type)},
    )


def test_upload_creates_paper_job_and_stored_file(client, project, storage_root):
    response = upload(client, project["id"])

    assert response.status_code == 201, response.text
    body = response.json()

    assert body["filename"] == "paper.pdf"
    assert body["status"] == "uploaded"
    assert body["sha256"] == hashlib.sha256(MINIMAL_PDF).hexdigest()
    assert body["project_id"] == project["id"]
    # Sprint 1 does not extract anything.
    assert body["page_count"] is None
    assert body["processed_at"] is None

    # A processing job must exist, pending and unstarted.
    job = body["job"]
    assert job is not None
    assert job["status"] == "pending"
    assert job["progress"] == 0
    assert job["error"] is None
    assert job["paper_id"] == body["id"]

    # The bytes actually landed on disk, unmodified.
    stored = storage_root / body["storage_path"]
    assert stored.is_file()
    assert stored.read_bytes() == MINIMAL_PDF

    # Both rows are really in the database, not just in the response.
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM papers WHERE id = %s", (body["id"],))
        assert cur.fetchone()["n"] == 1
        cur.execute(
            "SELECT COUNT(*) AS n FROM processing_jobs WHERE paper_id = %s",
            (body["id"],),
        )
        assert cur.fetchone()["n"] == 1


@pytest.mark.parametrize(
    "filename,data,content_type,expected_fragment",
    [
        ("fake.pdf", b"not a pdf at all", "application/pdf", "PDF header"),
        ("empty.pdf", b"", "application/pdf", "empty"),
        ("image.pdf", b"\x89PNG\r\n\x1a\n" + b"0" * 40, "image/png", "content type"),
    ],
    ids=["pdf-name-but-not-pdf", "empty-file", "wrong-content-type"],
)
def test_upload_rejects_invalid_files(
    client, project, storage_root, filename, data, content_type, expected_fragment
):
    response = upload(
        client, project["id"], filename=filename, data=data, content_type=content_type
    )

    assert response.status_code == 400, response.text
    assert expected_fragment.lower() in response.json()["detail"].lower()

    # A rejected upload must leave nothing behind.
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM papers WHERE project_id = %s", (project["id"],)
        )
        assert cur.fetchone()["n"] == 0
    assert not (storage_root / project["id"]).exists()


def test_upload_accepts_and_indexes_text_sources(client, project):
    response = upload(
        client, project["id"], filename="notes.txt", data=b"A source note about semantic retrieval.", content_type="text/plain"
    )
    assert response.status_code == 201, response.text
    paper = client.get(f"/papers/{response.json()['id']}").json()
    assert paper["status"] == "ready"
    pages = client.get(f"/papers/{paper['id']}/pages").json()
    assert "semantic retrieval" in pages[0]["cleaned_text"]


def test_delete_source_removes_its_record_and_stored_file(client, project, storage_root):
    created = upload(client, project["id"], filename="notes.txt", data=b"Disposable note", content_type="text/plain").json()
    stored = storage_root / created["storage_path"]
    assert stored.is_file()

    response = client.delete(f"/papers/{created['id']}")

    assert response.status_code == 204
    assert client.get(f"/papers/{created['id']}").status_code == 404
    assert not stored.exists()


def test_upload_over_size_limit_is_rejected(client, project):
    from app.core.config import get_settings

    oversized = MINIMAL_PDF + b"0" * get_settings().max_upload_bytes
    response = upload(client, project["id"], data=oversized)

    assert response.status_code == 400
    assert "limit" in response.json()["detail"].lower()


def test_upload_to_unknown_project_is_404_and_stores_nothing(client, storage_root):
    missing = uuid4()

    response = upload(client, missing)

    assert response.status_code == 404
    assert not (storage_root / str(missing)).exists()


def test_upload_response_reports_the_job_as_queued(client, project):
    """The upload response is returned before the background task runs."""
    body = upload(client, project["id"]).json()

    assert body["job"]["status"] == "pending"
    assert body["job"]["stage"] == "queued"


def test_listing_papers_returns_paper_with_its_job(client, project):
    uploaded = upload(client, project["id"]).json()

    response = client.get(f"/projects/{project['id']}/papers")

    assert response.status_code == 200
    papers = response.json()
    assert len(papers) == 1
    assert papers[0]["id"] == uploaded["id"]
    # Sprint 2: extraction runs in the background, so by the time this is
    # queried the job has finished. (Sprint 1 asserted 'pending' here, when
    # nothing consumed jobs.)
    assert papers[0]["job"]["status"] == "succeeded"


def test_get_single_paper(client, project):
    uploaded = upload(client, project["id"]).json()

    response = client.get(f"/papers/{uploaded['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == uploaded["id"]
    assert response.json()["job"]["stage"] == "complete"


def test_get_unknown_paper_is_404(client):
    assert client.get(f"/papers/{uuid4()}").status_code == 404
