"""The pieces that let the API run as a Vercel function (api/index.py).

Hosted embeddings, the model-free reranker, Postgres-backed storage, chunked
uploads, age-bounded stranded-job recovery and the read-only session cookie.
None of them needs the network: the hosted provider is driven through a stubbed
`httpx.post`.
"""

import hashlib
import math
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.core.auth import _bearer_token
from app.core.config import get_settings
from app.db.session import get_connection
from app.services.embedding import (
    EMBEDDING_DIM,
    EmbeddingError,
    EstimatingTokenCounter,
    HostedEmbeddingProvider,
)
from app.services.ingestion import recover_stranded_jobs
from app.services.reranking import RetrievalOrderReranker
from app.services.storage import PostgresStorage, StorageError
from tests.conftest import MINIMAL_PDF


def _provider(api_key="sk-test"):
    return HostedEmbeddingProvider(
        vendor="openai",
        api_key=api_key,
        model="text-embedding-3-small",
        base_url="https://example.invalid/v1/",
        key_env="OPENAI_API_KEY",
    )


def _stub_post(monkeypatch, *, status=200, dims=768, seen=None):
    def fake_post(url, *, headers, json, timeout):
        if seen is not None:
            seen.update(url=url, headers=headers, json=json)
        # Out of order on purpose: the provider must sort by `index`.
        data = [
            {"index": i, "embedding": [float(i + 1)] + [0.0] * (dims - 1)}
            for i in range(len(json["input"]))
        ][::-1]
        return httpx.Response(status, json={"data": data} if status == 200 else {})

    monkeypatch.setattr(httpx, "post", fake_post)


def test_hosted_embeddings_are_ordered_truncated_and_normalised(monkeypatch):
    seen = {}
    _stub_post(monkeypatch, seen=seen)

    vectors = _provider().embed(texts=["a", "b", "c"])

    assert seen["url"] == "https://example.invalid/v1/embeddings"
    assert seen["headers"]["Authorization"] == "Bearer sk-test"
    assert seen["json"]["dimensions"] == EMBEDDING_DIM
    assert [len(v) for v in vectors] == [EMBEDDING_DIM] * 3
    for vector in vectors:
        assert math.isclose(sum(x * x for x in vector), 1.0)
    # Matching input order, even though the response arrived reversed.
    assert vectors[0][0] == vectors[1][0] == vectors[2][0] == 1.0


def test_hosted_embeddings_name_the_vendor_and_fail_loudly(monkeypatch):
    assert _provider().name == "openai/text-embedding-3-small"

    with pytest.raises(EmbeddingError, match="OPENAI_API_KEY"):
        _provider(api_key="").embed(texts=["x"])

    _stub_post(monkeypatch, status=401)
    with pytest.raises(EmbeddingError, match="401"):
        _provider().embed(texts=["x"])


def test_estimating_token_counter_errs_high():
    counter = EstimatingTokenCounter()
    assert counter.count("") == 0
    # 4 words + 1 punctuation piece = 5 pieces, scaled by 1.3 and rounded up.
    assert counter.count("Attention is all you.") == 7


def test_retrieval_order_reranker_keeps_order_and_caps():
    ranked = RetrievalOrderReranker().rerank(
        query="q", chunks=[("a", "x"), ("b", "y"), ("c", "z")], top_k=2
    )
    assert [r.chunk_id for r in ranked] == ["a", "b"]
    assert ranked[0].score > ranked[1].score


def test_postgres_storage_round_trip():
    storage = PostgresStorage()
    key = f"test/{uuid4()}.bin"

    assert storage.store(key=key, data=b"one") == key
    assert storage.exists(key=key)
    storage.store(key=key, data=b"two")  # overwrite, not a duplicate-key error
    assert storage.read(key=key) == b"two"
    storage.delete(key=key)
    assert not storage.exists(key=key)
    with pytest.raises(StorageError):
        storage.read(key=key)
    with pytest.raises(StorageError):
        storage.store(key="../escape", data=b"x")


def test_chunked_upload_joins_parts_into_one_paper(client, project, storage_root):
    pid = project["id"]
    started = client.post(f"/projects/{pid}/uploads")
    assert started.status_code == 201, started.text
    upload_id = started.json()["upload_id"]

    half = len(MINIMAL_PDF) // 2
    for index, part in enumerate([MINIMAL_PDF[:half], MINIMAL_PDF[half:]]):
        response = client.put(
            f"/projects/{pid}/uploads/{upload_id}/parts/{index}", content=part
        )
        assert response.status_code == 204, response.text

    done = client.post(
        f"/projects/{pid}/uploads/{upload_id}/complete",
        json={"filename": "parts.pdf", "content_type": "application/pdf", "part_count": 2},
    )
    assert done.status_code == 201, done.text
    body = done.json()
    assert body["filename"] == "parts.pdf"
    assert body["sha256"] == hashlib.sha256(MINIMAL_PDF).hexdigest()
    assert (storage_root / body["storage_path"]).read_bytes() == MINIMAL_PDF
    # Scratch parts are gone once joined.
    parts_dir = storage_root / "_uploads" / pid / upload_id
    assert not parts_dir.exists() or not any(parts_dir.iterdir())


def test_chunked_upload_rejects_missing_and_oversized_parts(client, project):
    pid = project["id"]
    upload_id = client.post(f"/projects/{pid}/uploads").json()["upload_id"]

    missing = client.post(
        f"/projects/{pid}/uploads/{upload_id}/complete",
        json={"filename": "x.pdf", "part_count": 1},
    )
    assert missing.status_code == 400
    assert "missing" in missing.json()["detail"]

    too_big = client.put(
        f"/projects/{pid}/uploads/{upload_id}/parts/0",
        content=b"x" * (4 * 1024 * 1024 + 1),
    )
    assert too_big.status_code == 413

    bad_index = client.put(f"/projects/{pid}/uploads/{upload_id}/parts/-1", content=b"x")
    assert bad_index.status_code in {400, 422}


def test_stranded_recovery_spares_recent_jobs(client, project, monkeypatch):
    upload = client.post(
        f"/projects/{project['id']}/papers",
        files={"file": ("p.pdf", MINIMAL_PDF, "application/pdf")},
    )
    paper_id = upload.json()["id"]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE processing_jobs SET status = 'running', updated_at = now()"
            " WHERE paper_id = %s",
            (paper_id,),
        )
        conn.commit()

    monkeypatch.setattr(get_settings(), "stranded_job_after_seconds", 900)
    recover_stranded_jobs()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM processing_jobs WHERE paper_id = %s", (paper_id,)
        )
        assert cur.fetchone()["status"] == "running"

        cur.execute(
            "UPDATE processing_jobs SET updated_at = now() - interval '1 hour'"
            " WHERE paper_id = %s",
            (paper_id,),
        )
        conn.commit()

    recover_stranded_jobs()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM processing_jobs WHERE paper_id = %s", (paper_id,)
        )
        assert cur.fetchone()["status"] == "failed"


def _request(method, headers=None, cookies=None):
    return SimpleNamespace(
        method=method, headers=headers or {}, cookies=cookies or {}
    )


def test_session_cookie_authenticates_reads_only():
    assert _bearer_token(_request("GET", {"authorization": "Bearer abc"})) == "abc"
    assert _bearer_token(_request("GET", cookies={"__session": "jwt"})) == "jwt"
    # A cookie rides along on cross-site form posts; writes need the header.
    assert _bearer_token(_request("POST", cookies={"__session": "jwt"})) is None
    assert _bearer_token(_request("DELETE", cookies={"__session": "jwt"})) is None
