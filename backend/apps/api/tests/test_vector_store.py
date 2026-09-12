"""Vector store tests: the Chroma path, and the pgvector fallback under it.

The fallback is the part worth testing hardest. It only runs when Chroma is
unavailable, which in normal operation is never — so without a test that
deliberately breaks Chroma, the code that keeps search alive during an outage
would be the code that has never once executed.

Tests that need a live Chroma are skipped, not failed, when none is running:
the suite has to pass on a laptop with no containers. The fallback tests need
nothing and always run.
"""

import os
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.services import vector_store
from app.services.retrieval import retrieve_candidates
from app.services.vector_store import VectorStoreError

TEST_COLLECTION = "aletheia_test_chunks"


def _chroma_available() -> bool:
    """True when a Chroma server answers on the configured host/port."""
    previous = dict(os.environ)
    os.environ["CHROMA_ENABLED"] = "true"
    os.environ["CHROMA_COLLECTION"] = TEST_COLLECTION
    get_settings.cache_clear()
    vector_store.reset_vector_store()
    try:
        return vector_store.is_available()
    finally:
        os.environ.clear()
        os.environ.update(previous)
        get_settings.cache_clear()
        vector_store.reset_vector_store()


needs_chroma = pytest.mark.skipif(
    not _chroma_available(),
    reason="no Chroma server on CHROMA_HOST:CHROMA_PORT (docker compose up -d chroma)",
)


@pytest.fixture
def chroma():
    """Point the vector store at a throwaway collection, and drop it after.

    The collection name differs from the application's so a test run can never
    touch real vectors, and it is deleted on the way out so a re-run starts
    from an empty index rather than inheriting the last run's rows.
    """
    previous = dict(os.environ)
    os.environ["CHROMA_ENABLED"] = "true"
    os.environ["CHROMA_COLLECTION"] = TEST_COLLECTION
    get_settings.cache_clear()
    vector_store.reset_vector_store()

    yield vector_store

    try:
        vector_store.delete_collection()
    except VectorStoreError:
        pass
    os.environ.clear()
    os.environ.update(previous)
    get_settings.cache_clear()
    vector_store.reset_vector_store()


def unit_vector(dimension: int, hot: int) -> list[float]:
    """A one-hot vector, so cosine similarity between two of them is 0 or 1."""
    vector = [0.0] * dimension
    vector[hot] = 1.0
    return vector


# --- the fallback, which needs no Chroma ------------------------------------


def test_disabled_chroma_raises_rather_than_returning_nothing():
    """A disabled store must be distinguishable from an empty one.

    Returning [] here would make retrieval treat "no vector store" as "no
    matching documents" and answer honestly-worded nonsense off zero evidence.
    """
    get_settings.cache_clear()
    vector_store.reset_vector_store()
    with pytest.raises(VectorStoreError, match="disabled"):
        vector_store.query(
            project_id=uuid4(), query_vector=[0.0] * 512, top_k=5
        )


def test_retrieval_falls_back_to_pgvector_when_chroma_is_off(client, project):
    """With CHROMA_ENABLED=false — the suite's default — search still works."""
    assert get_settings().chroma_enabled is False

    response = client.post(
        f"/projects/{project['id']}/search",
        json={"query": "anything at all", "top_k": 5},
    )
    # An empty project has nothing to find; the point is that it answered
    # through pgvector instead of erroring on the missing vector store.
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_fallback_survives_a_chroma_that_fails_mid_query(monkeypatch, project):
    """A store that connects and then throws is still an outage, not an error.

    `get_collection` succeeding does not mean the next call will: a server can
    die between the heartbeat and the query. Retrieval has to absorb that too.
    """

    def explode(**_kwargs):
        raise VectorStoreError("connection reset by peer")

    monkeypatch.setattr("app.services.retrieval.vector_query", explode)

    # Reaches pgvector and returns cleanly rather than propagating.
    results = retrieve_candidates(
        project_id=project["id"], query="anything", top_k=5
    )
    assert results == []


# --- the Chroma path ---------------------------------------------------------


@needs_chroma
def test_upsert_then_query_returns_the_nearest_vector(chroma):
    project_id, paper_id = uuid4(), uuid4()
    ids = [uuid4() for _ in range(3)]

    chroma.upsert_chunks(
        project_id=project_id,
        paper_id=paper_id,
        chunk_ids=ids,
        vectors=[unit_vector(512, i) for i in range(3)],
        contents=["first", "second", "third"],
    )

    hits = chroma.query(
        project_id=project_id, query_vector=unit_vector(512, 1), top_k=3
    )

    assert hits[0].chunk_id == ids[1]
    # Cosine similarity with itself, so the conversion from Chroma's distance
    # is checked too, not just the ordering.
    assert hits[0].similarity == pytest.approx(1.0, abs=1e-5)


