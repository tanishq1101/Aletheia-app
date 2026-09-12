"""What the duplicate-project cleanup is and is not allowed to delete.

A cleanup script that runs once and is never tested is a cleanup script nobody
can safely rerun. The risk here is not that it fails to find the duplicate —
that is visible immediately — it is that it takes something it should not: a
project a user deliberately named "My Library", or one that quietly acquired a
paper between the survey and the delete.

The survey query is imported and exercised against the real schema rather than
reimplemented here, so a change to either one has to face these cases.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from uuid import uuid4

import pytest

from app.api.projects import DEFAULT_PROJECT_NAME
from app.db.session import get_connection

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend" / "scripts"))
import remove_duplicate_default_projects as cleanup  # noqa: E402


USER = "00000000-0000-0000-0000-000000000001"
BASE = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


def make_project(cur, name, *, offset_seconds, description=None):
    project_id = str(uuid4())
    cur.execute(
        """
        INSERT INTO projects (id, user_id, name, description, created_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            project_id,
            USER,
            name,
            description,
            BASE + timedelta(seconds=offset_seconds),
        ),
    )
    return project_id


def add_paper(cur, project_id):
    cur.execute(
        "INSERT INTO papers (project_id, filename, storage_path) VALUES (%s, %s, %s)",
        (project_id, "paper.pdf", f"/tmp/{uuid4()}.pdf"),
    )


@pytest.fixture
def scenario():
    """The original race, plus every neighbour the script must not touch."""
    created = []
    with get_connection() as conn, conn.cursor() as cur:
        # Anything already in this database would change what "oldest" means.
        cur.execute("DELETE FROM projects WHERE user_id = %s", (USER,))

        ids = {
            # 171 ms apart, which is what actually happened.
            "original": make_project(cur, DEFAULT_PROJECT_NAME, offset_seconds=0),
            "duplicate": make_project(cur, DEFAULT_PROJECT_NAME, offset_seconds=0.171),
            "described": make_project(
                cur, DEFAULT_PROJECT_NAME, offset_seconds=60, description="on purpose"
            ),
            "renamed": make_project(cur, "Thesis Sources", offset_seconds=120),
            "occupied": make_project(cur, DEFAULT_PROJECT_NAME, offset_seconds=180),
        }
        add_paper(cur, ids["occupied"])
        created = list(ids.values())
        conn.commit()

    yield ids

    with get_connection() as conn, conn.cursor() as cur:
        for project_id in created:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


def survey_ids(scenario_ids) -> set[str]:
    with get_connection() as conn:
        return {str(row["id"]) for row in cleanup.survey(conn)}


def test_it_finds_the_empty_duplicate(scenario):
    assert scenario["duplicate"] in survey_ids(scenario)


def test_it_never_takes_the_oldest_project(scenario):
    """The oldest is the default the UI selects. Deleting it is the bug itself."""
    assert scenario["original"] not in survey_ids(scenario)


def test_it_leaves_a_deliberately_named_project_alone(scenario):
    """Two projects a user meant to name the same thing is legitimate."""
    assert scenario["described"] not in survey_ids(scenario)


def test_it_leaves_other_projects_alone(scenario):
    assert scenario["renamed"] not in survey_ids(scenario)


def test_it_never_takes_a_project_holding_papers(scenario):
    assert scenario["occupied"] not in survey_ids(scenario)


def test_deleting_removes_only_the_duplicate(scenario):
    with get_connection() as conn:
        rows = cleanup.survey(conn)
        removed = cleanup.delete(conn, rows)
        conn.commit()
    assert removed == 1

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE user_id = %s", (USER,))
        surviving = {str(row["id"]) for row in cur.fetchall()}

    assert scenario["duplicate"] not in surviving
    assert surviving == {
        scenario["original"],
        scenario["described"],
        scenario["renamed"],
        scenario["occupied"],
    }


def test_a_paper_arriving_mid_run_saves_its_project(scenario):
    """The survey is not a lock, so the delete re-checks what it is deleting."""
    with get_connection() as conn:
        rows = cleanup.survey(conn)
        assert [str(row["id"]) for row in rows] == [scenario["duplicate"]]

    # Between the survey and the delete, someone uploads into it.
    with get_connection() as conn, conn.cursor() as cur:
        add_paper(cur, scenario["duplicate"])
        conn.commit()

    with get_connection() as conn:
        removed = cleanup.delete(conn, rows)
        conn.commit()

    assert removed == 0, "a project that gained a paper was deleted anyway"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projects WHERE id = %s", (scenario["duplicate"],))
        assert cur.fetchone() is not None


def test_it_finds_nothing_once_it_has_run(scenario):
    with get_connection() as conn:
        cleanup.delete(conn, cleanup.survey(conn))
        conn.commit()
    assert survey_ids(scenario) == set()
