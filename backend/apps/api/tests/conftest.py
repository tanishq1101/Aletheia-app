import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_DB_NAME = "research_intelligence_test"

# --- Everything below must happen BEFORE any app module reads settings, since
# --- get_settings() is lru_cached on first call.

# Throwaway storage directory. Env vars beat .env in pydantic-settings.
os.environ["LOCAL_STORAGE_DIR"] = tempfile.mkdtemp(prefix="ri-test-storage-")

# The suite runs against pgvector, not Chroma. Two reasons, both deliberate:
# the tests must pass with no container running, and mirroring test papers into
# the real collection would leave junk vectors behind in a store that has no
# cascade to clean them up. Because retrieval falls back to pgvector rather
# than failing, this exercises a real code path — the same one that serves
# production whenever Chroma is down. Tests that need Chroma turn it on
# themselves against a throwaway collection (see test_vector_store.py).
os.environ["CHROMA_ENABLED"] = "false"

# The suite exercises the routes, not Clerk. Stating the intent explicitly is
# what the startup guard asks for, and it keeps the tests honest: they run as
# the seeded development user and prove nothing about authentication. The auth
# and ownership paths have their own tests, which configure an issuer and mint
# tokens against a throwaway key (see test_auth.py).
os.environ["ALLOW_UNAUTHENTICATED"] = "true"
# Per-test HTTP calls come from one client and would otherwise trip the
# limiter partway through a suite. Its own behaviour is tested directly.
os.environ["RATE_LIMIT_ENABLED"] = "false"

# Tests get their own database. They used to share the app's, and because
# recover_stranded_jobs() is global, running the suite mutated real rows.
os.environ.setdefault(
    "TEST_DATABASE_URL",
    f"postgresql://research:research@localhost:5433/{TEST_DB_NAME}",
)


def _ensure_test_database(url: str) -> None:
    """Create the test database if absent, then migrate it."""
    parts = urlparse(url)
    admin_url = urlunparse(parts._replace(path="/postgres"))

    with psycopg.connect(admin_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,))
        if cur.fetchone() is None:
            cur.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')

    # Apply migrations with the same runner the app uses, so tests can never
    # drift from production schema.
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "migrate.py")],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": url},
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not migrate the test database:\n{result.stdout}\n{result.stderr}"
        )


_TEST_DB_URL = os.environ["TEST_DATABASE_URL"]
_ensure_test_database(_TEST_DB_URL)
os.environ["DATABASE_URL"] = _TEST_DB_URL

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import get_connection  # noqa: E402
from main import app  # noqa: E402

# A minimal but genuinely valid PDF: correct header, one page, valid xref.
MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj
xref
0 4
0000000000 65535 f
0000000009 00000 n
0000000056 00000 n
0000000111 00000 n
trailer<</Size 4/Root 1 0 R>>
startxref
190
%%EOF
"""


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def project(client: TestClient) -> Iterator[dict]:
    response = client.post(
        "/projects", json={"name": "Test Project", "description": "created by tests"}
    )
    assert response.status_code == 201, response.text
    created = response.json()

    yield created

    # Papers and jobs cascade from the project.
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM projects WHERE id = %s", (created["id"],))
        conn.commit()


@pytest.fixture
def storage_root():
    return get_settings().storage_root