@needs_chroma
def test_query_is_scoped_to_one_project(chroma):
    """A vector from another project must not surface, however close it is."""
    mine, theirs = uuid4(), uuid4()
    my_chunk, their_chunk = uuid4(), uuid4()
    identical = unit_vector(512, 7)

    chroma.upsert_chunks(
        project_id=mine, paper_id=uuid4(), chunk_ids=[my_chunk],
        vectors=[identical], contents=["mine"],
    )
    chroma.upsert_chunks(
        project_id=theirs, paper_id=uuid4(), chunk_ids=[their_chunk],
        vectors=[identical], contents=["theirs"],
    )

    hits = chroma.query(project_id=mine, query_vector=identical, top_k=10)

    assert [hit.chunk_id for hit in hits] == [my_chunk]


@needs_chroma
def test_query_can_be_narrowed_to_specific_papers(chroma):
    """Claim verification depends on this: evidence must come from one paper.

    Without the filter a claim would be "supported" by a neighbouring paper's
    text, which is a wrong answer rather than a missing one.
    """
    project_id = uuid4()
    wanted_paper, other_paper = uuid4(), uuid4()
    wanted_chunk, other_chunk = uuid4(), uuid4()

    chroma.upsert_chunks(
        project_id=project_id, paper_id=wanted_paper, chunk_ids=[wanted_chunk],
        vectors=[unit_vector(512, 3)], contents=["wanted"],
    )
    chroma.upsert_chunks(
        project_id=project_id, paper_id=other_paper, chunk_ids=[other_chunk],
        vectors=[unit_vector(512, 3)], contents=["other"],
    )

    hits = chroma.query(
        project_id=project_id,
        query_vector=unit_vector(512, 3),
        top_k=10,
        paper_ids=[wanted_paper],
    )

    assert [hit.chunk_id for hit in hits] == [wanted_chunk]


@needs_chroma
def test_reprocessing_replaces_a_paper_rather_than_duplicating_it(chroma):
    """Upsert on the same ids must not grow the collection."""
    project_id, paper_id = uuid4(), uuid4()
    ids = [uuid4(), uuid4()]

    for content in ("first pass", "second pass"):
        chroma.upsert_chunks(
            project_id=project_id, paper_id=paper_id, chunk_ids=ids,
            vectors=[unit_vector(512, 0), unit_vector(512, 1)],
            contents=[content, content],
        )

    assert chroma.count() == 2


@needs_chroma
def test_delete_paper_removes_only_that_paper(chroma):
    project_id = uuid4()
    doomed, kept = uuid4(), uuid4()
    doomed_chunk, kept_chunk = uuid4(), uuid4()

    chroma.upsert_chunks(
        project_id=project_id, paper_id=doomed, chunk_ids=[doomed_chunk],
        vectors=[unit_vector(512, 0)], contents=["doomed"],
    )
    chroma.upsert_chunks(
        project_id=project_id, paper_id=kept, chunk_ids=[kept_chunk],
        vectors=[unit_vector(512, 1)], contents=["kept"],
    )

    chroma.delete_paper(doomed)

    remaining = chroma.query(
        project_id=project_id, query_vector=unit_vector(512, 0), top_k=10
    )
    assert [hit.chunk_id for hit in remaining] == [kept_chunk]


@needs_chroma
def test_misaligned_batch_is_refused_before_it_is_written(chroma):
    """Storing 3 ids against 2 vectors would silently mislabel every vector."""
    with pytest.raises(VectorStoreError, match="misaligned"):
        chroma.upsert_chunks(
            project_id=uuid4(),
            paper_id=uuid4(),
            chunk_ids=[uuid4(), uuid4(), uuid4()],
            vectors=[unit_vector(512, 0), unit_vector(512, 1)],
            contents=["a", "b", "c"],
        )
    assert chroma.count() == 0


@needs_chroma
def test_hydrate_skips_vectors_whose_chunk_is_gone_from_postgres(chroma):
    """A stale vector must not become a citation to a paper that was deleted.

    This is reachable in production: a delete that reaches Postgres but not
    Chroma leaves exactly this state behind.
    """
    from app.services.retrieval import _hydrate
    from app.services.vector_store import VectorHit

    assert _hydrate([VectorHit(chunk_id=uuid4(), similarity=0.99)]) == []
