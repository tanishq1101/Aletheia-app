"""End-to-end ingestion tests.

TestClient runs BackgroundTasks synchronously once the response is returned, so
by the time an upload call returns, extraction has already run. That makes these
deterministic without sleeping or polling.
"""

from app.db.session import get_connection
from app.services.ingestion import recover_stranded_jobs
from tests.fixtures import build_corrupt_pdf, build_encrypted_pdf, build_pdf


def upload(client, project_id, *, filename="paper.pdf", data=None):
    return client.post(
        f"/projects/{project_id}/papers",
        files={"file": (filename, data or build_pdf(), "application/pdf")},
    )


def test_upload_triggers_extraction_and_paper_becomes_ready(client, project):
    response = upload(client, project["id"])
    assert response.status_code == 201, response.text
    paper_id = response.json()["id"]

    paper = client.get(f"/papers/{paper_id}").json()
    assert paper["status"] == "ready"
    assert paper["page_count"] == 3
    assert paper["processed_at"] is not None
    assert paper["title"] == "Deep Residual Learning for Image Recognition"

    job = paper["job"]
    assert job["status"] == "succeeded"
    assert job["progress"] == 1.0
    assert job["stage"] == "complete"
    assert job["error"] is None
    assert job["attempts"] == 1


def test_extracted_pages_are_queryable_in_order(client, project):
    paper_id = upload(client, project["id"]).json()["id"]

    pages = client.get(f"/papers/{paper_id}/pages").json()

    assert [p["page_number"] for p in pages] == [1, 2, 3]
    assert "Abstract" in pages[0]["cleaned_text"]
    assert "2 Related Work" in pages[1]["cleaned_text"]
    # Page boundaries preserved: page 2 content is not on page 1.
    assert "2 Related Work" not in pages[0]["cleaned_text"]
    assert all(p["character_count"] > 0 for p in pages)


def test_detected_sections_are_queryable(client, project):
    paper_id = upload(client, project["id"]).json()["id"]

    sections = client.get(f"/papers/{paper_id}/sections").json()

    titles = [s["title"] for s in sections]
    assert "1 Introduction" in titles
    assert "3.1 Identity Mapping by Shortcuts" in titles
    assert [s["section_index"] for s in sections] == list(range(len(sections)))
    nested = next(s for s in sections if s["title"].startswith("3.1"))
    assert nested["level"] == 2
    assert nested["start_page"] == 2


def test_page_token_counts_are_populated(client, project):
    """Sprint 2 left these NULL pending a tokenizer; Sprint 3 fills them in."""
    paper_id = upload(client, project["id"]).json()["id"]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT token_count, character_count FROM paper_pages WHERE paper_id = %s",
            (paper_id,),
        )
        rows = cur.fetchall()

    assert rows
    for row in rows:
        assert row["token_count"] is not None
        assert row["token_count"] > 0
        # Sanity: tokens should be fewer than characters for English prose.
        assert row["token_count"] < row["character_count"]


# --- duplicates -------------------------------------------------------------


def test_duplicate_in_same_project_is_rejected_with_409(client, project):
    # The same bytes, not merely an equivalent document: PyMuPDF stamps a
    # creation time, so build_pdf() twice would produce two different files.
    pdf = build_pdf()

    first = upload(client, project["id"], data=pdf)
    assert first.status_code == 201

    second = upload(client, project["id"], filename="same-paper-again.pdf", data=pdf)

    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["existing_paper_id"] == first.json()["id"]
    assert "already in the project" in detail["message"]

    # The rejected upload must not have created a second paper.
    papers = client.get(f"/projects/{project['id']}/papers").json()
    assert len(papers) == 1


def test_same_pdf_in_a_different_project_is_allowed(client, project):
    pdf = build_pdf()
    upload(client, project["id"], data=pdf)

    other = client.post("/projects", json={"name": "Another project"}).json()
    try:
        # Byte-identical file, different project: a separate paper record.
        response = upload(client, other["id"], data=pdf)
        assert response.status_code == 201
        assert response.json()["project_id"] == other["id"]
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (other["id"],))
            conn.commit()


def test_unique_constraint_backs_the_duplicate_check(client, project):
    """The database, not just app code, must guarantee per-project uniqueness."""
    import psycopg
    import pytest

    paper = upload(client, project["id"]).json()

    with get_connection() as conn:
        with pytest.raises(psycopg.errors.UniqueViolation):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO papers (project_id, filename, storage_path, sha256)
                    VALUES (%s, 'sneaky.pdf', 'x/y.pdf', %s)
                    """,
                    (project["id"], paper["sha256"]),
                )
        conn.rollback()


# --- failure handling -------------------------------------------------------


def test_corrupt_pdf_fails_the_job_with_a_readable_error(client, project):
    response = upload(client, project["id"], data=build_corrupt_pdf())
    # Upload itself succeeds: the header is valid, so this is a processing
    # failure, not a validation failure.
    assert response.status_code == 201
    paper_id = response.json()["id"]

    paper = client.get(f"/papers/{paper_id}").json()
    assert paper["status"] == "failed"
    assert paper["job"]["status"] == "failed"
    assert paper["job"]["error"]
    assert paper["page_count"] is None

    # Nothing partial was written.
    assert client.get(f"/papers/{paper_id}/pages").json() == []
    assert client.get(f"/papers/{paper_id}/sections").json() == []


def test_encrypted_pdf_fails_with_a_password_message(client, project):
    paper_id = upload(client, project["id"], data=build_encrypted_pdf()).json()["id"]

    job = client.get(f"/papers/{paper_id}").json()["job"]
    assert job["status"] == "failed"
    assert "password" in job["error"].lower()


# --- retry ------------------------------------------------------------------


def test_failed_paper_can_be_reprocessed(client, project):
    paper_id = upload(client, project["id"], data=build_corrupt_pdf()).json()["id"]
    assert client.get(f"/papers/{paper_id}").json()["status"] == "failed"

    # Replace the stored bytes with a readable PDF, then retry.
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT storage_path FROM papers WHERE id = %s", (paper_id,)
        )
        storage_path = cur.fetchone()["storage_path"]

    from app.core.config import get_settings

    (get_settings().storage_root / storage_path).write_bytes(build_pdf())

    response = client.post(f"/papers/{paper_id}/reprocess")
    assert response.status_code == 200

    paper = client.get(f"/papers/{paper_id}").json()
    assert paper["status"] == "ready"
    assert paper["job"]["status"] == "succeeded"
    assert paper["job"]["error"] is None
    assert len(client.get(f"/papers/{paper_id}/pages").json()) == 3


def test_reprocess_is_idempotent_and_does_not_duplicate_pages(client, project):
    paper_id = upload(client, project["id"]).json()["id"]
    assert len(client.get(f"/papers/{paper_id}/pages").json()) == 3

    client.post(f"/papers/{paper_id}/reprocess")
    client.post(f"/papers/{paper_id}/reprocess")

    assert len(client.get(f"/papers/{paper_id}/pages").json()) == 3
    sections = client.get(f"/papers/{paper_id}/sections").json()
    assert len(sections) == len({s["title"] for s in sections})


def test_reprocess_unknown_paper_is_404(client):
    from uuid import uuid4

    assert client.post(f"/papers/{uuid4()}/reprocess").status_code == 404


def test_pending_jobs_nothing_will_pick_up_are_recovered(client, project):
    """A job left pending at boot is stranded — no live task is coming for it.

    This is the state of any paper uploaded before extraction existed.
    """
    paper_id = upload(client, project["id"]).json()["id"]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE processing_jobs SET status = 'pending' WHERE paper_id = %s",
            (paper_id,),
        )
        conn.commit()

    recover_stranded_jobs()

    job = client.get(f"/papers/{paper_id}").json()["job"]
    assert job["status"] == "failed"
    assert "never started" in job["error"].lower()


def test_stranded_running_jobs_are_recovered_as_retryable(client, project):
    paper_id = upload(client, project["id"]).json()["id"]

    # Simulate a process killed mid-extraction.
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE processing_jobs SET status = 'running' WHERE paper_id = %s",
            (paper_id,),
        )
        cur.execute("UPDATE papers SET status = 'processing' WHERE id = %s", (paper_id,))
        conn.commit()

    assert recover_stranded_jobs() >= 1

    paper = client.get(f"/papers/{paper_id}").json()
    assert paper["status"] == "failed"
    assert paper["job"]["status"] == "failed"
    assert "restart" in paper["job"]["error"].lower()

    # And it can then actually be retried.
    client.post(f"/papers/{paper_id}/reprocess")
    assert client.get(f"/papers/{paper_id}").json()["status"] == "ready"
